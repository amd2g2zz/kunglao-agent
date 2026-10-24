#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capability_probe.py — dispatch-gate capability probes + TTL fact cache
(#812).

The production incident (logs-panel RC5, issue #812): dynamic-trace was
dispatched 9x on hosts lacking frida (host ModuleNotFoundError at 14:58;
dep_surface_gate only flagged the gap next morning 08:08), and a "device
has no root" verdict became reportable because NO positive control
separated host-tool-absent from device-unrooted — the canonical
`adb shell su -c id` check (kunglao-init HARD gate) never executed on the
machine surface while the conclusion was being narrated. Machine logs
showed ZERO root checks.

Two structural fixes, both pinned by tests/test_capability_probes_812.py:

SEPARATE FACTS
  The host-side face (`frida --version`) and the device-side face
  (`adb shell su -c id`) are DISTINCT capabilities (`host_frida`,
  `device_root`). A host probe failure says NOTHING about device state
  and vice versa. The separation trap is pinned hardest on the skip
  semantics: adb absent on PATH is a channel-absent SKIP, never a
  device-root FAIL — the misattribution class is unrepresentable.

TTL FACT CACHE
  #475 fixed the periodic contract (per-dispatch probing violates the
  env_check_gate narrow+low-IO shape); #812 moves the CONSULTATION to the
  dispatch gate. Reconciliation: the gate consults facts, not commands —
  fresh entries (env-state.json snapshot first, the single source of
  truth writer, then the gate-local cache) answer without executing
  anything; a stale/missing REQUIRED fact is probed once on demand and
  cached for PROBE_TTL_SECONDS. A probe failure is a fact too (negative
  results cache within TTL — the dead lane is not re-probed per
  dispatch).

Conservative rule (#421, unchanged): an absent/stale/unprobed/crashed
probe is a SKIP — absence of evidence is NOT evidence of absence. Only
an executed probe with an honest negative detail produces "fail".

Test contract: probes NEVER execute real commands in tests. Behavior is
pinned via an injected `run` callable; the real argv assembly is pinned
by a recording injection (["frida", "--version"] /
["<adb>", "shell", "su", "-c", "id"]).
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# facts fresher than this answer without executing anything; a required
# fact older than TTL is re-probed once on demand (documented policy
# constant, not a fitted parameter)
PROBE_TTL_SECONDS = 300

#: the #812 capability pair — SEPARATE facts by contract (issue acceptance 1)
CAPABILITY_NAMES = ("host_frida", "device_root")

CACHE_REL = Path("runs") / ".capability-probe-cache.json"
ENV_STATE_REL = Path("runs") / "env-state.json"

 #: canonical probe commands (pinned verbatim by the injection tests)
HOST_FRIDA_ARGV = ("frida", "--version")
DEVICE_ROOT_ARGV_TAIL = ("shell", "su", "-c", "id")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _default_run(argv: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """The ONLY place real commands execute: the toolchain #474 runner
    (single source). Tests inject `run` and never reach this. Lazy
    sibling import: every production importer (env_state_probe,
    dispatch_gate via scripts_on_path) has scripts/ on sys.path before
    this resolves."""
    import toolchain as tc
    return tc._run_cmd(list(argv), timeout=timeout)


# ------------------------------------------------------- the probe faces

def probe_host_frida(run=None) -> tuple[str, str]:
    """HOST-side frida CLI face (`frida --version`). rc==0 -> pass; any
    nonzero rc -> fail (the detail carries the real error — the 14:58
    ModuleNotFoundError class); a crashed probe -> skip (conservative)."""
    runner = run or _default_run
    try:
        rc, out, err = runner(list(HOST_FRIDA_ARGV))
    except Exception as exc:  # exec outage is no evidence of absence
        return ("skip", f"probe crashed: {type(exc).__name__}: {exc}")
    version = (out or "").strip().splitlines()[0][:40] if (out or "").strip() \
        else ""
    if rc == 0:
        return ("pass", f"frida {version}".strip())
    return ("fail", (err or out or f"rc={rc}").strip()[:120])


def probe_device_root(run=None, adb: str | None = None) -> tuple[str, str]:
    """DEVICE-side root face (the kunglao-init canonical check:
    `adb shell su -c id`). uid=0 in the reply -> pass.

    adb=<None> is a channel-absent SKIP — never a device-root FAIL (the
    incident pin: a host without adb cannot speak about device state).
    Resolution of the adb path is the CALLER's job (env_state_probe's
    _adb_path); the probe itself stays pure."""
    if adb is None:
        return ("skip", "adb path unresolved — device root UNVERIFIED "
                        "(channel absent, not device-unrooted)")
    runner = run or _default_run
    argv = [adb, *DEVICE_ROOT_ARGV_TAIL]
    try:
        rc, out, err = runner(argv)
    except Exception as exc:
        return ("skip", f"probe crashed: {type(exc).__name__}: {exc}")
    reply = (out or "").strip()
    if rc == 0 and "uid=0" in reply:
        return ("pass", f"root confirmed: {reply.splitlines()[0][:60]}")
    if rc == 0:
        return ("fail", f"su present but not root: {reply[:80]}")
    return ("fail", (err or reply or f"rc={rc}").strip()[:120])


_PROBE_ADB = None  # bound once per facts() call (the caller's channel)


def _probe_device_root_channel(run=None) -> tuple[str, str]:
    return probe_device_root(run=run, adb=_PROBE_ADB or shutil.which("adb"))


#: name -> probe face (unknown names never fabricate — they skip)
PROBES = {
    "host_frida": probe_host_frida,
    "device_root": _probe_device_root_channel,
}


# ------------------------------------------------- the family vocabulary

#: (family, prompt-keyword triggers, required capabilities, alternative arm)
#: Alternative arms are concrete pivots (the offline-recompute lane the
#: PoW bet already proved) — a refusal without an exit is a wall, not a
#: gate.
ANDROID_FAMILIES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str],
                        ...] = (
    ("android-dynamic-trace",
     ("frida", "stalker", "hook", "instrument", "dynamic-trace"),
     ("host_frida",),
     "offline-recompute: the static arm on the captured artifact "
     "(ghidra headless / jadx), or move the dynamic leg to a host with "
     "the frida CLI installed"),
    ("android-root-instrument",
     ("root", "su -c", "/proc/", "mem dump", "memory dump"),
     ("device_root",),
     "offline-recompute: the static arm (baksmali/smali constants walk), "
     "or schedule the root-required leg onto the rooted device channel"),
    ("android-jdwp",
     ("jdwp", "jdb ", "debug-flag"),
     ("jdwp_debug",),
     "offline-recompute: the static bytecode arm while the debuggable "
     "channel is down (start the target with the JDWP flag, then "
     "re-dispatch)"),
)


def match_required(prompt_text: str | None,
                   project_type: str | None) -> list[tuple[str, tuple[str, ...]]]:
    """(family, required-capabilities) pairs whose keyword triggers appear
    in the dispatch prompt. Android-scoped: the keywords misfire on other
    lanes (web JS hooking is camoufox, not frida), so a non-android
    project type never matches."""
    if str(project_type or "").strip() != "android":
        return []
    text = str(prompt_text or "").lower()
    out: list[tuple[str, tuple[str, ...]]] = []
    for family, triggers, caps, _alt in ANDROID_FAMILIES:
        if any(t in text for t in triggers):
            out.append((family, caps))
    return out


def alternative_for(family: str) -> str | None:
    """The family's alternative-arm suggestion (None for unknown)."""
    for fam, _triggers, _caps, alt in ANDROID_FAMILIES:
        if fam == family:
            return alt
    return None


# ------------------------------------------------------- the TTL cache

def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_cache(ws: Path, cache: dict) -> None:
    path = Path(ws) / CACHE_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        from kunglao_log import warn
        warn("capability_probe_cache", "cache write failed (best-effort)")


def _fresh(entry, now: datetime, ttl: int) -> bool:
    ts = _parse_ts((entry or {}).get("ts")
                   or (entry or {}).get("last_probe_ts"))
    if ts is None:
        return False
    return abs((now - ts).total_seconds()) <= ttl


def facts(ws, required, *, now=None, run=None,
          ttl: int = PROBE_TTL_SECONDS) -> dict:
    """The dispatch-gate consultation face: {name: entry} for the REQUIRED
    capabilities. Resolution order per name — fresh env-state.json
    snapshot entry (the #475 single source), fresh gate cache, on-demand
    probe (executed once, cached). Unknown names yield an honest skip —
    never a fabricated fact."""
    ws = Path(ws)
    now = now or _utc_now()
    global _PROBE_ADB
    _PROBE_ADB = shutil.which("adb")
    snapshot = (_read_json(ws / ENV_STATE_REL).get("per_capability") or {})
    cache = _read_json(ws / CACHE_REL)
    out: dict[str, dict] = {}
    mutated = False
    for name in required:
        snap_entry = snapshot.get(name)
        if isinstance(snap_entry, dict) and _fresh(snap_entry, now, ttl):
            out[name] = {"status": str(snap_entry.get("status")),
                         "detail": str(snap_entry.get("detail") or ""),
                         "ts": str(snap_entry.get("last_probe_ts") or ""),
                         "source": "env-state"}
            continue
        cached = cache.get(name)
        if isinstance(cached, dict) and _fresh(cached, now, ttl):
            out[name] = {**cached, "source": "cache"}
            continue
        probe = PROBES.get(name)
        if probe is None:
            out[name] = {"status": "skip",
                         "detail": f"no probe registered for {name}",
                         "ts": now.isoformat(timespec="seconds")
                         .replace("+00:00", "Z"), "source": "none"}
            continue
        status, detail = probe(run=run)
        entry = {"status": status, "detail": detail,
                 "ts": now.isoformat(timespec="seconds")
                 .replace("+00:00", "Z")}
        cache[name] = entry
        mutated = True
        out[name] = {**entry, "source": "probe"}
    if mutated:
        _write_cache(ws, cache)
    return out
