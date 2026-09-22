#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""premise_gate.py — premise-probe reconciliation + premise expiry (#340).

A locally-coherent false belief can only be broken by an information
channel the belief-holder did not generate (#340 design axiom). This
module routes that channel; nobody "realizes" anything:

B — premise-probe reconciliation (wired at the dispatch seam,
hooks/worker_budget_sinks.check_env_premise, the same face that runs
check_env_fresh): when a dispatch needs capability X (the
`_env_caps_needed` vocabulary — the single source of capability names),
an ACTIVE env-attribution premise in blockers/*.md claims X unavailable,
and runs/env-state.json shows X liveness PASS, two machine-readable
records disagree and the PROBE wins:
  1. the premise is marked SUSPECT by an APPEND-ONLY history line in the
     blocker file (never a silent rewrite);
  2. a ONE-SHOT on-demand capability re-probe is scheduled
     (runs/.env-reprobe-pending.json; consumed through the #474 on-demand
     channel — scripts/toolchain.py --capability — never a reinvented
     probe);
  3. the contradiction is emitted to the event ledger as the registered
     word `env_premise_contradiction` (scripts/event_taxonomy.py
     EMIT_ACTIONS — no ad-hoc strings).
The dispatch itself is NEVER rejected on the stale premise. Missing/
unreadable env-state.json keeps the existing fail-open behavior.

C — premise expiry (the tick-hosted clock): declared in
scripts/mechanisms.yaml as mechanism `premise_expiry` (channel tick). A
v2 env-class blocker whose probe_evidence has not refreshed within
`expires` ticks (int; default DEFAULT_EXPIRY_TICKS, env
KUNGLAO_PREMISE_EXPIRY_TICKS) or past its ISO deadline gets an
INVALIDATED(stale) history line appended. The line is what
convergence_check._active_blockers keys on, so the premise stops being
active and re-derivation is forced on next need. Append-only: previous
history bytes are always a byte-prefix of the new file. Legacy-shape
files are NOT migrated (no-backcompat 2026-09-01) — the write gate
rejects them on touch; this sweep skips them.

Tick accounting: runs/.premise-expiry.json carries a monotonic tick
counter (incremented once per sweep pass — the mechanism runs once per
heartbeat_tick) and, per blocker stem, the sha256 of the probe_evidence
value last seen. A changed probe_evidence value IS a re-verification:
its clock restarts.

CLI (mechanism entry): premise_gate.py <workspace> [--json]
Exit 0 always — advisory mechanism, never tick-fatal.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import kunglao_log

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import blocker_lint  # noqa: E402  (frontmatter parse + pattern set)

ENV_STATE_REL = Path("runs") / "env-state.json"
PREMISE_STATE_REL = Path("runs") / ".premise-expiry.json"
REPROBE_PENDING_REL = Path("runs") / ".env-reprobe-pending.json"
REPROBE_SCRIPT = "toolchain.py"

DEFAULT_EXPIRY_TICKS = 12
REPROBE_MAX_ATTEMPTS = 3
REPROBE_TIMEOUT_S = 50  # inside the scheduler runner's 60s window

from harness_common import utc_now_z as utc_now  # noqa: E402  # #863 Family F

# premise text → capability keyword map. KEYED BY the `_env_caps_needed`
# vocabulary (hooks/worker_budget_sinks) — that function is the single
# source of capability names; this map only decides which premise TEXTS
# speak about which capability.
CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vm_reachable": ("vm", "vmware", "vmr", "ssh", "docker", "x64dbg",
                     "frida", "adb", "device", "emulator", "detonat"),
    "mcp_bridge": ("ghidra", "ida", "mcp", "decompil", "bridge"),
    "jdwp_debug": ("jdwp", "jdb", "android debug", "java debug"),
}


def _warn(op: str, reason: str) -> None:
    print(f"[kunglao-agent] premise_gate WARN (fail-open): {op}: {reason}",
          file=sys.stderr)


# ---------------------------------------------------------------------------
# B: premise scan + SUSPECT marking + re-probe scheduling + event
# ---------------------------------------------------------------------------

def _blocker_files(ws: Path) -> list[Path]:
    bdir = Path(ws) / "blockers"
    if not bdir.is_dir():
        return []
    return sorted(p for p in bdir.glob("*.md")
                  if p.is_file() and p.name != "README.md")


def active_env_premises(ws: Path) -> list[dict]:
    """Active env-class premises: v2 blockers whose text makes an
    environment-capability attribution and carries no INVALIDATED marker
    (mirrors convergence_check._active_blockers' exclusion)."""
    out: list[dict] = []
    for p in _blocker_files(ws):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INVALIDATED" in text.upper():
            continue
        phrases = blocker_lint.match_env_attribution(text)
        if not phrases:
            continue
        out.append({"path": p, "stem": p.stem, "text": text,
                    "phrases": phrases})
    return out


def premises_for_caps(ws: Path, needed_caps: set[str]) -> list[dict]:
    """Premises claiming one of `needed_caps` unavailable: an env
    attribution phrase present AND a keyword of that capability in the
    text. The caller passes the `_env_caps_needed(tier, tools)` output —
    that vocabulary is the single source of capability names."""
    hits: list[dict] = []
    for prem in active_env_premises(ws):
        low = prem["text"].lower()
        for cap in sorted(needed_caps):
            if any(kw in low for kw in CAPABILITY_KEYWORDS.get(cap, ())):
                hits.append({**prem, "cap": cap})
    return hits


def mark_suspect(ws: Path, premise_stem: str, cap: str, probe_ts: str,
                 detail: str = "") -> bool:
    """Append one SUSPECT history line to the blocker file (append-only).
    Deduped per (cap, probe_ts): the same probe snapshot never produces
    duplicate markers; a FRESH probe ts is new evidence → a new marker.
    Returns True when a line was appended."""
    p = Path(ws) / "blockers" / f"{premise_stem}.md"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # dedupe: an existing SUSPECT line for the SAME cap against the SAME
    # probe snapshot is not new evidence
    needle = f"(probe {probe_ts or 'ts-unreadable'})"
    for ln in text.splitlines():
        if ("[SUSPECT]" in ln and f"`{cap}`" in ln and needle in ln):
            return False
    line = (f"- [SUSPECT] `{cap}` unavailable vs PASS {utc_now()} "
            f"env_premise_contradiction: premise claims `{cap}` unavailable, "
            f"but runs/env-state.json recorded `{cap}` PASS "
            f"(probe {probe_ts or 'ts-unreadable'}) — probe wins; "
            "one-shot capability re-probe scheduled (#340)"
            + (f"; {detail}" if detail else ""))
    try:
        with p.open("a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
    except OSError as exc:
        _warn("mark_suspect", f"{type(exc).__name__}: {exc}")
        return False
    return True


def schedule_reprobe(ws: Path, caps: set[str], reason: str,
                     blocker_stems: list[str]) -> Path:
    """Merge `caps` into the one-shot pending file (idempotent per cap —
    one pending request carries every contradicting capability until the
    consumer executes it once through the #474 on-demand channel)."""
    p = Path(ws) / REPROBE_PENDING_REL
    data: dict = {}
    try:
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    merged = sorted(set(data.get("caps") or []) | set(caps))
    stems = sorted(set(data.get("blockers") or []) | set(blocker_stems))
    data.update({"caps": merged, "blockers": stems, "reason": reason,
                 "ts": utc_now(),
                 "attempts": int(data.get("attempts") or 0)})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        _warn("schedule_reprobe", f"{type(exc).__name__}: {exc}")
    return p


def _emit_contradiction(ws: Path, premise_stem: str, cap: str,
                        probe_ts: str) -> None:
    try:
        kunglao_log.emit(Path(ws), "premise_gate",
                         "env_premise_contradiction",
                         artifact=f"blockers/{premise_stem}.md",
                         detail=("premise claims "
                                 f"`{cap}` unavailable while env-state "
                                 f"shows PASS (probe {probe_ts or 'n/a'}); "
                                 "premise marked SUSPECT, one-shot "
                                 "capability re-probe scheduled"))
    except Exception as exc:  # noqa: BLE001 — logging never breaks the gate
        _warn("_emit_contradiction", f"{type(exc).__name__}: {exc}")


def reconcile_dispatch(ws: Path, needed_caps: set[str],
                       per_capability: dict) -> list[dict]:
    """The reconciliation face for one dispatch. `needed_caps` is the
    `_env_caps_needed(tier, tools)` output; `per_capability` the parsed
    runs/env-state.json map. Only a liveness PASS triggers the
    contradiction (a FAIL agrees with the premise — check_env_fresh's
    existing reject path owns that face). Never raises; never blocks."""
    contradictions: list[dict] = []
    try:
        for prem in premises_for_caps(ws, needed_caps):
            cap = prem["cap"]
            entry = per_capability.get(cap)
            if not isinstance(entry, dict) or entry.get("status") != "pass":
                continue  # PASS is the only contradiction trigger
            probe_ts = str(entry.get("last_probe_ts") or "")
            if mark_suspect(ws, prem["stem"], cap, probe_ts):
                schedule_reprobe(ws, {cap}, "env_premise_contradiction",
                                 [prem["stem"]])
                _emit_contradiction(ws, prem["stem"], cap, probe_ts)
            contradictions.append({"blocker": prem["stem"], "cap": cap,
                                   "probe_ts": probe_ts})
    except Exception as exc:  # noqa: BLE001 — reconciliation never blocks
        _warn("reconcile_dispatch", f"{type(exc).__name__}: {exc}")
    return contradictions


def _append_history(p: Path, text: str, line: str) -> bool:
    """Append one history line; the previous bytes stay a byte-prefix."""
    try:
        with p.open("a", encoding="utf-8") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
        return True
    except OSError as exc:
        _warn("_append_history", f"{type(exc).__name__}: {exc}")
        return False


# ---------------------------------------------------------------------------
# B: one-shot re-probe consumer (the #474 on-demand channel)
# ---------------------------------------------------------------------------

def _load_pending(ws: Path) -> dict | None:
    try:
        pending = json.loads((Path(ws) / REPROBE_PENDING_REL)
                             .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return pending if isinstance(pending, dict) else None


def _note_blockers(ws: Path, stems: list[str], line: str) -> None:
    """Append an outcome line to every implicated blocker's history."""
    for stem in stems:
        bp = Path(ws) / "blockers" / f"{stem}.md"
        try:
            text = bp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _append_history(bp, text, line)


def _project_type(ws: Path) -> str | None:
    try:
        from init_state import read_project_type
        return read_project_type(ws)
    except Exception as exc:  # noqa: BLE001 — probe intake must not raise
        _warn("run_pending_reprobe", f"project_type: {type(exc).__name__}: {exc}")
        return None


def _default_runner(argv: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8",
                           errors="replace")
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"{type(exc).__name__}: {exc}"


def _reprobe_argv(ws: Path, ptype: str) -> list[str]:
    """The #474 on-demand capability channel — reused, never reinvented."""
    return [sys.executable, str(_SCRIPT_DIR / REPROBE_SCRIPT), str(ws),
            "--type", str(ptype), "--capability", "--json"]


def _reprobe_failure(ws: Path, p: Path, pending: dict, stems: list[str],
                     rc: int, err: str, out: str) -> dict:
    attempts = int(pending.get("attempts") or 0) + 1
    if attempts >= REPROBE_MAX_ATTEMPTS:
        _note_blockers(ws, stems, f"- re-probe {utc_now()}: FAILED after "
                       f"{attempts} attempt(s) (last rc={rc}: "
                       f"{(err or out)[:160]}) — premise stays SUSPECT; "
                       "run scripts/toolchain.py --capability manually "
                       "(#340)")
        p.unlink(missing_ok=True)
        return {"ran": True, "outcome": "failed_consumed", "attempts": attempts}
    pending["attempts"] = attempts
    try:
        p.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    except OSError as exc:
        _warn("run_pending_reprobe", f"{type(exc).__name__}: {exc}")
    return {"ran": True, "outcome": "retry_scheduled", "attempts": attempts}


def _reprobe_success(ws: Path, p: Path, stems: list[str],
                     out: str) -> dict:
    """Land the evidence, note the outcome, consume the one-shot."""
    ev_name = f"env-reprobe-{utc_now().replace(':', '')}.json"
    try:
        (ws / "runs" / ev_name).write_text(out or "{}", encoding="utf-8")
    except OSError as exc:
        _warn("run_pending_reprobe", f"evidence: {type(exc).__name__}: {exc}")
    status = "completed"
    try:
        report = json.loads(out or "{}")
        if isinstance(report, dict) and report.get("overall_status"):
            status = str(report["overall_status"])
    except ValueError:
        pass
    _note_blockers(ws, stems, f"- re-probe {utc_now()}: capability re-probe "
                   f"completed: {status} (evidence runs/{ev_name}, via "
                   "toolchain.py --capability #474/#340) — reconcile the "
                   "premise against this evidence; a PASS makes the "
                   "premise false")
    p.unlink(missing_ok=True)
    return {"ran": True, "outcome": status}


def run_pending_reprobe(ws: Path, runner=None) -> dict:
    """Execute the pending one-shot re-probe through the existing #474
    on-demand capability channel (scripts/toolchain.py --capability).

    `runner(argv, timeout) -> (rc, stdout, stderr)` is the injection seam
    for tests; the default runs the subprocess bounded to REPROBE_TIMEOUT_S
    (inside the scheduler runner's 60s window). One-shot semantics: the
    pending file is consumed on a completed probe OR after
    REPROBE_MAX_ATTEMPTS failed attempts (honest failure note appended) —
    a transient failure keeps it pending so the next tick retries."""
    ws = Path(ws)
    p = ws / REPROBE_PENDING_REL
    pending = _load_pending(ws)
    if pending is None:
        return {"ran": False, "reason": "no pending re-probe"}
    stems = [str(s) for s in (pending.get("blockers") or [])]
    ptype = _project_type(ws)
    if ptype is None:
        _note_blockers(ws, stems, f"- re-probe {utc_now()}: NOT RUN — "
                       "project_type undeclared, the #474 on-demand "
                       "capability channel has no manifest to probe "
                       "against; premise stays SUSPECT until a manual "
                       "re-verification (#340)")
        p.unlink(missing_ok=True)
        return {"ran": True, "outcome": "skipped_no_project_type"}
    if runner is None:
        runner = _default_runner
    rc, out, err = runner(_reprobe_argv(ws, ptype), REPROBE_TIMEOUT_S)
    if rc != 0:
        return _reprobe_failure(ws, p, pending, stems, rc, err, out)
    return _reprobe_success(ws, p, stems, out)


# ---------------------------------------------------------------------------
# C: premise expiry sweep (the tick-hosted clock)
# ---------------------------------------------------------------------------

def _expiry_ticks() -> int:
    raw = os.environ.get("KUNGLAO_PREMISE_EXPIRY_TICKS")
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError as exc:
            _warn("_expiry_ticks", f"{type(exc).__name__}: {exc}")
    return DEFAULT_EXPIRY_TICKS


def _load_expiry_state(ws: Path) -> dict:
    try:
        data = json.loads((Path(ws) / PREMISE_STATE_REL)
                          .read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_expiry_state(ws: Path, state: dict) -> None:
    p = Path(ws) / PREMISE_STATE_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        _warn("_write_expiry_state", f"{type(exc).__name__}: {exc}")


def expire_stale(ws: Path, *, now: datetime | None = None) -> list[dict]:
    """One sweep pass: +1 tick; env-class v2 blockers whose probe evidence
    did not refresh within their `expires` window are marked
    INVALIDATED(stale) by an appended history line. Returns the list of
    invalidations. Idempotent: an already-marked file is skipped (the
    INVALIDATED marker itself excludes it from every later pass)."""
    ws = Path(ws)
    state = _load_expiry_state(ws)
    tick = int(state.get("tick") or 0) + 1
    per = state.get("blockers") if isinstance(state.get("blockers"), dict) \
        else {}
    per = dict(per)
    invalidated: list[dict] = []
    now = now or datetime.now(timezone.utc)
    for p in _blocker_files(ws):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INVALIDATED" in text.upper():
            continue  # resolved (or stale-invalidated) — nothing to do
        if not blocker_lint.match_env_attribution(text):
            continue  # not an env-class premise (B2 user-stop etc.)
        meta, _ = blocker_lint.parse_frontmatter(text)
        if meta is None:
            continue  # no-compat: legacy shape is not migrated by the sweep
        pe_sha = hashlib.sha256(
            str(meta.get("probe_evidence") or "").encode("utf-8")).hexdigest()
        st = dict(per.get(p.stem) or {})
        if st.get("probe_sha") != pe_sha:
            st = {"probe_sha": pe_sha, "first_seen_tick": tick}
        age = tick - int(st.get("first_seen_tick") or tick)
        expires = blocker_lint.parse_expires(meta.get("expires"))
        due, why = False, ""
        if isinstance(expires, datetime):
            if now >= expires:
                due, why = True, f"ISO deadline {expires.isoformat()} reached"
        else:
            limit = expires if isinstance(expires, int) else _expiry_ticks()
            if age >= limit:
                due, why = True, f"{age} ticks without probe-evidence " \
                                 f"refresh (expires {limit})"
        if due:
            line = (f"- INVALIDATED(stale) {utc_now()}: env-class premise "
                    f"unverified — {why}; forced re-derivation on next need "
                    "(premise expiry, #340)")
            if _append_history(p, text, line):
                st["invalidated_tick"] = tick
                invalidated.append({"blocker": p.stem, "why": why})
        per[p.stem] = st
    _write_expiry_state(ws, {"schema": 1, "tick": tick, "blockers": per})
    return invalidated


# ---------------------------------------------------------------------------
# CLI (mechanism entry — mechanisms.yaml `premise_expiry`)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    from _boot import reconfigure_stdout
    reconfigure_stdout()
    args = [a for a in (argv if argv is not None else sys.argv[1:])
            if a != "--json"]
    if not args:
        print("usage: premise_gate.py <workspace> [--json]", file=sys.stderr)
        return 2
    ws = Path(args[0]).resolve()
    if not ws.is_dir():
        print(f"ERROR: workspace {ws} is not an existing directory",
              file=sys.stderr)
        return 2
    as_json = "--json" in (argv if argv is not None else sys.argv[1:])
    try:
        invalidated = expire_stale(ws)
    except Exception as exc:  # noqa: BLE001 — the sweep never fails the tick
        invalidated = []
        _warn("expire_stale", f"{type(exc).__name__}: {exc}")
    try:
        reprobe = run_pending_reprobe(ws)
    except Exception as exc:  # noqa: BLE001
        reprobe = {"ran": False, "reason": f"{type(exc).__name__}: {exc}"}
    out = {"ts": utc_now(), "invalidated": invalidated, "reprobe": reprobe}
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        for item in invalidated:
            print(f"premise_expiry: INVALIDATED(stale) {item['blocker']} "
                  f"({item['why']})")
        if reprobe.get("ran"):
            print(f"premise_gate: re-probe {reprobe.get('outcome')}")
    return 0  # advisory mechanism — never tick-fatal


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
