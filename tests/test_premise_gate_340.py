# -*- coding: utf-8 -*-
"""Issue #340 scope B+C — premise-probe reconciliation gate + premise expiry.

B (reconciliation, the main blade): a dispatch needing capability X
(`_env_caps_needed` vocabulary — single source) is reconciled against
blockers/*.md env premises and runs/env-state.json. Premise claims X
unavailable + env-state shows X PASS → premise marked SUSPECT (append-only),
one-shot capability re-probe scheduled (#474 on-demand channel), event
`env_premise_contradiction` emitted — and the dispatch is NOT blocked.

C (expiry): a v2 env-class blocker whose probe evidence has not refreshed
within `expires` ticks is marked INVALIDATED(stale) by the tick-hosted
mechanism (append-only history line); convergence_check._active_blockers
then excludes it; file history is preserved.

Real synthetic workspaces on disk (tmp_path) throughout — no gate-mocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import premise_gate  # noqa: E402
from convergence_check import _active_blockers  # noqa: E402

ENV_STATE = Path("runs") / "env-state.json"
NOW = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "blockers").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n  evidence_tier_attempted: 1\n",
        encoding="utf-8")
    return ws


def _write_blocker(ws: Path, stem: str = "C-1", *, claim_id: str = "C-1",
                   attributed: str = "device has no root, frida unusable",
                   probe_evidence: str = "su -c id -> su: not found (rc 1)",
                   expires: str = "12") -> Path:
    p = ws / "blockers" / f"{stem}.md"
    p.write_text(
        "---\n"
        f"claim_id: {claim_id}\n"
        "blocker_type: B1b\n"
        'reason: "spawn fails with permission-flavored stderr"\n'
        "created: 2026-09-22\n"
        'observed: "adb shell su -c id -> su: not found"\n'
        f'attributed: "{attributed}"\n'
        f'probe_evidence: "{probe_evidence}"\n'
        f"expires: {expires}\n"
        "---\n"
        "\n# Blocker\n\n- missing: frida spawn\n",
        encoding="utf-8")
    return p


def _write_env_state(ws: Path, per_capability: dict,
                     age_min: float = 0.0) -> None:
    ts = _iso(NOW - timedelta(minutes=age_min))
    (ws / ENV_STATE).write_text(json.dumps({
        "per_capability": {k: {**v, "last_probe_ts": v.get("last_probe_ts", ts)}
                           for k, v in per_capability.items()},
        "written_by": "env_state_probe", "ts": ts,
    }, indent=2), encoding="utf-8")


def _paths(ws: Path) -> dict:
    """Mirror of test_env_drift_475's paths dict (pre_check needs the
    register/state keys even though this seam check only reads workspace)."""
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


# =====================================================================
# B: premise-probe reconciliation
# =====================================================================

class TestPremiseReconciliation:
    def test_contradiction_suspect_reprobe_event_and_not_blocked(
            self, tmp_path, capsys):
        """The issue's exact regression: env-state PASS vs blocker premise
        claiming the capability unavailable. The dispatch is NOT blocked on
        the premise; the premise is marked SUSPECT, a re-probe is scheduled
        and env_premise_contradiction is emitted."""
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        _write_env_state(ws, {"vm_reachable": {"status": "pass",
                                               "detail": "VM reachable"}})
        ok, msg = check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert ok is True, "the dispatch must NOT be blocked on the stale premise"
        text = blocker.read_text(encoding="utf-8")
        assert "[SUSPECT]" in text and "vm_reachable" in text
        pending = ws / "runs" / ".env-reprobe-pending.json"
        assert pending.exists(), "one-shot capability re-probe must be scheduled"
        data = json.loads(pending.read_text(encoding="utf-8"))
        assert "vm_reachable" in (data.get("caps") or [])
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "event ledger row expected"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert any(r.get("action") == "env_premise_contradiction" for r in rows)

    def test_premise_contradiction_word_registered(self):
        from event_taxonomy import EMIT_ACTIONS
        assert "env_premise_contradiction" in EMIT_ACTIONS

    def test_suspect_marker_is_append_only(self, tmp_path):
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        _write_env_state(ws, {"vm_reachable": {"status": "pass",
                                               "detail": "ok"}})
        before = blocker.read_bytes()
        check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        after = blocker.read_bytes()
        assert after.startswith(before), "history append-only: old bytes are a prefix"

    def test_suspect_deduped_per_probe_ts(self, tmp_path):
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        _write_env_state(ws, {"vm_reachable": {"status": "pass",
                                               "detail": "ok"}})
        for _ in range(2):
            check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        text = blocker.read_text(encoding="utf-8")
        assert text.count("[SUSPECT]") == 1
        # a FRESH probe ts is new evidence → a new marker is honest
        _write_env_state(ws, {"vm_reachable": {"status": "pass", "detail": "ok",
                                               "last_probe_ts": _iso(
                                                   NOW + timedelta(minutes=5))}})
        check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert blocker.read_text(encoding="utf-8").count("[SUSPECT]") == 2

    def test_missing_env_state_fail_open_unchanged(self, tmp_path):
        """Regression pin: missing env-state.json keeps the current
        fail-open behavior — no marker, no pending file, no event."""
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        ok, _msg = check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert ok is True
        assert "[SUSPECT]" not in blocker.read_text(encoding="utf-8")
        assert not (ws / "runs" / ".env-reprobe-pending.json").exists()
        assert not (ws / "runs" / "logs").exists()

    def test_no_contradiction_when_env_state_fail(self, tmp_path):
        """FAIL agrees with the premise — reconciliation stays silent
        (check_env_fresh's existing reject path owns that face)."""
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        _write_env_state(ws, {"vm_reachable": {"status": "fail",
                                               "detail": "VM unreachable"}})
        check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert "[SUSPECT]" not in blocker.read_text(encoding="utf-8")

    def test_no_contradiction_when_premise_absent_or_resolved(self, tmp_path):
        from worker_budget import check_env_premise
        ws = _mk_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "pass",
                                               "detail": "ok"}})
        # no blockers at all
        check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert not (ws / "runs" / ".env-reprobe-pending.json").exists()
        # resolved (INVALIDATED) blocker is not an active premise
        blocker = _write_blocker(ws)
        blocker.write_text(
            blocker.read_text(encoding="utf-8")
            + "\n- INVALIDATED 2026-09-22: manually resolved\n",
            encoding="utf-8")
        check_env_premise(_paths(ws), tier=2, tools=["vmr-shell"])
        assert not (ws / "runs" / ".env-reprobe-pending.json").exists()

    def test_full_pre_check_allows_on_contradiction(self, tmp_path, capsys):
        """End-to-end at the dispatch-vetting seam: pre_check must not
        reject this dispatch ('REJECT envpremise' never appears)."""
        from worker_budget import pre_check
        ws = _mk_ws(tmp_path)
        (ws / "facts").mkdir()
        _write_blocker(ws)
        _write_env_state(ws, {"vm_reachable": {"status": "pass",
                                               "detail": "ok"}})
        payload = {"tool_input": {
            "name": "w-t", "description": "dynamic detonation",
            "prompt": "[T2 tools=vmr-shell] claim C-001 detonate "
                      "facts-snapshot: 0 facts at 2026-09-22T00:00Z"}}
        rc = pre_check(payload, _paths(ws))
        captured = capsys.readouterr()
        assert "envpremise" not in captured.err
        assert rc == 0, captured.err


# =====================================================================
# B: one-shot re-probe consumer (the #474 on-demand channel)
# =====================================================================

class TestReprobeConsumer:
    def _pending(self, ws: Path) -> None:
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        (ws / "runs" / ".env-reprobe-pending.json").write_text(json.dumps({
            "caps": ["vm_reachable"], "reason": "env_premise_contradiction",
            "blockers": ["C-1"], "ts": _iso(NOW), "attempts": 0,
        }), encoding="utf-8")

    def test_reprobe_via_existing_toolchain_channel(self, tmp_path):
        """The consumer must route through scripts/toolchain.py --capability
        (the #474 on-demand channel) — never a reinvented probe."""
        ws = _mk_ws(tmp_path)
        (ws / "analysis_state.txt").write_text(
            "project_type=windows\n", encoding="utf-8")
        blocker = _write_blocker(ws)
        self._pending(ws)
        calls = []

        def fake_runner(argv, timeout):
            calls.append((argv, timeout))
            return 0, json.dumps({"items": [], "overall_status": "PASS"}), ""

        out = premise_gate.run_pending_reprobe(ws, runner=fake_runner)
        assert out.get("ran") is True
        assert calls, "toolchain --capability must be invoked"
        argv, _t = calls[0]
        assert "toolchain.py" in " ".join(str(a) for a in argv)
        assert "--capability" in [str(a) for a in argv]
        assert not (ws / "runs" / ".env-reprobe-pending.json").exists(), \
            "one-shot: pending consumed"
        text = blocker.read_text(encoding="utf-8")
        assert "re-probe" in text and "PASS" in text

    def test_reprobe_failure_increments_attempts_then_consumes(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "analysis_state.txt").write_text(
            "project_type=windows\n", encoding="utf-8")
        blocker = _write_blocker(ws)
        self._pending(ws)

        def failing(argv, timeout):
            return 1, "", "boom"

        premise_gate.run_pending_reprobe(ws, runner=failing)
        pending = json.loads(
            (ws / "runs" / ".env-reprobe-pending.json").read_text("utf-8"))
        assert pending["attempts"] == 1, "one failure keeps the one-shot pending"
        premise_gate.run_pending_reprobe(ws, runner=failing)
        premise_gate.run_pending_reprobe(ws, runner=failing)
        assert not (ws / "runs" / ".env-reprobe-pending.json").exists(), \
            "3 failed attempts consume the one-shot with an honest failure note"
        assert "re-probe" in blocker.read_text(encoding="utf-8")

    def test_no_pending_is_noop(self, tmp_path):
        ws = _mk_ws(tmp_path)
        out = premise_gate.run_pending_reprobe(ws, runner=lambda a, t: (0, "", ""))
        assert out.get("ran") is False


# =====================================================================
# C: premise expiry
# =====================================================================

class TestPremiseExpiry:
    def test_stale_blocker_invalidated_after_n_ticks(self, tmp_path):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws, expires="2")
        ws_arg = Path(ws)
        premise_gate.expire_stale(ws_arg)   # tick 1: fresh, stays active
        assert _active_blockers(ws_arg) == ["C-1"]
        premise_gate.expire_stale(ws_arg)   # tick 2: age 1 < 2
        assert _active_blockers(ws_arg) == ["C-1"]
        premise_gate.expire_stale(ws_arg)   # tick 3: age 2 >= 2 → stale
        text = blocker.read_text(encoding="utf-8")
        assert "INVALIDATED(stale)" in text
        assert _active_blockers(ws_arg) == [], "convergence must exclude it"

    def test_invalidation_is_append_only(self, tmp_path):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws, expires="1")
        before = blocker.read_bytes()
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        after = blocker.read_bytes()
        assert after.startswith(before), "history preserved byte-prefix"
        assert before in after

    def test_invalidation_idempotent_within_and_across_ticks(self, tmp_path):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws, expires="1")
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        first = blocker.read_text(encoding="utf-8")
        premise_gate.expire_stale(Path(ws))
        assert blocker.read_text(encoding="utf-8") == first, \
            "already-invalidated files are not re-appended"

    def test_fresh_probe_evidence_resets_clock(self, tmp_path):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws, expires="2")
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        # re-verification: fresh probe evidence lands (a rewrite is a new
        # premise with new evidence — the clock restarts)
        blocker.write_text(
            blocker.read_text(encoding="utf-8").replace(
                "probe_evidence: \"su -c id -> su: not found (rc 1)\"",
                "probe_evidence: \"re-probe: id -> uid=2000 shell\""),
            encoding="utf-8")
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        text = blocker.read_text(encoding="utf-8")
        assert "INVALIDATED(stale)" not in text
        assert _active_blockers(Path(ws)) == ["C-1"]

    def test_iso_expires_in_past_invalidates(self, tmp_path):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws, expires='"2026-09-01T00:00:00Z"')
        premise_gate.expire_stale(Path(ws))
        assert "INVALIDATED(stale)" in blocker.read_text(encoding="utf-8")

    def test_iso_expires_in_future_stays(self, tmp_path):
        ws = _mk_ws(tmp_path)
        future = _iso(NOW + timedelta(days=1))
        blocker = _write_blocker(ws, expires=f'"{future}"')
        premise_gate.expire_stale(Path(ws))
        assert "INVALIDATED(stale)" not in blocker.read_text(encoding="utf-8")

    def test_default_expiry_ticks_is_12(self):
        assert premise_gate.DEFAULT_EXPIRY_TICKS == 12

    def test_missing_expires_uses_configurable_default(self, tmp_path,
                                                       monkeypatch):
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(ws)
        text = blocker.read_text(encoding="utf-8").replace("expires: 12\n", "")
        blocker.write_text(text, encoding="utf-8")
        monkeypatch.setenv("KUNGLAO_PREMISE_EXPIRY_TICKS", "1")
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        assert "INVALIDATED(stale)" in blocker.read_text(encoding="utf-8")

    def test_non_env_blockers_never_auto_expire(self, tmp_path):
        """A B2 user-stop blocker carries no env attribution — it is not an
        env-class premise and must not be invalidated by the sweep."""
        ws = _mk_ws(tmp_path)
        blocker = _write_blocker(
            ws, stem="C-2", claim_id="C-2",
            attributed="user stopped the session at 14:03",
            probe_evidence="stop hook signal bytes: [Stop] user",
            expires="1")
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        premise_gate.expire_stale(Path(ws))
        text = blocker.read_text(encoding="utf-8")
        assert "INVALIDATED(stale)" not in text
        assert _active_blockers(Path(ws)) == ["C-2"]

    def test_legacy_shape_blocker_skipped_by_sweep(self, tmp_path):
        """No-compat ruling: legacy files are not migrated by the sweep —
        the write gate rejects them on touch; expiry ignores them."""
        ws = _mk_ws(tmp_path)
        blocker = ws / "blockers" / "C-9.md"
        blocker.write_text(
            "---\nclaim_id: C-9\nblocker_type: B1a\n---\n\nlegacy body\n",
            encoding="utf-8")
        for _ in range(5):
            premise_gate.expire_stale(Path(ws))
        assert "INVALIDATED" not in blocker.read_text(encoding="utf-8")

    def test_registry_declares_premise_expiry_mechanism(self):
        """Scope C lives in the #878 registry — trigger/cost_class/
        cockpit_signal all three, or the registry rejects."""
        import mechanism_scheduler as ms
        res = ms.validate_registry()
        assert res["ok"], res["errors"]
        entries, _ = ms.load_registry()
        me = [e for e in entries if e["name"] == "premise_expiry"]
        assert me, "premise_expiry mechanism must be declared"
        e = me[0]
        assert e["channel"] == "tick"
        assert e["trigger"]["type"] == "tick"
        assert e["trigger"]["gate"] in ms.GATES
        assert e["cost_class"] in ms.COST_CLASSES
        assert e["cockpit_signal"].strip()
        assert e["entry"] == "scripts/premise_gate.py"

    def test_cli_entry_runs_and_writes_state(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _write_blocker(ws)
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "premise_gate.py"), str(ws)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        state = ws / "runs" / ".premise-expiry.json"
        assert state.exists()
        data = json.loads(state.read_text(encoding="utf-8"))
        assert data["tick"] == 1
