# -*- coding: utf-8 -*-
"""SPINNING carries the prescribed remedy and is entered by flatline only.

Contract pinned here:

  S1  fact growth with a flat open count is information only: the verdict
      JSON keeps the `churn` field, but only a flatline of
      SPINNING_FLATLINE rounds over open work yields SPINNING
  S2  SPINNING carries the same `remedy` block as STALLED; its action text
      names the remedy marker and keeps the reformulate / decompose / DEFER
      guidance and the re-dispatch warning; the remedy names the detector's
      stuck set only
  S3  stalled_state() returns the state for both verdicts and says which
  S4  the gate admits the prescribed remedy dispatch at the rc=2 SPINNING
      face exactly as at the rc=1 STALLED face (same predicate, channels,
      depth cap, admit telemetry row) and rejects every other dispatch;
      with open claims but no stuck claim nothing is admissible at either
      face; admit rows naming the stuck claim close the follow-through
      channel at both faces
  S5  the user-facing guidance names the remedy path

Fast unit face: the health check's out-of-process run is stubbed at the
_run_py boundary, but the detector state is the REAL
scripts/convergence_health.stalled_state against a REAL ledger and the
predicate is the REAL hooks/lib_kunglao function.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convergence_health as ch  # noqa: E402
import worker_budget_core as wbc  # noqa: E402
import worker_budget_sinks as wbs  # noqa: E402
from _path_hygiene import load_hooks_lib  # noqa: E402

LIB = load_hooks_lib()
MARKER = LIB.STALLED_REMEDY_MARKER

BASE = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _snap(i: int, open_count: int, open_ids: list[str],
          dispatched_ids: list[str] | None = None,
          facts_total: int = 5) -> dict:
    """One ledger snapshot row (new format), 60s apart — never dedup'd."""
    return {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": facts_total,
        "dispatched_ids": dispatched_ids if dispatched_ids is not None else [],
    }


def _spinning_ledger(n: int = ch.SPINNING_FLATLINE) -> list[dict]:
    """C-1 dispatched-flat for n rounds: flatline n over one open claim."""
    return [_snap(i, 1, ["C-1"], ["C-1"]) for i in range(n)]


def _rotating_ledger(n: int) -> list[dict]:
    """Two open claims held flat for n rounds while the frontier rotates
    (C-1/C-2, then C-3/C-4, ...): no claim stays open three consecutive
    snapshots, so the detector's stuck set is empty. The last snapshot
    (n odd) leaves C-1 and C-2 open."""
    return [_snap(i, 2, ["C-1", "C-2"] if i % 2 == 0 else ["C-3", "C-4"], [])
            for i in range(n)]


def _fact_growth_ledger(n: int) -> list[dict]:
    """Three open claims held flat for n rounds while facts grow by 2 per
    round; none dispatched, so no claim counts as stuck."""
    return [_snap(i, 3, ["C-1", "C-2", "C-3"], [], facts_total=10 + 2 * i)
            for i in range(n)]


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    (ws / ch.LEDGER_NAME).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


def _ledger_with_admits(rows: list[dict], n_admits: int) -> list[dict]:
    """rows + n admit-telemetry rows for C-1 (the gate writes one such row
    per admitted remedy dispatch of the stuck claim)."""
    out = list(rows)
    for _ in range(n_admits):
        out.append({"type": "operator_action",
                    "action": ch.REMEDY_ADMIT_ACTION,
                    "actor": "hook:worker_budget",
                    "claim_id": "C-1", "ts": BASE.isoformat(),
                    "reason": "telemetry"})
    return out


# =====================================================================
# S1: fact growth alone never yields SPINNING
# =====================================================================

class TestFactGrowthIsInformationOnly:
    @pytest.mark.parametrize("rounds,expected", [
        (4, "HEALTHY"),   # flatline 4: below STALLED_FLATLINE
        (7, "STALLED"),   # flatline 7: below SPINNING_FLATLINE
    ])
    def test_fact_growth_with_flat_open_count_is_not_spinning(
            self, rounds, expected):
        r = ch.assess(_fact_growth_ledger(rounds))
        assert r["churn"]["is_churning"] is True, r["churn"]
        assert r["churn"]["facts_delta"] >= ch.SPINNING_CHURN_FACTS
        assert r["flatline_run"] < ch.SPINNING_FLATLINE
        assert r["verdict"] == expected
        assert r["exit_code"] != ch.EXIT_SPINNING

    def test_churn_field_stays_in_the_verdict_json(self):
        r = ch.assess(_fact_growth_ledger(4))
        assert set(r["churn"]) == {"facts_delta", "open_delta", "is_churning"}

    def test_spinning_threshold_is_the_flatline(self):
        below = ch.assess(_spinning_ledger(ch.SPINNING_FLATLINE - 1))
        at = ch.assess(_spinning_ledger(ch.SPINNING_FLATLINE))
        assert below["verdict"] == "STALLED"
        assert at["verdict"] == "SPINNING"
        assert at["exit_code"] == ch.EXIT_SPINNING

    def test_converged_flatline_is_still_healthy(self):
        """open_count == 0 keeps the converged-loop guard."""
        r = ch.assess([_snap(i, 0, [], []) for i in range(12)])
        assert r["verdict"] == "HEALTHY"
        assert "remedy" not in r

    def test_churn_only_ledger_has_no_remedy_state(self, tmp_path):
        _write_ledger(tmp_path, _fact_growth_ledger(4))
        assert ch.stalled_state(tmp_path) is None


# =====================================================================
# S2: the SPINNING verdict carries the remedy
# =====================================================================

class TestSpinningRemedyReference:
    def test_spinning_json_carries_remedy(self):
        r = ch.assess(_spinning_ledger())
        assert r["verdict"] == "SPINNING"
        remedy = r.get("remedy")
        assert remedy, "SPINNING must carry the invokable remedy reference"
        assert remedy["operator"] == "decompose"
        assert remedy["claims"] == ["C-1"]
        assert remedy["dispatch_marker"] == MARKER
        assert "target_ladder.py" in remedy["mint_cmd"]
        assert "--mint" in remedy["mint_cmd"]

    def test_spinning_remedy_has_the_stalled_shape(self):
        stalled = ch.assess([_snap(i, 1, ["C-1"], ["C-1"])
                             for i in range(ch.STALLED_FLATLINE)])
        spinning = ch.assess(_spinning_ledger())
        assert stalled["verdict"] == "STALLED"
        assert spinning["remedy"] == stalled["remedy"]

    def test_spinning_action_names_the_remedy_marker(self):
        action = ch.assess(_spinning_ledger())["action"]
        assert f"`{MARKER}`" in action
        assert "target_ladder.py" in action
        assert "for a stuck claim is admitted at the gate" in action
        assert "STOP dispatching" not in action

    def test_spinning_action_keeps_the_intervention_guidance(self):
        action = ch.assess(_spinning_ledger())["action"]
        for needle in ("escalate tier", "reformulate", "decompose",
                       "DEFER", "escalate to user", ">3x",
                       "flatlined 8 rounds"):
            assert needle in action, needle

    def test_spinning_without_stuck_claims_remedy_names_none(self):
        """The frontier rotates (no dispatched claim is open three
        consecutive rounds): the remedy block names the detector's stuck
        set — empty — and the prose names the open claims for display."""
        r = ch.assess(_rotating_ledger(ch.SPINNING_FLATLINE + 1))
        assert r["verdict"] == "SPINNING"
        assert r["stuck_claims"] == []
        assert r["remedy"]["claims"] == []
        assert "No claim is stuck" in r["action"]
        assert "C-1, C-2" in r["action"]
        assert "no remedy dispatch is admitted" in r["action"]
        assert "for a stuck claim is admitted" not in r["action"]
        assert "--mint" not in r["action"]
        for needle in ("escalate tier", "reformulate", "decompose",
                       "DEFER", "escalate to user"):
            assert needle in r["action"], needle

    def test_human_output_without_stuck_claims_says_no_remedy_target(self):
        human = ch._human(ch.assess(_rotating_ledger(ch.SPINNING_FLATLINE + 1)))
        remedy_lines = [ln for ln in human.splitlines()
                        if ln.startswith("remedy:")]
        assert remedy_lines == [f"remedy: decompose — {ch.NO_STUCK_REMEDY_NOTE}"]
        assert "for a stuck claim is gate-admitted" not in human
        assert "--mint" not in human

    @pytest.mark.parametrize("ledger", [
        _spinning_ledger(),
        [_snap(i, 1, ["C-1"], ["C-1"]) for i in range(ch.STALLED_FLATLINE)],
    ], ids=["spinning", "stalled"])
    def test_human_output_with_stuck_claims_is_unchanged(self, ledger):
        human = ch._human(ch.assess(ledger))
        remedy_lines = [ln for ln in human.splitlines()
                        if ln.startswith("remedy:")]
        assert remedy_lines == [
            "remedy: decompose — mint via python scripts/target_ladder.py "
            "<workspace> --mint <stuck-claim>; a dispatch carrying "
            f"`{MARKER}` for a stuck claim is gate-admitted"]

    def test_cli_exit_code_and_json_for_spinning(self, tmp_path):
        _write_ledger(tmp_path, _spinning_ledger())
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "convergence_health.py"),
             str(tmp_path), "--json"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == ch.EXIT_SPINNING, proc.stderr
        out = json.loads(proc.stdout)
        assert out["verdict"] == "SPINNING"
        assert out["remedy"]["dispatch_marker"] == MARKER


# =====================================================================
# S3: stalled_state serves both verdicts
# =====================================================================

class TestStateForBothVerdicts:
    def test_spinning_state_carries_verdict_and_remedy(self, tmp_path):
        _write_ledger(tmp_path, _spinning_ledger())
        state = ch.stalled_state(tmp_path)
        assert state is not None
        assert state["verdict"] == "SPINNING"
        assert state["stuck_ids"] == ["C-1"]
        assert state["flatlined_open_ids"] == ["C-1"]
        assert state["remedy"]["operator"] == "decompose"
        assert state["remedy_depth"] == 0
        assert state["remedy_max_depth"] == ch.REMEDY_MAX_DEPTH

    def test_stalled_state_still_says_stalled(self, tmp_path):
        _write_ledger(tmp_path, [_snap(i, 1, ["C-1"], ["C-1"])
                                 for i in range(ch.STALLED_FLATLINE)])
        assert ch.stalled_state(tmp_path)["verdict"] == "STALLED"

    @pytest.mark.parametrize("rounds,verdict", [
        (ch.STALLED_FLATLINE + 1, "STALLED"),
        (ch.SPINNING_FLATLINE + 1, "SPINNING"),
    ])
    def test_state_stuck_ids_are_the_detector_stuck_set(
            self, tmp_path, rounds, verdict):
        """Rotating frontier: no stuck claim, so the state names none at
        either verdict (open claims are never promoted to stuck)."""
        _write_ledger(tmp_path, _rotating_ledger(rounds))
        state = ch.stalled_state(tmp_path)
        assert state["verdict"] == verdict
        assert state["stuck_ids"] == []
        assert state["remedy"]["claims"] == []
        last_open = ["C-1", "C-2"] if rounds % 2 == 1 else ["C-3", "C-4"]
        assert state["flatlined_open_ids"] == last_open

    def test_spinning_state_ids_follow_the_stuck_claims(self, tmp_path):
        _write_ledger(tmp_path, _spinning_ledger())
        state = ch.stalled_state(tmp_path)
        assert state["stuck_ids"] == state["remedy"]["claims"] == ["C-1"]

    def test_remedy_depth_counts_admits_at_spinning(self, tmp_path):
        _write_ledger(tmp_path, _ledger_with_admits(_spinning_ledger(), 2))
        assert ch.stalled_state(tmp_path)["remedy_depth"] == 2


# =====================================================================
# scaffold: a workspace the pre-gates pass (mirror of test_worker_budget)
# =====================================================================

def _healthy_ws(tmp_path: Path) -> Path:
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    prev = (now_dt - timedelta(minutes=5)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    (tmp_path / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"last_tick_ts": now, "activity_ts": now, "started_ts": prev,
         "tick_history": [prev, now]}), encoding="utf-8")
    with (tmp_path / "runs" / ".heartbeat.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": prev, "actor": "tick"}) + "\n")
        f.write(json.dumps({"ts": now, "actor": "tick"}) + "\n")
    (tmp_path / "analysis_state.txt").write_text(
        f"deadline_ts: {int(time.time()) + 3600}\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "IN_PROGRESS", "promotion_attempts": 1},
        ]}, sort_keys=False), encoding="utf-8")
    (tmp_path / "claim_deps.yaml").write_text("deps: {}\n", encoding="utf-8")
    (tmp_path / "task_spec.yaml").write_text(
        yaml.safe_dump({"vm_detonation": "allowed"}, sort_keys=False),
        encoding="utf-8")
    return tmp_path


def _paths_for(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def _dispatch_payload(claim: str, marker: bool) -> tuple[dict, str]:
    prompt = (json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": claim, "tier": 1,
        "tools": ["grep"], "agent": "w-test"}})
        + "\nfacts-snapshot: 1 facts"
        + (f"\n{MARKER}\n" if marker else "\n"))
    payload = {"tool_input": {"name": "w-test", "description": "",
                              "prompt": prompt}}
    return payload, prompt


def _add_claim(ws: Path, claim: dict) -> None:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    reg["claims"].append(claim)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")


def _rc(code: int):
    return lambda args, cwd=None: SimpleNamespace(
        returncode=code, stderr="", stdout="")


def _gate(ws: Path, claim: str, marker: bool):
    payload, prompt = _dispatch_payload(claim, marker=marker)
    return wbc.check_convergence_health(_paths_for(ws), claim, payload, prompt)


# =====================================================================
# S4: the gate's rc=2 face
# =====================================================================

class TestGateRc2Face:
    def test_remedy_dispatch_admitted_at_spinning(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        ok, msg = _gate(ws, "C-1", marker=True)
        assert ok is True
        assert "SPINNING" in msg
        assert "remedy" in msg

    def test_admit_writes_the_same_telemetry_row(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        assert _gate(ws, "C-1", marker=True)[0] is True
        rows = [json.loads(line) for line in
                (ws / ch.LEDGER_NAME).read_text(encoding="utf-8").splitlines()]
        admits = [r for r in rows
                  if r.get("action") == ch.REMEDY_ADMIT_ACTION]
        assert len(admits) == 1
        assert admits[0]["claim_id"] == "C-1"
        assert admits[0]["actor"] == "hook:worker_budget"
        assert ch.stalled_state(ws)["remedy_depth"] == 1

    def test_unmarked_dispatch_rejected_at_spinning(
            self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        ok, msg = _gate(ws, "C-1", marker=False)
        assert ok is False
        assert msg == "convergence SPINNING - diagnose before dispatching"

    def test_marked_non_stuck_claim_rejected_at_spinning(
            self, tmp_path, monkeypatch):
        """Marker + a queued claim in the flatlined open set but NOT stuck
        -> rejected, as at the STALLED face."""
        ws = _healthy_ws(tmp_path)
        rows = [_snap(i, 2, ["C-1", "C-Q"], ["C-1"])
                for i in range(ch.SPINNING_FLATLINE)]
        _add_claim(ws, {"id": "C-Q", "status": "OPEN",
                        "promotion_attempts": 0})
        _write_ledger(ws, rows)
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        assert _gate(ws, "C-Q", marker=True)[0] is False

    def test_fresh_open_claim_rejected_at_spinning(
            self, tmp_path, monkeypatch):
        """A fresh unrelated OPEN claim plus the marker is the self-minted
        work shape; provenance (depends_on a stuck claim) is required."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        _add_claim(ws, {"id": "C-777", "status": "OPEN"})
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        ok, msg = _gate(ws, "C-777", marker=True)
        assert ok is False
        assert msg == "convergence SPINNING - diagnose before dispatching"

    def test_minted_subclaim_admitted_at_spinning(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        _add_claim(ws, {"id": "C-2", "status": "OPEN",
                        "depends_on": ["C-1"]})
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        ok, msg = _gate(ws, "C-2", marker=True)
        assert ok is True
        assert "depth=0" in msg

    @pytest.mark.parametrize("rounds,rc", [
        (ch.STALLED_FLATLINE, 1),
        (ch.SPINNING_FLATLINE, 2),
    ])
    def test_depth_cap_closes_channel_b_at_both_faces(
            self, tmp_path, monkeypatch, rounds, rc):
        """Two prior admit rows naming the stuck claim: the follow-through
        channel closes, the stuck claim itself stays admissible — the same
        at the STALLED and the SPINNING face."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _ledger_with_admits(
            [_snap(i, 1, ["C-1"], ["C-1"]) for i in range(rounds)], 2))
        _add_claim(ws, {"id": "C-2", "status": "OPEN",
                        "depends_on": ["C-1"]})
        monkeypatch.setattr(wbc, "_run_py", _rc(rc))
        ok_b, _msg = _gate(ws, "C-2", marker=True)
        assert ok_b is False, "depth cap must close the follow-through channel"
        ok_a, msg_a = _gate(ws, "C-1", marker=True)
        assert ok_a is True, "channel A must survive the depth cap"
        assert "depth=2" in msg_a

    @pytest.mark.parametrize("rounds,rc,verdict", [
        (ch.STALLED_FLATLINE + 1, 1, "STALLED"),
        (ch.SPINNING_FLATLINE + 1, 2, "SPINNING"),
    ])
    def test_open_claims_without_stuck_are_not_admissible(
            self, tmp_path, monkeypatch, rounds, rc, verdict):
        """Open claims, none stuck: a marker dispatch of an open claim, and
        of an OPEN claim whose depends_on names an open (not stuck) claim,
        are both rejected — the same at STALLED and SPINNING."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _rotating_ledger(rounds))
        last_open = ["C-1", "C-2"] if rounds % 2 == 1 else ["C-3", "C-4"]
        _add_claim(ws, {"id": "C-9", "status": "OPEN",
                        "depends_on": [last_open[0]]})
        assert ch.stalled_state(ws)["verdict"] == verdict
        monkeypatch.setattr(wbc, "_run_py", _rc(rc))
        ok, msg = _gate(ws, last_open[0], marker=True)
        assert ok is False, "an open, never-stuck claim is not the remedy"
        assert msg == f"convergence {verdict} - diagnose before dispatching"
        ok, msg = _gate(ws, "C-9", marker=True)
        assert ok is False, "depends_on an open (not stuck) claim is no provenance"
        assert msg == f"convergence {verdict} - diagnose before dispatching"

    def test_legacy_one_arg_call_keeps_block_at_spinning(
            self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        ok, msg = wbc.check_convergence_health({"workspace": str(ws)})
        assert ok is False
        assert msg == "convergence SPINNING - diagnose before dispatching"

    def test_state_exception_fails_closed_at_spinning(
            self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))

        def _boom(ws_):
            raise RuntimeError("state unreadable")
        monkeypatch.setattr(ch, "stalled_state", _boom)
        ok, msg = _gate(ws, "C-1", marker=True)
        assert ok is False
        assert "SPINNING" in msg

    def test_state_drift_fails_closed_at_spinning(self, tmp_path, monkeypatch):
        """rc=2 from the out-of-process check but the re-derived state is
        healthy -> no exemption."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, [_snap(0, 3, ["C-1"], []),
                           _snap(1, 2, ["C-1"], []),
                           _snap(2, 1, ["C-1"], [])])
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        assert _gate(ws, "C-1", marker=True)[0] is False

    def test_crashed_rc4_fail_open_preserved(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        monkeypatch.setattr(wbc, "_run_py", _rc(4))
        ok, msg = _gate(ws, "C-1", marker=True)
        assert ok is True
        assert "crashed (rc=4)" in msg

    def test_rc1_face_unchanged(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, [_snap(i, 1, ["C-1"], ["C-1"])
                           for i in range(ch.STALLED_FLATLINE)])
        monkeypatch.setattr(wbc, "_run_py", _rc(1))
        ok, msg = _gate(ws, "C-1", marker=False)
        assert ok is False
        assert msg == "convergence STALLED - diagnose before dispatching"
        ok, msg = _gate(ws, "C-1", marker=True)
        assert ok is True
        assert "STALLED" in msg


# =====================================================================
# S5: guidance strings
# =====================================================================

class TestSpinningGuidanceNamesRemedy:
    def test_reject_fix_text_describes_the_remedy_path(self):
        text = wbs.REJECT_FIXES["health"]["additionalContext"]
        assert "STOP dispatching" not in text
        assert "remedy" in text
        assert "SPINNING" in text

    def test_gate_message_directs_to_diagnosis(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _spinning_ledger())
        monkeypatch.setattr(wbc, "_run_py", _rc(2))
        _ok, msg = _gate(ws, "C-1", marker=False)
        assert "diagnose before dispatching" in msg
        assert "STOP" not in msg
