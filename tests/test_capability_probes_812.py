#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_capability_probes_812.py — #812 dispatch-gate capability probes.

The production incident (logs-panel RC5): dynamic-trace was dispatched 9x
on hosts lacking frida (host ModuleNotFoundError at 14:58; dep_surface_gate
only flagged the gap next morning), and the "device has no root" verdict
became reportable because NO positive control separated host-tool-absent
from device-unrooted — the canonical `adb shell su -c id` check never
executed while the conclusion was being narrated.

Faces pinned here:
  1. scripts/capability_probe.py — host-side (`frida --version`) and
     device-side (`adb shell su -c id`) probes recorded as SEPARATE
     capability facts; the misattribution trap is pinned structurally:
     no adb on PATH is a SKIP (channel absent), NEVER a device-root FAIL.
     Probes never execute real commands in tests: behavior is pinned via
     an injected `run` callable; the real argv assembly is pinned via a
     recording injection (the command never runs).
  2. TTL probe cache (runs/.capability-probe-cache.json) — a fresh cached
     fact never re-executes the probe (the dispatch gate must stay
     narrow+low-IO per #475 while still consulting facts AT the gate).
  3. FAMILY_REQUIRED matching — the dispatch prompt's method keywords map
     to the capability facts the family REQUIRES; probe FAIL refuses the
     dispatch with an alternative-arm suggestion (execution_surface
     class); SKIP/absent facts never fabricate a refusal.
  4. env_state_probe — `device_root` (and host_frida) join the android
     probe set; the declared-but-never-probed jdwp_debug seam (#421) is
     closed by wiring the #474 `_adb_jdwp_probe` primitive.
  5. exogenous vocabulary — LANE_REQUIRED android grows host_frida (the
     9x incident class); LANE_CONDITIONAL adds jdwp_debug / device_root /
     network_egress / remote words; classify_exogenous accepts the
     method-grain `extra` (additive, default ()).
  6. toolfirst negative cache (tools/_lib/negative_cache.py + the
     tool-search --find face) — identical negative queries are answered
     from the TTL cache within TTL (Standard 11: occurrences count PER
     FAMILY, the limit escalates); a workspace-less cwd keeps the cache
     silent (existing determinism pins unaffected).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"


def _ts_ago(minutes: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)) \
        .isoformat(timespec="seconds").replace("+00:00", "Z")


def _mk_ws(root: Path, *, ptype: str | None = "android") -> Path:
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    if ptype is not None:
        (ws / "analysis_state.txt").write_text(
            f"project_type={ptype}\n", encoding="utf-8")
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


def _recorder(argv_results: dict | None = None):
    """Injection pin: records argv, never executes; per-argv scripted
    results default to rc=0 / empty out."""
    calls: list[list[str]] = []

    def run(argv, timeout: int = 10):
        calls.append(list(argv))
        scripted = (argv_results or {}).get(tuple(argv), (0, "", ""))
        return (int(scripted[0]), str(scripted[1]), str(scripted[2]))

    run.calls = calls  # type: ignore[attr-defined]
    return run


# ===================================================== 1. probe primitives

class TestHostFridaProbe:
    def test_pass_on_version_success(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("frida", "--version"): (0, "16.5.9", "")})
        status, detail = cp.probe_host_frida(run=run)
        assert status == "pass"
        assert "16.5.9" in detail

    def test_fail_on_missing_binary_rc(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("frida", "--version"): (1, "", "ModuleNotFoundError")})
        status, detail = cp.probe_host_frida(run=run)
        assert status == "fail"
        assert "ModuleNotFoundError" in detail

    def test_real_command_assembly_pinned(self, tmp_path) -> None:
        """The injection pin records EXACTLY the canonical argv — the
        probe never executes it here, but the assembly is the contract
        the dep_surface/host story must match."""
        import capability_probe as cp
        run = _recorder()
        cp.probe_host_frida(run=run)
        assert run.calls == [["frida", "--version"]]

    def test_probe_crash_is_skip_never_fail(self, tmp_path) -> None:
        import capability_probe as cp

        def boom(argv, timeout: int = 10):
            raise OSError("exec unavailable")

        status, _ = cp.probe_host_frida(run=boom)
        assert status == "skip", (
            "a crashed probe is NO EVIDENCE of absence — the conservative "
            "rule (#421) forbids fabricating a fail from an exec outage")


class TestDeviceRootProbe:
    def test_root_pass_uid_zero(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("/usr/bin/adb", "shell", "su", "-c", "id"):
                         (0, "uid=0(root) gid=0(root)", "")})
        status, detail = cp.probe_device_root(run=run, adb="/usr/bin/adb")
        assert status == "pass"
        assert "uid=0" in detail

    def test_su_without_uid_zero_is_fail(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("/usr/bin/adb", "shell", "su", "-c", "id"):
                         (0, "uid=2000(shell)", "")})
        status, _detail = cp.probe_device_root(run=run, adb="/usr/bin/adb")
        assert status == "fail"

    def test_su_rc_failure_is_fail(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("/usr/bin/adb", "shell", "su", "-c", "id"):
                         (1, "", "su: not found")})
        status, _detail = cp.probe_device_root(run=run, adb="/usr/bin/adb")
        assert status == "fail"

    def test_no_adb_is_skip_never_fail(self, tmp_path) -> None:
        """THE incident pin: host adb absent must NEVER read as "device
        has no root" — the channel is absent, the fact is unverified."""
        import capability_probe as cp
        status, detail = cp.probe_device_root(run=_recorder(), adb=None)
        assert status == "skip"
        assert "adb" in detail.lower()

    def test_device_side_is_separate_fact_from_host(self, tmp_path) -> None:
        """Acceptance 1 verbatim: host-side and device-side recorded as
        SEPARATE capabilities — a host frida failure says nothing about
        the device root state and vice versa (distinct names)."""
        import capability_probe as cp
        assert cp.CAPABILITY_NAMES == ("host_frida", "device_root")
        host_status, _ = cp.probe_host_frida(
            run=_recorder({("frida", "--version"): (1, "", "ModuleNotFoundError")}))
        dev_status, _ = cp.probe_device_root(run=_recorder(), adb=None)
        assert (host_status, dev_status) == ("fail", "skip"), (
            "a host frida failure and an unverified device channel are "
            "SEPARATE facts — the misattribution shape is unrepresentable")

    def test_real_command_assembly_pinned(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder()
        cp.probe_device_root(run=run, adb="/usr/bin/adb")
        assert run.calls == [["/usr/bin/adb", "shell", "su", "-c", "id"]]


# ===================================================== 2. TTL facts cache

class TestFactsCache:
    def test_unknown_capability_is_skip(self, tmp_path) -> None:
        import capability_probe as cp
        facts = cp.facts(tmp_path, ("no_such_cap",), run=_recorder())
        assert facts["no_such_cap"]["status"] == "skip"

    def test_stale_cache_probes_once_then_reuses(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("frida", "--version"): (0, "16.5.9", "")})
        # seed a STALE entry (older than any sane TTL)
        cache = tmp_path / "runs" / ".capability-probe-cache.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"host_frida": {
            "status": "fail", "detail": "old", "ts": _ts_ago(9999)}}),
            encoding="utf-8")
        first = cp.facts(tmp_path, ("host_frida",), run=run)
        assert first["host_frida"]["status"] == "pass"
        assert len(run.calls) == 1, "stale entry must re-probe exactly once"
        second = cp.facts(tmp_path, ("host_frida",), run=run)
        assert second["host_frida"]["status"] == "pass"
        assert len(run.calls) == 1, "fresh cached fact must NEVER re-probe"

    def test_negative_result_is_cached_within_ttl(self, tmp_path) -> None:
        """A probe FAIL is a fact too — within TTL the dead-lane dispatch
        refusal must not re-execute the probe (bounded probing)."""
        import capability_probe as cp
        run = _recorder({("frida", "--version"): (1, "", "gone")})
        cp.facts(tmp_path, ("host_frida",), run=run)
        assert len(run.calls) == 1
        again = cp.facts(tmp_path, ("host_frida",), run=run)
        assert again["host_frida"]["status"] == "fail"
        assert len(run.calls) == 1, "cached negative must not re-execute"

    def test_fresh_env_state_snapshot_wins(self, tmp_path) -> None:
        """env-state.json is the single source of truth writer (#475) —
        a FRESH snapshot entry is consulted without any probe execution."""
        import capability_probe as cp
        run = _recorder()
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / "env-state.json").write_text(json.dumps({
            "per_capability": {"host_frida": {
                "status": "pass", "detail": "snapshot", "last_probe_ts":
                _ts_ago(1)}},
            "written_by": "env_state_probe", "ts": _ts_ago(1)}),
            encoding="utf-8")
        facts = cp.facts(tmp_path, ("host_frida",), run=run, ttl=600)
        assert facts["host_frida"]["status"] == "pass"
        assert len(run.calls) == 0, "fresh snapshot must not re-probe"

    def test_stale_snapshot_falls_through_to_probe(self, tmp_path) -> None:
        import capability_probe as cp
        run = _recorder({("frida", "--version"): (0, "16.5.9", "")})
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / "env-state.json").write_text(json.dumps({
            "per_capability": {"host_frida": {
                "status": "fail", "detail": "stale", "last_probe_ts":
                _ts_ago(9999)}},
            "written_by": "env_state_probe", "ts": _ts_ago(9999)}),
            encoding="utf-8")
        facts = cp.facts(tmp_path, ("host_frida",), run=run, ttl=600)
        assert facts["host_frida"]["status"] == "pass"
        assert len(run.calls) == 1


# ============================================ 3. family matching vocabulary

class TestFamilyMatching:
    def test_android_dynamic_trace_requires_host_frida(self) -> None:
        import capability_probe as cp
        matched = cp.match_required(
            "dispatch dynamic-trace: frida stalker hook the JNI table",
            "android")
        assert ("android-dynamic-trace", ("host_frida",)) in matched

    def test_android_root_family_requires_device_root(self) -> None:
        import capability_probe as cp
        matched = cp.match_required(
            "dump memory via /proc/<pid>/mem needs root su", "android")
        assert ("android-root-instrument", ("device_root",)) in matched

    def test_android_jdwp_family_requires_jdwp_debug(self) -> None:
        import capability_probe as cp
        matched = cp.match_required(
            "attach jdb over jdwp to the debuggable pid", "android")
        assert ("android-jdwp", ("jdwp_debug",)) in matched

    def test_non_android_lane_never_matches(self) -> None:
        import capability_probe as cp
        assert cp.match_required("frida hook the target", "web") == []
        assert cp.match_required("frida hook the target", None) == []

    def test_alternative_arm_carried_per_family(self) -> None:
        """Acceptance 1: a refused family gets a CONCRETE alternative —
        the offline-recompute lane already proven by the PoW bet."""
        import capability_probe as cp
        alts = cp.alternative_for("android-dynamic-trace")
        assert alts and "offline" in alts.lower()


# ================================== 4. env_state_probe android probe set

class TestEnvStateAndroidSet:
    def test_android_caps_declare_device_root_and_host_frida(self) -> None:
        import env_state_probe as esp
        assert "device_root" in esp.ANDROID_CAPS
        assert "host_frida" in esp.ANDROID_CAPS
        assert "jdwp_debug" in esp.ANDROID_CAPS

    def test_android_probe_emits_all_five(self, tmp_path, monkeypatch) -> None:
        import env_state_probe as esp
        (tmp_path / "analysis_state.txt").write_text(
            "project_type=android\n", encoding="utf-8")
        monkeypatch.setattr(esp, "_probe_adb",
                            lambda: esp._entry("pass", "1 attached"))
        monkeypatch.setattr(esp, "_probe_frida_server",
                            lambda: esp._entry("pass", "forwarded"))
        monkeypatch.setattr(esp, "_probe_jdwp_debug",
                            lambda: esp._entry("pass", "handshake"))
        monkeypatch.setattr(esp, "_probe_device_root",
                            lambda: esp._entry("pass", "uid=0"))
        monkeypatch.setattr(esp, "_probe_host_frida",
                            lambda: esp._entry("pass", "16.5.9"))
        state = esp.probe(tmp_path)
        caps = state["per_capability"]
        for name in ("adb", "frida_server", "jdwp_debug", "device_root",
                     "host_frida"):
            assert name in caps, f"{name} missing from the android snapshot"

    def test_no_adb_skips_device_root_never_fails_it(
            self, tmp_path, monkeypatch) -> None:
        import env_state_probe as esp
        (tmp_path / "analysis_state.txt").write_text(
            "project_type=android\n", encoding="utf-8")
        monkeypatch.setattr(esp, "_adb_path", lambda: None)
        monkeypatch.setattr(esp, "_probe_host_frida",
                            lambda: esp._entry("pass", "16.5.9"))
        state = esp.probe(tmp_path)
        assert state["per_capability"]["device_root"]["status"] == "skip"

    def test_jdwp_uses_toolchain_primitive(self) -> None:
        """The #474 probe primitives are the single source — the jdwp
        wiring must reuse tc._adb_jdwp_probe, not reimplement."""
        import env_state_probe as esp
        import inspect
        src = inspect.getsource(esp)
        assert "_adb_jdwp_probe" in src


# ==================================== 5. exogenous vocabulary extension

class TestExogenousVocabulary:
    def test_android_lane_required_grows_host_frida(self) -> None:
        import exogenous as ex
        assert "host_frida" in ex.LANE_REQUIRED["android"]

    def test_lane_conditional_words_registered(self) -> None:
        import exogenous as ex
        assert "jdwp_debug" in ex.LANE_CONDITIONAL["android"]
        assert "device_root" in ex.LANE_CONDITIONAL["android"]
        assert "network_egress" in ex.LANE_CONDITIONAL["web"]
        assert "network_egress" in ex.LANE_CONDITIONAL["remote"]

    def test_conditional_word_down_classifies_with_extra(self, tmp_path) -> None:
        import exogenous as ex
        now = datetime.now(tz=timezone.utc)
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / "env-state.json").write_text(json.dumps({
            "per_capability": {"jdwp_debug": {
                "status": "fail", "detail": "no handshake",
                "last_probe_ts": _ts_ago(1)}},
            "ts": _ts_ago(1)}), encoding="utf-8")
        base = ex.classify_exogenous(tmp_path, "android", now=now)
        assert base is None, "jdwp down must NOT classify base android work"
        extra = ex.classify_exogenous(tmp_path, "android", now=now,
                                      extra=ex.LANE_CONDITIONAL["android"])
        assert extra is not None and extra["component"] == "jdwp_debug"

    def test_extra_additive_default_keeps_callers(self, tmp_path) -> None:
        import inspect
        import exogenous as ex
        sig = inspect.signature(ex.classify_exogenous)
        assert sig.parameters["extra"].default == ()
        assert ex.classify_exogenous(tmp_path, "android") is None

    def test_unprobed_conditional_word_never_classifies(self, tmp_path) -> None:
        import exogenous as ex
        now = datetime.now(tz=timezone.utc)
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / "env-state.json").write_text(json.dumps({
            "per_capability": {}, "ts": _ts_ago(1)}), encoding="utf-8")
        got = ex.classify_exogenous(tmp_path, "web", now=now,
                                    extra=ex.LANE_CONDITIONAL["web"])
        assert got is None, ("vocabulary without a probe producer is inert "
                             "(conservative rule: unprobed != down)")


# ================================ 6. dispatch-gate capability-probe face

def _dispatch_prompt(method: str) -> dict:
    return {"tool_input": {"prompt": json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1,
        "tools": ["Read", "Write"], "agent": "kunglao-worker"}})
        + f"\n{method} the target"}}


class TestDispatchProbeGate:
    def _gate(self, tmp_path, prompt: dict):
        import dispatch_gate as dg
        return dg._capability_probe_gate(
            tmp_path, "C-1", prompt["tool_input"]["prompt"])

    def test_failed_required_capability_rejects(self, tmp_path, monkeypatch) -> None:
        import capability_probe as cp
        ws = _mk_ws(tmp_path)
        monkeypatch.setattr(cp, "facts",
                            lambda ws_, req, **kw: {
                                "host_frida": {"status": "fail",
                                               "detail": "ModuleNotFoundError",
                                               "ts": _ts_ago(0)}})
        rc = self._gate(ws, _dispatch_prompt(
            "dynamic-trace with frida stalker hooks"))
        assert rc == 2, "a failed family capability must refuse dispatch"

    def test_reject_names_separate_facts_and_alternative(
            self, tmp_path, monkeypatch, capsys) -> None:
        """The misattribution fix verbatim: the refusal names WHICH face
        failed (host) and does NOT claim the device is unrooted, plus the
        alternative-arm suggestion."""
        import capability_probe as cp
        ws = _mk_ws(tmp_path)
        monkeypatch.setattr(cp, "facts",
                            lambda ws_, req, **kw: {
                                "host_frida": {"status": "fail",
                                               "detail": "gone", "ts":
                                               _ts_ago(0)}})
        self._gate(ws, _dispatch_prompt("frida stalker trace"))
        captured = capsys.readouterr()
        err, out = captured.err, captured.out
        assert "host_frida" in err
        first_line = err.splitlines()[0] if err else ""
        assert "device_root" not in first_line, (
            "the refusal's summary line names the FAILED face only — no "
            "device verdict rides host evidence (the misattribution pin)")
        assert "offline" in out.lower(), (
            "the fix path must carry the alternative-arm pivot")

    def test_skip_fact_never_rejects(self, tmp_path, monkeypatch) -> None:
        """Channel-absent facts are NOT evidence — the gate proceeds (the
        incident's anti-pattern is refusing on a skip)."""
        import capability_probe as cp
        ws = _mk_ws(tmp_path)
        monkeypatch.setattr(cp, "facts",
                            lambda ws_, req, **kw: {
                                "host_frida": {"status": "skip",
                                               "detail": "channel absent",
                                               "ts": _ts_ago(0)}})
        assert self._gate(ws, _dispatch_prompt("frida stalker trace")) is None

    def test_non_android_workspace_silent(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path, ptype="web")
        assert self._gate(ws, _dispatch_prompt("frida stalker trace")) is None

    def test_unmatched_prompt_silent(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        assert self._gate(ws, _dispatch_prompt("static jadx decompile")) is None

    def test_verifier_remediation_passes(self, tmp_path, monkeypatch) -> None:
        import dispatch_gate as dg
        ws = _mk_ws(tmp_path)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-1\n    status: PROVEN\n", encoding="utf-8")
        payload = {"tool_input": {"prompt": json.dumps({"kunglao_dispatch": {
            "version": 1, "claim": "C-1", "tier": 1,
            "tools": ["Read"], "agent": "kunglao-redteam"}})
            + "\nfrida trace verify"}}
        rc = dg._capability_probe_gate(ws, "C-1", payload["tool_input"]["prompt"])
        assert rc is None, "the D2 honest path is never capability-blocked"

    def test_unreadable_cache_fails_open(self, tmp_path, monkeypatch) -> None:
        import capability_probe as cp
        ws = _mk_ws(tmp_path)
        def boom(*a, **kw):
            raise OSError("cache unreadable")
        monkeypatch.setattr(cp, "facts", boom)
        assert self._gate(ws, _dispatch_prompt("frida stalker trace")) is None

    def test_reject_emits_registered_action(self, tmp_path, monkeypatch) -> None:
        import capability_probe as cp
        ws = _mk_ws(tmp_path)
        monkeypatch.setattr(cp, "facts",
                            lambda ws_, req, **kw: {
                                "host_frida": {"status": "fail",
                                               "detail": "gone",
                                               "ts": _ts_ago(0)}})
        self._gate(ws, _dispatch_prompt("frida stalker trace"))
        rows = []
        logs = ws / "runs" / "logs"
        if logs.is_dir():
            for p in sorted(logs.glob("kunglao-*.jsonl")):
                rows.extend(json.loads(ln) for ln in
                            p.read_text(encoding="utf-8",
                                        errors="replace").splitlines() if ln)
        assert any(e.get("action") == "capability_probe_reject" for e in rows)


def test_emit_actions_registered() -> None:
    import event_taxonomy as et
    assert "capability_probe_reject" in et.EMIT_ACTIONS
    assert "capability_probe_unverified" in et.EMIT_ACTIONS


# ================================== 7. toolfirst negative cache (Standard 11)

def _seed_ws(root: Path) -> Path:
    ws = root / "wsws"
    (ws / "runs").mkdir(parents=True)
    return ws


class TestNegativeCache:
    def test_family_normalization_sorted_unique(self) -> None:
        from negative_cache import normalize_family
        assert normalize_family(["jadx", "apk", "jadx"]) == "apk|jadx"
        assert normalize_family(["TLS", "mitm"]) == "mitm|tls"

    def test_record_counts_per_family(self, tmp_path) -> None:
        from negative_cache import record_negative
        ws = _seed_ws(tmp_path)
        r1 = record_negative(ws, "jadx|apk", "static-decompile/android-apk")
        r2 = record_negative(ws, "jadx|apk", "static-decompile/android-apk")
        assert (r1["occurrence"], r2["occurrence"]) == (1, 2)

    def test_lookup_fresh_within_ttl(self, tmp_path) -> None:
        from negative_cache import record_negative, lookup
        ws = _seed_ws(tmp_path)
        record_negative(ws, "mitm|tls", "mitm/capture/tls")
        row = lookup(ws, "mitm|tls")
        assert row is not None and row["occurrence"] == 1

    def test_lookup_expired_returns_none(self, tmp_path) -> None:
        from negative_cache import lookup, store_negative_state
        ws = _seed_ws(tmp_path)
        store_negative_state(ws, {"families": {"mitm|tls": {
            "occurrence": 5, "first_ts": _ts_ago(999), "last_ts": _ts_ago(999),
            "escalated": True}}})
        assert lookup(ws, "mitm|tls", ttl=1800) is None

    def test_standard11_escalation_at_limit(self, tmp_path) -> None:
        from negative_cache import (NEGATIVE_REPEAT_LIMIT, record_negative)
        ws = _seed_ws(tmp_path)
        row = None
        for _ in range(NEGATIVE_REPEAT_LIMIT):
            row = record_negative(ws, "jadx|apk", "static-decompile")
        assert row["escalated"] is True, (
            "the occurrence AT the limit escalates (dead-lane verdict)")

    def test_corrupt_store_degrades_silent(self, tmp_path) -> None:
        from negative_cache import lookup
        ws = _seed_ws(tmp_path)
        (ws / "runs" / ".toolsearch-negative-cache.json").write_text(
            "{not json", encoding="utf-8")
        assert lookup(ws, "anything") is None
        fresh = tmp_path / "fresh-ws"
        (fresh / "runs").mkdir(parents=True)
        assert lookup(fresh, "never-seen") is None


class TestToolSearchNegativeFace:
    def _run(self, *args: str, cwd: Path | None = None):
        return subprocess.run(
            [sys.executable, str(TOOLS / "tool-search.py"), *args],
            capture_output=True, text=True, timeout=60, cwd=str(cwd or REPO_ROOT),
            errors="replace")

    def test_negative_query_recorded_then_cached(self, tmp_path) -> None:
        ws = _seed_ws(tmp_path)
        args = ("--find", "zzqq-no-such-tool-xyz", "--ws", str(ws), "--json")
        r1 = self._run(*args)
        assert r1.returncode == 0
        doc1 = json.loads(r1.stdout or '{"count": 0, "tools": []}')
        assert doc1["count"] == 0
        assert "negative_cache" not in doc1, "first miss records, not hits"
        r2 = self._run(*args)
        doc2 = json.loads(r2.stdout)
        assert doc2["count"] == 0
        nc = doc2["negative_cache"]
        assert nc["occurrence"] >= 1, "identical negative answered from cache"
        assert nc["family"] == "zzqq-no-such-tool-xyz"

    def test_cached_answer_is_fast_no_rescan(self, tmp_path) -> None:
        """Within TTL the cache answers WITHOUT the four-source scan —
        pin via the marker only (the scan is not observable here, but the
        second response must carry cached_at/ttl metadata proving the
        cache served it)."""
        ws = _seed_ws(tmp_path)
        args = ("--find", "zzqq-dead-lane", "--ws", str(ws), "--json")
        self._run(*args)
        r2 = self._run(*args)
        nc = json.loads(r2.stdout)["negative_cache"]
        assert "cached_at" in nc and "ttl_remaining" in nc

    def test_positive_query_never_caches(self, tmp_path) -> None:
        ws = _seed_ws(tmp_path)
        self._run("--find", "ghidra", "--ws", str(ws), "--json")
        store = ws / "runs" / ".toolsearch-negative-cache.json"
        assert not store.exists() or json.loads(store.read_text()) == \
            {"families": {}}

    def test_no_workspace_cache_silent(self, tmp_path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        r = self._run("--find", "zzqq-no-such-tool", "--json", cwd=bare)
        assert r.returncode == 0
        doc = json.loads(r.stdout) if r.stdout.strip() else {"count": 0}
        assert "negative_cache" not in doc
