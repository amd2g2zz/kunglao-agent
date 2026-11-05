#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rl_v3_direction_954.py — the direction face (#954, Type-3).

Faces under test (the issue's scope, minus #951's config-6 sim validation
which is that card's follow-up, not this one):

  posterior arithmetic — Beta conjugacy pins over the append-only fold
      (direction-register/1 prior + +1 α/β per direction-obs/1 outcome;
      re-registration rebases = the re-arm face);
  collapse predicate — the racing elimination gate's EXACT bounds
      (β mass strictly > 4.0, mean strictly < 0.2) and the
      anti-premature-surrender leg (zero failure observations NEVER
      collapses — #951 config 4's silent-true-arm lesson);
  censor-streak integration (#958 seam) — the posterior feed routes
      through censoring.posterior_observations (censored rows drop
      BEFORE any update), a frozen direction is never eliminated and
      never raceable, a live observation breaks the freeze;
  step credit — step_credit_delta wraps probe_face.probe_delta (THE
      seam, exercised through a REAL run_probe over two ws states),
      the in-process bank + claim-terminal settle (positive -> success,
      negative -> failure, flat/empty -> silence);
  flag — KUNGLAO_DIRECTION=1 enables the loop faces (default OFF: zero
      rows, zero stderr, inert receipts — the zero-behavior pin);
  seals (#799) — armed, a forged direction row can never drive the
      posterior or the elimination gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import censoring, direction, probe_face  # noqa: E402

D = "deep-probe"


# ------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    """The flag axis is per-test: default OFF unless a test sets it."""
    monkeypatch.delenv(direction.FLAG_ENV, raising=False)


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _obs(ws: Path, d: str, outcome, n: int = 1) -> None:
    for _ in range(n):
        direction.observe_outcome(ws, d, outcome)


# ------------------------------------------------- posterior arithmetic

class TestPosteriorArithmetic:
    def test_fresh_and_unregistered_are_the_wide_prior(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        assert direction.posterior(ws, D) == (1.0, 1.0)
        assert direction.posterior(ws, "never-registered") == (1.0, 1.0)

    def test_conjugate_updates_pin(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "success", 3)
        _obs(ws, D, "failure", 2)
        assert direction.posterior(ws, D) == (4.0, 3.0)

    def test_bool_outcomes_are_accepted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.observe_outcome(ws, D, True)
        direction.observe_outcome(ws, D, False)
        assert direction.posterior(ws, D) == (2.0, 2.0)

    def test_custom_prior_rides_the_register_row(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D, alpha=2.0, beta=1.0)
        _obs(ws, D, "success")
        assert direction.posterior(ws, D) == (3.0, 1.0)

    def test_reregistration_rebases_the_posterior(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        _obs(ws, D, "failure", 5)
        assert direction.posterior(ws, D) == (1.0, 6.0)
        direction.new_direction(ws, D, source="re-arm")  # the re-arm face
        assert direction.posterior(ws, D) == (1.0, 1.0)

    def test_malformed_prior_falls_back_to_the_base(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D, alpha=-3, beta="vibes")
        assert direction.posterior(ws, D) == (1.0, 1.0)

    def test_foreign_vocabulary_outcome_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError):
            direction.observe_outcome(ws, D, "vibes")

    def test_empty_direction_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError):
            direction.new_direction(ws, "  ")
        with pytest.raises(ValueError):
            direction.observe_outcome(ws, "", "success")

    def test_rows_are_sealed_and_persist(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D, situation_tags=("lane web", "FAM-X"))
        _obs(ws, D, "success")
        rows = direction.state_rows(ws)
        assert [r["schema"] for r in rows] == [
            "direction-register/1", "direction-obs/1"]
        assert rows[0]["situation_tags"] == ["lane-web", "fam-x"]
        assert rows[0]["source"] == ""
        assert rows[1]["outcome"] == "success"

    def test_censored_rows_never_move_the_posterior(self, tmp_path):
        """The #958 seam end-to-end: censor rows land in the SAME file
        and the posterior feed drops them BEFORE any update."""
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "success", 2)
        before = direction.posterior(ws, D)
        censoring.observe_censored(ws, D, "env_risk_control")
        censoring.observe_live(ws, D)
        assert direction.posterior(ws, D) == before
        kept = censoring.posterior_observations(direction.state_rows(ws))
        assert all(r["schema"] != "direction-censor/1" or
                   r.get("censored") is not True for r in kept)


# ---------------------------------------------------- collapse predicate

class TestCollapsePredicate:
    def test_module_bounds_are_pinned(self):
        assert direction.COLLAPSE_BETA_MASS == 4.0
        assert direction.COLLAPSE_MEAN_FLOOR == 0.2
        assert direction.BASE_ALPHA == 1.0 and direction.BASE_BETA == 1.0
        assert direction.FLAG_ENV == "KUNGLAO_DIRECTION"

    def test_fresh_direction_never_collapses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        assert direction.collapse(ws, D) is False

    def test_three_failures_is_the_exact_non_collapse_bound(self, tmp_path):
        """(α, β) = (1, 4): β == 4.0 is NOT above the mass bound and the
        mean == 0.2 is NOT below the floor — the boundary never fires."""
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 3)
        assert direction.posterior(ws, D) == (1.0, 4.0)
        assert direction.collapse(ws, D) is False

    def test_four_failures_collapse(self, tmp_path):
        """(1, 5): β = 5 > 4 and mean = 1/6 < 0.2 — the first collapsing
        posterior under the base prior."""
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)
        assert direction.collapse(ws, D) is True

    def test_successes_delay_collapse(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)
        _obs(ws, D, "success", 3)          # (4, 5): mean 4/9 = 0.444
        assert direction.collapse(ws, D) is False
        _obs(ws, D, "failure", 4)          # (4, 9): mean 4/13 = 0.308
        assert direction.collapse(ws, D) is False
        _obs(ws, D, "failure", 2)          # (4, 11): mean 4/15 = 0.267
        assert direction.collapse(ws, D) is False
        _obs(ws, D, "failure", 3)          # (4, 14): mean 0.222 — still above
        assert direction.collapse(ws, D) is False
        _obs(ws, D, "failure", 4)          # (4, 18): mean 0.182 < 0.2
        assert direction.collapse(ws, D) is True

    def test_zero_failure_evidence_never_collapses(self, tmp_path):
        """The anti-premature-surrender leg: with NO failure rows the
        predicate is False under ANY bounds — racing alone can never
        kill a silent-true arm."""
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "success", 7)
        assert direction.collapse(ws, D, beta_mass=0.0,
                                  mean_floor=0.999) is False

    def test_exact_boundary_with_custom_bounds(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 3)          # (1, 4), mean 0.2
        assert direction.collapse(ws, D, beta_mass=3.9) is False  # mean==floor
        assert direction.collapse(ws, D, beta_mass=3.9,
                                  mean_floor=0.21) is True
        assert direction.collapse(ws, D, beta_mass=4.0) is False  # β==mass


# ------------------------------------------- censor integration (#958)

class TestCensorIntegration:
    def _frozen(self, ws: Path) -> None:
        for _ in range(censoring.CENSOR_FREEZE_K):
            censoring.observe_censored(ws, D, "env_toolchain")

    def test_frozen_direction_is_never_eliminated(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)          # the posterior says collapse
        assert direction.collapse(ws, D) is True
        self._frozen(ws)                   # ...but the streak freezes it
        assert censoring.frozen(ws, D) is True
        assert direction.maybe_eliminate(ws, D) is False
        assert direction.raceable(ws, D) is False

    def test_frozen_posterior_feed_keeps_its_silence(self, tmp_path):
        """'Never observed': the censored rows drop before any update —
        the frozen direction's posterior is exactly what it had."""
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "success")
        self._frozen(ws)
        assert censoring.posterior_observations(direction.state_rows(ws)) \
            == direction.state_rows(ws)          # censor rows all dropped
        assert direction.posterior(ws, D) == (2.0, 1.0)

    def test_live_observation_breaks_the_freeze(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._frozen(ws)
        assert censoring.frozen(ws, D) is True
        _obs(ws, D, "success")             # a real sample resets the run
        # ...through the seam's live-marker counterpart (censored: false)
        markers = [r for r in censoring.state_rows(ws)
                   if r["censored"] is False]
        assert [r["schema"] for r in markers] == ["direction-censor/1"]
        assert censoring.frozen(ws, D) is False
        assert direction.raceable(ws, D) is True

    def test_collapse_beats_the_race_when_not_frozen(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)
        assert direction.raceable(ws, D) is False

    def test_filter_is_not_bypassable_on_explicit_rows(self, tmp_path):
        """Even a hand-merged stream cannot smuggle mass through a
        censored row — the fold re-applies the seam filter."""
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        smuggled = [
            {"schema": direction.SCHEMA_OBS, "direction": D,
             "outcome": "failure", "censored": True},
            {"schema": direction.SCHEMA_OBS, "direction": D,
             "outcome": "failure"},
        ]
        assert direction.posterior(ws, D, rows=smuggled) == (1.0, 2.0)


# ------------------------------------------------------- elimination

class TestElimination:
    def test_elimination_only_on_collapse(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        assert direction.maybe_eliminate(ws, D) is False
        _obs(ws, D, "failure", 4)
        assert direction.maybe_eliminate(ws, D) is True

    def test_no_failure_observations_never_eliminated(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "success", 10)
        assert direction.maybe_eliminate(ws, D) is False
        assert direction.maybe_eliminate(ws, "unregistered") is False

    def test_elimination_writes_stderr_and_one_state_row(
            self, tmp_path, capsys):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)
        assert direction.maybe_eliminate(ws, D, reason="racing") is True
        err = capsys.readouterr().err
        assert err.count("[rlvr.direction] eliminated") == 1
        assert "racing" in err
        (row,) = [r for r in direction.state_rows(ws)
                  if r["schema"] == "direction-eliminate/1"]
        assert row["direction"] == D
        assert row["alpha"] == 1.0 and row["beta"] == 5.0
        # the 6-dp grid is the module's rounding discipline
        assert row["mean"] == pytest.approx(1.0 / 6.0, abs=1e-6)

    def test_elimination_is_idempotent_until_rearmed(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _obs(ws, D, "failure", 4)
        assert direction.maybe_eliminate(ws, D) is True
        assert direction.maybe_eliminate(ws, D) is True   # no duplicate row
        assert len([r for r in direction.state_rows(ws)
                    if r["schema"] == "direction-eliminate/1"]) == 1
        direction.new_direction(ws, D, source="re-arm")
        assert direction.raceable(ws, D) is True
        assert direction.maybe_eliminate(ws, D) is False  # the re-arm holds


# --------------------------------------------------------- step credit

class TestStepCredit:
    def test_step_credit_wraps_the_probe_delta_seam(self):
        t0 = {"schema": probe_face.PROBE_SCHEMA, "scalar": 0.2}
        t1 = {"schema": probe_face.PROBE_SCHEMA, "scalar": 0.7}
        assert direction.step_credit_delta(None, t0, t1) == \
            probe_face.probe_delta(None, t0, t1) == 0.5
        assert direction.step_credit_delta(None, t1, t0) == -0.5
        assert direction.step_credit_delta(None, "garbage", None) == 0.0

    def test_real_seam_call_over_two_ws_states(self, tmp_path):
        """The end-to-end ΔV seam: a real unit probe (probe_face.run_probe)
        read over two workspace states prices a positive step credit."""
        unit = tmp_path / "units" / "syn-dir-v1"
        unit.mkdir(parents=True)
        (unit / "task.yaml").write_text(
            "schema: kunglao-eval-task/1\ntask_id: syn-dir-v1\n"
            "family: tf-novelvm\nprobe:\n  entrypoint: probe.py\n"
            "  cadence: instant\n", encoding="utf-8")
        (unit / "probe.py").write_text(
            '#!/usr/bin/env python3\n'
            'import json, sys, os\n'
            'ws = sys.argv[1]\n'
            'try:\n'
            '    with open(os.path.join(ws, "prog.txt")) as fh:\n'
            '        n = int(fh.read().strip() or "0")\n'
            'except OSError:\n'
            '    n = 0\n'
            'sys.stdout.write(json.dumps({\n'
            '    "schema": "kunglao-probe-reading/1",\n'
            '    "task_id": "syn-dir-v1", "family": "tf-novelvm",\n'
            '    "scalar": round(min(1.0, n / 10), 6),\n'
            '    "vector": {"n": n}, "reason": "prog-read"}))\n',
            encoding="utf-8")
        ws0, ws1 = _mk_ws(tmp_path), tmp_path / "ws1"
        ws1.mkdir(parents=True)
        (ws1 / "prog.txt").write_text("5", encoding="utf-8")
        r0, r1 = probe_face.run_probe(unit, ws0), probe_face.run_probe(
            unit, ws1)
        assert (r0["scalar"], r1["scalar"]) == (0.0, 0.5)
        assert direction.step_credit_delta(ws1, r0, r1) == 0.5

    def test_bank_and_settle_success(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        direction.observe_step(ws, D, 0.3)
        direction.observe_step(ws, D, 0.4)
        assert direction.step_tally(ws, D) == {"steps": 2, "total": 0.7}
        out = direction.settle_step(ws, D)
        assert out["settled"] is True and out["outcome"] == "success"
        assert direction.posterior(ws, D) == (2.0, 1.0)
        assert direction.step_tally(ws, D) == {"steps": 0, "total": 0.0}
        assert direction.settle_step(ws, D) == {
            "settled": False, "reason": "no-steps", "direction": D}

    def test_negative_total_settles_failure(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.observe_step(ws, D, -0.2)
        direction.observe_step(ws, D, -0.1)
        out = direction.settle_step(ws, D)
        assert out["outcome"] == "failure"
        assert direction.posterior(ws, D) == (1.0, 2.0)

    def test_flat_and_empty_totals_stay_silent(self, tmp_path):
        ws = _mk_ws(tmp_path)
        assert direction.settle_step(ws, D)["reason"] == "no-steps"
        direction.observe_step(ws, D, 0.25)
        direction.observe_step(ws, D, -0.25)
        out = direction.settle_step(ws, D)
        assert out["settled"] is False and out["reason"] == "flat"
        assert direction.posterior(ws, D) == (1.0, 1.0)   # no mass, ever

    def test_non_finite_delta_fails_closed(self, tmp_path):
        ws = _mk_ws(tmp_path)
        rec = direction.observe_step(ws, D, float("nan"))
        assert rec["delta"] == 0.0
        rec = direction.observe_step(ws, D, "vibes")
        assert rec["delta"] == 0.0
        assert direction.settle_step(ws, D)["reason"] == "flat"


# ----------------------------------------------------------------- flag

class TestFlag:
    def test_default_off_and_declared_values(self, monkeypatch):
        monkeypatch.delenv(direction.FLAG_ENV, raising=False)
        assert direction.enabled() is False
        for value in ("0", "false", "off", ""):
            monkeypatch.setenv(direction.FLAG_ENV, value)
            assert direction.enabled() is False
        for value in ("1", "true", "yes", " on"):
            monkeypatch.setenv(direction.FLAG_ENV, value)
            assert direction.enabled() is True

    def test_flag_off_loop_faces_are_inert(self, tmp_path):
        """The zero-behavior pin: OFF, the loop faces write NOTHING and
        bank nothing — the flag-off tree is byte-identical."""
        ws = _mk_ws(tmp_path)
        assert direction.maybe_register(ws) == {
            "enabled": False, "registered": []}
        assert direction.on_step(ws, D, None, None) == {"enabled": False}
        assert direction.on_claim_terminal(ws, D) == {"enabled": False}
        assert not (ws / "runs" / "direction-state.jsonl").exists()
        assert direction.step_tally(ws, D) == {"steps": 0, "total": 0.0}

    def test_flag_off_does_not_touch_a_populated_state_file(self, tmp_path):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)          # direct library call
        before = (ws / "runs" / "direction-state.jsonl").read_bytes()
        direction.maybe_register(ws)
        direction.on_claim_terminal(ws, D)
        assert (ws / "runs" / "direction-state.jsonl").read_bytes() == before

    def test_flag_on_registers_from_primary_questions(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv(direction.FLAG_ENV, "1")
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n"
            "- id: PQ-1\n  q: what signs the request\n"
            "- id: PQ-2\n  q: where is the key\n", encoding="utf-8")
        out = direction.maybe_register(ws)
        assert out["enabled"] is True
        names = [r["direction"] for r in out["registered"]]
        assert names == ["pq:PQ-1", "pq:PQ-2"]
        assert out["registered"][0]["situation_tags"] == ["pq-pq-1"]
        assert out["registered"][0]["source"] == "primary-question"
        assert direction.posterior(ws, "pq:PQ-1") == (1.0, 1.0)

    def test_flag_on_prefers_playbook_groups(self, tmp_path, monkeypatch):
        monkeypatch.setenv(direction.FLAG_ENV, "1")
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n- id: PQ-9\n  q: q\n", encoding="utf-8")
        monkeypatch.setattr(
            direction, "_playbook_groups", lambda _ws: [
                {"context_features": ["lane-web", "fam-replay"],
                 "fragments": ["replay the signer with fresh seeds"]},
                {"context_features": ["lane-web"],
                 "fragments": []},                       # no method content
            ])
        out = direction.maybe_register(ws)
        (row,) = out["registered"]
        assert row["direction"] == "pb:lane-web|fam-replay"
        assert row["situation_tags"] == ["lane-web", "fam-replay"]
        assert row["source"] == "playbook"

    def test_playbook_failure_falls_back_to_questions(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv(direction.FLAG_ENV, "1")
        ws = _mk_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n- id: PQ-9\n  q: q\n", encoding="utf-8")

        def _boom(_ws):
            raise RuntimeError("pool gone")

        monkeypatch.setattr(direction, "_playbook_groups", _boom)
        names = [r["direction"] for r in direction.maybe_register(ws)
                 ["registered"]]
        assert names == ["pq:PQ-9"]

    def test_flag_on_end_to_end(self, tmp_path, monkeypatch, capsys):
        """The production shape: register -> price steps -> settle ->
        race the elimination gate — all behind the one flag."""
        monkeypatch.setenv(direction.FLAG_ENV, "1")
        ws = _mk_ws(tmp_path)
        direction.maybe_register(ws)
        r0 = {"schema": probe_face.PROBE_SCHEMA, "scalar": 0.0}
        r1 = {"schema": probe_face.PROBE_SCHEMA, "scalar": 0.6}
        rec = direction.on_step(ws, D, r0, r1)
        assert rec["enabled"] is True and rec["delta"] == 0.6
        done = direction.on_claim_terminal(ws, D)
        assert done["settle"]["settled"] is True
        assert done["settle"]["outcome"] == "success"
        assert done["eliminated"] is False
        assert direction.posterior(ws, D) == (2.0, 1.0)
        # ...and the racing face: enough failure outcomes collapse it out
        # of the race, one stderr line + one eliminate row ((2, 9): mean
        # 2/11 < 0.2 — the success above delays the collapse to eight)
        _obs(ws, D, "failure", 8)
        assert direction.on_claim_terminal(ws, D)["eliminated"] is True
        assert capsys.readouterr().err.count(
            "[rlvr.direction] eliminated") == 1


# ------------------------------------------------------- seals (#799)

class TestSealedLedgers:
    @pytest.fixture
    def armed_seal(self, tmp_path, monkeypatch):
        from rlvr import learning_seal as seal
        key = tmp_path / "seal.key"
        key.write_text("k" * 48, encoding="utf-8")
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
        return seal

    def test_forged_obs_row_cannot_drive_the_posterior(
            self, tmp_path, armed_seal):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        _obs(ws, D, "success")
        with open(ws / "runs" / "direction-state.jsonl", "a",
                  encoding="utf-8") as fh:
            for _ in range(3):
                fh.write(json.dumps({"schema": "direction-obs/1",
                                     "ts": "x", "direction": D,
                                     "outcome": "failure"}) + "\n")
        assert direction.posterior(ws, D) == (2.0, 1.0)   # forgeries refused
        assert direction.collapse(ws, D) is False

    def test_legit_rows_survive_armed_reads(self, tmp_path, armed_seal):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        _obs(ws, D, "failure", 4)
        assert direction.posterior(ws, D) == (1.0, 5.0)
        assert direction.maybe_eliminate(ws, D) is True
        assert len([r for r in direction.state_rows(ws)
                    if r["schema"] == "direction-eliminate/1"]) == 1

    def test_forged_eliminate_row_cannot_fake_the_gate(
            self, tmp_path, armed_seal, capsys):
        ws = _mk_ws(tmp_path)
        direction.new_direction(ws, D)
        with open(ws / "runs" / "direction-state.jsonl", "a",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"schema": "direction-eliminate/1", "ts": "x",
                 "direction": D, "alpha": 1.0, "beta": 5.0,
                 "mean": 0.16, "reason": "forged"}) + "\n")
        # a wide-posterior direction is not eliminated, and the forged
        # row cannot make maybe_eliminate idempotent-skip a real collapse
        _obs(ws, D, "failure", 4)
        assert direction.maybe_eliminate(ws, D) is True
        assert capsys.readouterr().err.count(
            "[rlvr.direction] eliminated") == 1
