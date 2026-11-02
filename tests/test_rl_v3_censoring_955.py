# -*- coding: utf-8 -*-
"""tests/test_rl_v3_censoring_955.py — the interruption censoring chain (#955).

Faces under test (the issue's chain links 1, 2, 4, 5, 12):

  1. the interruption classifier — mechanical mapping-table pins over
     session record × active env-class blocker files × liveness at exit
     (terminal / censored_env / agent_death; agent-death PROSE never
     enters — the #447/#497 Type E gate owns it);
  3. the PARKED claim state + minimal escrow stub — park/unpark round
     trip with mass conservation, deterministic decay on the #667
     parameters, register status through the ws_yaml single-writer seam;
  4. censored posterior semantics — a censored sample updates NOTHING
     (fold mass byte-stable, trajectory wall holds) and the censor
     streak freezes a direction at K;
  5. the CENSORED(env, reason) row type in the unified ledger append
     face (schema censored/1) + its closed env vocabulary;
  lint: PARKED passes the claim-status machinery (status_defs SUSPENDED,
  open-claim fronts, carrier rule (f), the emit gate's double-ended
  vocabulary check).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import censoring, interruption, parking, q_cells  # noqa: E402
import status_defs  # noqa: E402

_SIG = "a" * 12


# ------------------------------------------------------------- fixtures

def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n"
        "- id: C-2\n  status: IN_PROGRESS\n", encoding="utf-8")
    return ws


def _mk_blocker(ws: Path, text: str, name: str = "B-001.md") -> Path:
    bdir = ws / "blockers"
    bdir.mkdir(exist_ok=True)
    path = bdir / name
    path.write_text(f"## observed\n{text}\n", encoding="utf-8")
    return path


def _bank_claim_mass(ws: Path, claim: str = "C-1") -> None:
    """One settled observation + two step rows — the provisional mass a
    mid-flight crash leaves hanging (#712 audit Gap 2)."""
    q_cells.append_observation(ws, _SIG, "mod-crypto", 1.0,
                               source="settlement", claim=claim)
    q_cells.append_observation(ws, _SIG, "mod-crypto", 0.8,
                               source="settlement", claim=claim,
                               credit_kind="step")
    q_cells.append_observation(ws, _SIG, "mod-crypto", 0.6,
                               source="settlement", claim=claim,
                               credit_kind="step")


# --------------------------------------------- 1. classifier mapping pins

class TestClassifierMapping:
    def test_clean_exit_is_terminal(self, tmp_path):
        ws = _mk_ws(tmp_path)
        got = interruption.classify(
            {"returncode": 0, "timed_out": False, "liveness": "alive"}, ws)
        assert got == {"class": "terminal", "reason_code": "completed"}

    def test_clean_exit_beats_a_stale_blocker(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "risk-control ban: account banned")
        got = interruption.classify({"returncode": 0, "timed_out": False},
                                    ws)
        assert got["class"] == "terminal"

    def test_risk_control_blocker_censors_when_session_bound(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "attributed: risk-control wall, account banned")
        got = interruption.classify(
            {"returncode": 1, "timed_out": False,
             "started_ts": time.time() - 60}, ws)
        assert got == {"class": "censored_env",
                       "reason_code": "env_risk_control"}

    def test_sample_missing_blocker_censors(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "sample deleted from the drop dir mid-run")
        got = interruption.classify(
            {"returncode": -9, "started_ts": time.time() - 60}, ws)
        assert got == {"class": "censored_env",
                       "reason_code": "env_sample_missing"}

    def test_toolchain_blocker_censors_a_timeout(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "debugger broken; toolchain unavailable")
        got = interruption.classify(
            {"returncode": 1, "timed_out": True,
             "started_ts": time.time() - 60}, ws)
        assert got == {"class": "censored_env", "reason_code": "env_toolchain"}

    def test_claim_bound_blocker_censors_without_recency(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "C-1 stalled: sample deleted")
        got = interruption.classify({"returncode": 1, "claim": "C-1"}, ws)
        assert got == {"class": "censored_env",
                       "reason_code": "env_sample_missing"}

    def test_unbound_blocker_never_censors_the_forge_closed(self, tmp_path):
        """The HIGH-1 fix: the agent WRITES blockers/*.md, so an unbound
        keyword match would launder a real failure into censored_env.
        No binding key -> the censor channel is closed."""
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "captcha verify-wall, risk-control ban")
        got = interruption.classify({"returncode": 1, "timed_out": False},
                                    ws)
        assert got == {"class": "agent_death", "reason_code": "nonzero_exit"}

    def test_stale_blocker_outside_the_session_window(self, tmp_path):
        ws = _mk_ws(tmp_path)
        path = _mk_blocker(ws, "risk-control ban")
        stale = time.time() - 3600
        os.utime(path, (stale, stale))
        got = interruption.classify(
            {"returncode": 1, "started_ts": time.time() - 60}, ws)
        assert got == {"class": "agent_death", "reason_code": "nonzero_exit"}

    def test_claim_mismatch_does_not_bind(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "C-1 stalled: risk-control ban")
        got = interruption.classify({"returncode": 1, "claim": "C-2"}, ws)
        assert got == {"class": "agent_death", "reason_code": "nonzero_exit"}

    def test_z_string_started_ts_binds(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "toolchain broken")
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime(time.time() - 60))
        got = interruption.classify(
            {"returncode": 1, "started_ts": started}, ws)
        assert got == {"class": "censored_env", "reason_code": "env_toolchain"}

    def test_invalidated_blocker_is_not_evidence_even_when_bound(
            self, tmp_path):
        ws = _mk_ws(tmp_path)
        _mk_blocker(ws, "risk-control ban\nINVALIDATED 2026-11-01")
        got = interruption.classify(
            {"returncode": 1, "started_ts": time.time() - 60}, ws)
        assert got == {"class": "agent_death", "reason_code": "nonzero_exit"}

    def test_timeout_without_env_evidence_is_agent_death(self, tmp_path):
        ws = _mk_ws(tmp_path)
        got = interruption.classify({"returncode": 1, "timed_out": True}, ws)
        assert got == {"class": "agent_death", "reason_code": "timeout_kill"}

    def test_liveness_dead_breaks_an_rc_none_tie(self, tmp_path):
        ws = _mk_ws(tmp_path)
        got = interruption.classify(
            {"returncode": None, "timed_out": False, "liveness": "dead"}, ws)
        assert got == {"class": "agent_death", "reason_code": "liveness_lost"}

    def test_fully_unknown_exit_is_agent_death(self, tmp_path):
        ws = _mk_ws(tmp_path)
        got = interruption.classify({}, ws)
        assert got == {"class": "agent_death", "reason_code": "unknown_exit"}

    def test_absent_workspace_never_raises(self, tmp_path):
        got = interruption.classify({"returncode": 1},
                                    tmp_path / "no-such-ws")
        assert got["class"] == "agent_death"


# ------------------------------- 3. PARKED + escrow: park/unpark round trip

class TestParking:
    def test_park_unpark_round_trip_conserves_mass(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _bank_claim_mass(ws)
        mass = parking.provisional_mass(ws, "C-1")
        assert mass == pytest.approx(2.4)     # 1.0 settled + 0.8 + 0.6 steps

        receipt = parking.park_claim(ws, "C-1", "env_risk_control")
        assert receipt["mass"] == pytest.approx(mass)
        assert receipt["prior_status"] == "OPEN"
        assert receipt["escrow_design"] == "#667"

        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][0]["status"] == "PARKED"
        assert reg["claims"][0]["wake_condition"]  # carrier rule (f)
        assert reg["claims"][1]["status"] == "IN_PROGRESS"  # untouched

        (row,) = parking.escrow_rows(ws)
        assert row["schema"] == "parked-mass/1"
        assert row["event"] == "park"
        assert row["mass"] == pytest.approx(mass)
        assert parking.escrow_balance(ws) == pytest.approx(mass)

        release = parking.unpark_claim(ws, "C-1")
        assert release["restored_mass"] == pytest.approx(mass)
        assert release["restored_status"] == "OPEN"
        assert parking.escrow_balance(ws) == pytest.approx(0.0)
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][0]["status"] == "OPEN"
        assert not reg["claims"][0].get("wake_condition")

    def test_unpark_restores_the_prior_status(self, tmp_path):
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-2", "env_toolchain")
        parking.unpark_claim(ws, "C-2")
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][1]["status"] == "IN_PROGRESS"

    def test_double_park_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-1", "env_sample_missing")
        with pytest.raises(ValueError, match="already PARKED"):
            parking.park_claim(ws, "C-1", "env_sample_missing")

    def test_unpark_of_a_live_claim_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError, match="not PARKED"):
            parking.unpark_claim(ws, "C-1")

    def test_unknown_claim_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError, match="unknown claim"):
            parking.park_claim(ws, "C-999", "env_toolchain")

    def test_dirty_ledger_reads_as_zero_mass(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "runs" / "experience.jsonl").write_text(
            "{broken json\n", encoding="utf-8")
        # the tolerant JSONL read skips the broken line, so the mass is
        # honestly 0 and the park proceeds with a zero escrow — the
        # unreadable-LEDGER (exception) path still raises in
        # provisional_mass; a dirty LINE is a documented empty read.
        assert parking.provisional_mass(ws, "C-1") == 0.0

    def test_decay_is_deterministic(self):
        assert parking.decayed(1.0, 0) == 1.0
        assert parking.decayed(1.0, 1) == pytest.approx(0.95)
        assert parking.decayed(1.0, 2) == pytest.approx(0.9025)
        assert parking.decayed(2.4, 10) == parking.decayed(2.4, 10)
        assert parking.decayed(1.0, 10_000) == 0.0          # floor at zero
        assert parking.decayed(1.0, -5) == 1.0              # no time travel
        assert parking.decayed(1.0, 3, "unheard-class") == 1.0  # no invented decay

    def test_decay_class_rides_the_park_row(self, tmp_path):
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-1", "env_risk_control")
        (row,) = parking.escrow_rows(ws)
        assert row["decay_class"] == "default"
        assert row["reason"] == "env_risk_control"

    def test_register_refusal_wedges_nothing(self, tmp_path, monkeypatch):
        """Fix 3: the register writes come FIRST — a refused write aborts
        with NO park row (a retry is clean, no wedged half-park)."""
        ws = _mk_ws(tmp_path)
        _bank_claim_mass(ws)
        import ws_yaml
        monkeypatch.setattr(ws_yaml, "main",
                            lambda argv: 3)  # the seam refuses
        with pytest.raises(ValueError, match="refused"):
            parking.park_claim(ws, "C-1", "env_risk_control")
        assert parking.escrow_rows(ws) == []
        assert parking.escrow_balance(ws) == 0.0

    def test_escrow_append_failure_rolls_the_register_back(
            self, tmp_path, monkeypatch):
        """Fix 3: an escrow failure AFTER a landed register write is
        compensated — the register restores the prior status and the
        wake_condition drops, so a retry is clean."""
        ws = _mk_ws(tmp_path)
        _bank_claim_mass(ws)

        def _boom(ws_, row):
            raise OSError("disk gone")

        monkeypatch.setattr(parking, "_append_row", _boom)
        with pytest.raises(OSError, match="disk gone"):
            parking.park_claim(ws, "C-1", "env_risk_control")
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][0]["status"] == "OPEN"
        assert not reg["claims"][0].get("wake_condition")
        assert parking.escrow_rows(ws) == []


# ------------------------------------ 4. censored-no-update + streak freeze

class TestCensoredSemantics:
    def test_censored_rows_never_reach_the_fold(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _bank_claim_mass(ws)
        before = q_cells.fold(q_cells.default_store(ws)).family_mass(
            "mod-crypto")
        q_cells.append_censored(ws, "risk-control", "env_risk_control",
                                source="protocol", claim="C-1")
        censoring.observe_censored(ws, "deep-probe", "env_risk_control")
        after = q_cells.fold(q_cells.default_store(ws)).family_mass(
            "mod-crypto")
        assert before == after                     # NO posterior update
        schemas = {r["schema"] for r in q_cells.trajectory_rows(ws)}
        assert schemas == {"q-cell-obs/1"}         # the trajectory wall holds

    def test_streak_freezes_at_k_and_live_breaks_it(self, tmp_path):
        ws = _mk_ws(tmp_path)
        for _ in range(censoring.CENSOR_FREEZE_K - 1):
            censoring.observe_censored(ws, "deep-probe", "env_toolchain")
        assert not censoring.frozen(ws, "deep-probe")
        censoring.observe_censored(ws, "deep-probe", "env_toolchain")
        assert censoring.frozen(ws, "deep-probe")       # K consecutive
        assert not censoring.frozen(ws, "other-dir")    # per-direction
        censoring.observe_live(ws, "deep-probe")        # #954 seam face
        assert not censoring.frozen(ws, "deep-probe")

    def test_streaks_are_per_direction(self, tmp_path):
        ws = _mk_ws(tmp_path)
        censoring.observe_censored(ws, "d-1", "env_risk_control")
        censoring.observe_censored(ws, "d-1", "env_risk_control")
        censoring.observe_censored(ws, "d-2", "env_toolchain")
        streaks = censoring.censor_streaks(ws)
        assert streaks == {"d-1": 2, "d-2": 1}

    def test_posterior_filter_drops_only_censored_rows(self, tmp_path):
        ws = _mk_ws(tmp_path)
        censoring.observe_censored(ws, "d-1", "env_risk_control")
        censoring.observe_live(ws, "d-1")
        rows = censoring.state_rows(ws)
        kept = censoring.posterior_observations(rows)
        assert [r["censored"] for r in kept] == [False]
        assert censoring.posterior_observations([]) == []

    def test_empty_direction_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError):
            censoring.observe_censored(ws, "  ", "env_toolchain")


# --------------------------------------- 5. the CENSORED ledger row type

class TestCensoredRowSchema:
    def test_row_shape_and_seal(self, tmp_path):
        ws = _mk_ws(tmp_path)
        out = q_cells.append_censored(ws, "sample-missing", "env_sample_missing",
                                      source="protocol", claim="C-1",
                                      rollout_id="ro-1", direction="d-1")
        row = out["row"]
        assert row["schema"] == "censored/1"
        assert row["env"] == "sample-missing"
        assert row["reason"] == "env_sample_missing"
        assert row["censored"] is True
        assert row["claim"] == "C-1"
        (read,) = q_cells.censored_rows(ws)   # the sealed/unsealed read face
        assert read["direction"] == "d-1"
        assert read["schema"] == "censored/1"

    def test_optional_columns_absent_when_unsupplied(self, tmp_path):
        ws = _mk_ws(tmp_path)
        q_cells.append_censored(ws, "toolchain", "env_toolchain",
                                source="protocol")
        (row,) = q_cells.censored_rows(ws)
        assert "claim" not in row and "rollout_id" not in row \
            and "direction" not in row     # additive-column discipline

    def test_foreign_env_class_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError, match="closed"):
            q_cells.append_censored(ws, "vibes", "env_vibes", source="p")

    def test_empty_source_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError, match="source"):
            q_cells.append_censored(ws, "toolchain", "env_toolchain",
                                    source="  ")

    def test_censored_rows_survive_the_process(self, tmp_path):
        ws = _mk_ws(tmp_path)
        q_cells.append_censored(ws, "risk-control", "env_risk_control",
                                source="protocol")
        rows = json.loads(json.dumps(q_cells.censored_rows(ws)))
        assert rows and rows[0]["censored"] is True   # link 12: persistence


# ------------------------------------------- #799 seals on the new ledgers

class TestSealedLedgers:
    """Fix 2: the parked-mass and direction-state rows ride the same
    #799 seal discipline as every q-cell row — armed, a forged raw row
    can never drive escrow_balance(), open_park_row() or frozen()."""

    @pytest.fixture
    def armed_seal(self, tmp_path, monkeypatch):
        from rlvr import learning_seal as seal
        key = tmp_path / "seal.key"
        key.write_text("k" * 48, encoding="utf-8")
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
        return seal

    @staticmethod
    def _forge(ws: Path, rel: str, row: dict) -> None:
        with open(ws / rel, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_forged_escrow_row_is_refused(self, tmp_path, armed_seal):
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-1", "env_risk_control")
        assert parking.escrow_balance(ws) == pytest.approx(0.0)
        self._forge(ws, "runs/parked-mass.jsonl",
                    {"schema": "parked-mass/1", "event": "park",
                     "claim_id": "C-1", "mass": 999.0, "ts": "x",
                     "reason": "forged", "decay_class": "default",
                     "prior_status": "OPEN"})
        rows = parking.escrow_rows(ws)
        assert len(rows) == 1                    # the forged row is gone
        assert parking.escrow_balance(ws) == pytest.approx(0.0)
        assert parking.open_park_row(ws, "C-1") is not None  # the real one

    def test_legit_escrow_rows_survive_armed_reads(self, tmp_path,
                                                   armed_seal):
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-1", "env_risk_control")
        parking.unpark_claim(ws, "C-1")
        assert parking.escrow_balance(ws) == pytest.approx(0.0)
        assert len(parking.escrow_rows(ws)) == 2   # park + release, sealed

    def test_forged_state_row_cannot_drive_frozen(self, tmp_path,
                                                  armed_seal):
        ws = _mk_ws(tmp_path)
        censoring.observe_censored(ws, "d-1", "env_risk_control")
        censoring.observe_censored(ws, "d-1", "env_risk_control")
        assert not censoring.frozen(ws, "d-1")
        for _ in range(censoring.CENSOR_FREEZE_K):
            self._forge(ws, "runs/direction-state.jsonl",
                        {"schema": "direction-censor/1", "ts": "x",
                         "direction": "d-1", "censored": True,
                         "reason": "forged"})
        assert censoring.frozen(ws, "d-1") is False   # forgeries refused
        assert censoring.censor_streak(censoring.state_rows(ws),
                                       "d-1") == 2

    def test_legit_state_rows_survive_armed_reads(self, tmp_path,
                                                  armed_seal):
        ws = _mk_ws(tmp_path)
        for _ in range(censoring.CENSOR_FREEZE_K):
            censoring.observe_censored(ws, "d-1", "env_toolchain")
        assert censoring.frozen(ws, "d-1") is True


# --------------------------------------- lint compatibility: PARKED status

class TestParkedStatusLint:
    def test_parked_is_suspended_never_terminal(self):
        assert "PARKED" in status_defs.SUSPENDED
        assert "PARKED" not in status_defs.TERMINAL
        assert "PARKED" not in status_defs.ACTIVE_STATUSES
        assert "PARKED" not in status_defs.PARTIAL_STATUSES
        assert "PARKED" not in status_defs.IN_PROGRESS_STATUSES

    def test_parked_claims_leave_the_open_fronts(self):
        import convergence_check
        reg = {"claims": [{"id": "C-1", "status": "PARKED"},
                          {"id": "C-2", "status": "OPEN"}]}
        open_ids = [c["id"] for c in convergence_check._open_claims(reg)]
        assert open_ids == ["C-2"]

    def test_carrier_rule_f_demands_a_wake_condition(self, tmp_path):
        import carrier_consistency
        ws = _mk_ws(tmp_path)
        parking.park_claim(ws, "C-1", "env_risk_control")
        clean = carrier_consistency.check(ws)
        assert clean["ok"], clean["violations"]
        # hand-strip the wake condition (ws_yaml del, the sanctioned seam)
        import ws_yaml
        assert ws_yaml.main(["del", str(ws / "claim-register.yaml"),
                             "claims.0.wake_condition"]) == 0
        dirty = carrier_consistency.check(ws)
        assert not dirty["ok"]
        assert any("(f)" in v and "PARKED" in v
                   for v in dirty["violations"])

    def test_claims_store_declares_the_parked_edges(self, tmp_path):
        """LOW-5: PARKED joins the LEGAL_TRANSITIONS matrix — incoming
        park_censored (wake-condition enforced, rule (f)) and the
        outgoing unpark edge."""
        import claims_store as cs
        ws = _mk_ws(tmp_path)
        refused = cs.apply(ws, "C-1", "park_censored", actor="t")
        assert refused.ok is False and "wake-condition" in refused.reason
        parked = cs.apply(ws, "C-1", "park_censored", actor="t",
                          wake_condition="env-repair ladder resume")
        assert parked.ok is True
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][0]["status"] == "PARKED"
        resumed = cs.apply(ws, "C-1", "unpark", actor="t")
        assert resumed.ok is True
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text())
        assert reg["claims"][0]["status"] == "OPEN"

    def test_emit_gate_vocabulary_stays_double_ended_clean(self):
        import emit_gate
        scan = emit_gate.scan(ROOT)
        assert not scan["orphans"], scan["orphans"]
        assert not scan["unregistered"], scan["unregistered"]
