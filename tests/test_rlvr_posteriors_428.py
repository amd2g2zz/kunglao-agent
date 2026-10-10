# -*- coding: utf-8 -*-
"""tests/test_rlvr_posteriors_428.py — the γ Discounted-TS posterior store.

Issue 428 + 420 Phase 2 (v0.1.6 W2-T1): ``scripts/rlvr/posteriors.py``
owns the learned-state core — an append-only JSONL store
(``runs/posterior-store.jsonl``, ledger-isomorphic with rollout_ledger)
whose fold/read face applies the γ forgetting recurrence

    (α, β) ← γ · (α, β) + obs        (per (state, arm) cell, input order)

so raw counts are never rewritten — decay is a READ-face property and the
sampled distribution is always a GENUINE posterior of the discounted data
(TS invariant, issue 428). Pins:

  - bit-exact fold math: hand-computable exact-binary recurrences pinned
    in float.hex, plus a numpy-view vs pure-Python scalar bit-equality
    pin (the determinism discipline of tests/test_rlvr_bitexact.py);
  - input-order sensitivity + replay determinism;
  - TS invariant: sampled frequencies match the decayed posterior's
    probabilities (validated against an independent direct-posterior
    Monte Carlo, not against itself);
  - self-heal (issue 428 pin): injected early misattribution decays out under
    γ < 1 once contradicting evidence arrives (γ = 1 control stays stuck);
  - cold-start width: γ < 1 keeps the posterior wider than γ = 1 after
    the same observation count (owner: 冷启动偏向更大探索空间);
  - pseudo-count priors as the learning-rate knob;
  - outcome-adaptive γ schedule: poor outcomes → γ grows slowly (stays
    near the floor = strong forgetting), improving → γ → 1.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import posteriors as rp  # noqa: E402

TS = "2026-09-29T00:00:00Z"


def _fhex(value) -> str:
    return float(value).hex()


def _assert_hex(label: str, value, golden_hex: str) -> None:
    assert _fhex(value) == golden_hex, (
        f"BIT-EXACT PIN FAILED: {label}: got {float(value).hex()} "
        f"({value!r}), golden {golden_hex}")


def _seed_cell(ws: Path, state: str, arm: str, outcomes, gamma=1.0) -> None:
    for out in outcomes:
        res = rp.record(ws, state, arm, out, gamma=gamma, ts=TS)
        assert res["appended"], res


# ---------- 1. store faces: schema, append-only, fail-open reads -------------

class TestStoreFaces:
    def test_record_appends_versioned_row(self, tmp_path):
        res = rp.record(tmp_path, "sig-a", "static-first", 1,
                        gamma=0.95, ts=TS)
        assert res["appended"] is True and res["reason"] is None
        rows = rp.read(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["schema"] == rp.SCHEMA
        assert row["schema"] == "posterior-store/1"
        assert row["state"] == "sig-a" and row["arm"] == "static-first"
        assert row["ts"] == TS
        assert row["gamma"] == 0.95
        assert row["outcome"] == 1
        assert row["alpha_add"] == 1.0 and row["beta_add"] == 0.0

    def test_record_default_gamma_is_the_shipped_dts_schedule(self, tmp_path):
        """Owner ruling 2026-09-29 (DTS REPLACES TS): no plain-TS default
        anywhere — gamma=None records the SHIPPED default schedule's γ
        (default_schedule().gamma(), the adaptive day-one value from the
        neutral seed), never the γ = 1 no-forgetting constant."""
        rp.record(tmp_path, "s", "a", 0, ts=TS)
        row = rp.read(tmp_path)[0]
        assert row["gamma"] == rp.default_schedule().gamma()
        assert row["gamma"] != 1.0
        assert row["beta_add"] == 1.0

    def test_gamma_domain_enforced_at_append(self, tmp_path):
        """γ ∈ (0, 1]: zero/negative/over-one/non-numeric refused loudly
        (result dict, no raise), nothing appended. gamma=None is NOT in
        the domain check — it is the documented 'undecided' sentinel that
        records the shipped DTS default schedule's γ
        (see test_record_default_gamma_is_the_shipped_dts_schedule)."""
        for bad in (0, -0.5, 1.5, "0.9", float("inf")):
            res = rp.record(tmp_path, "s", "a", 1, gamma=bad, ts=TS)
            assert res["appended"] is False and res["reason"], (bad, res)
        assert rp.read(tmp_path) == []
        ok = rp.record(tmp_path, "s", "a", 1, gamma=1.0, ts=TS)
        assert ok["appended"] is True

    def test_outcome_domain_enforced(self, tmp_path):
        """Bernoulli only: 0/1 in int/float/bool. Everything else —
        fractional rewards, strings, None — refused (scalar semantics are
        NOT this store's; it accepts observations as data, 0 or 1)."""
        for good, (a_add, b_add) in ((1, (1.0, 0.0)), (0, (0.0, 1.0)),
                                     (True, (1.0, 0.0)), (0.0, (0.0, 1.0))):
            ws = tmp_path / str(good)
            res = rp.record(ws, "s", "a", good, gamma=1.0, ts=TS)
            assert res["appended"] is True
            row = rp.read(ws)[0]
            assert (row["alpha_add"], row["beta_add"]) == (a_add, b_add)
        for bad in (0.5, 2, -1, "pass", None, [1]):
            res = rp.record(tmp_path, "s", "a", bad, gamma=1.0, ts=TS)
            assert res["appended"] is False and res["reason"], (bad, res)

    def test_empty_identity_refused(self, tmp_path):
        for state, arm in (("", "a"), ("s", ""), ("  ", "a"), (None, "a")):
            res = rp.record(tmp_path, state, arm, 1, gamma=1.0, ts=TS)
            assert res["appended"] is False and res["reason"]

    def test_store_is_append_only_byte_prefix(self, tmp_path):
        """The byte prefix is invariant across activity (wal posture):
        later appends never rewrite earlier bytes."""
        rp.record(tmp_path, "s", "a", 1, gamma=0.9, ts=TS)
        p = tmp_path / rp.STORE_REL
        first = p.read_bytes()
        rp.record(tmp_path, "s", "a", 0, gamma=0.9, ts=TS)
        rp.record(tmp_path, "s", "b", 1, gamma=1.0, ts=TS)
        grown = p.read_bytes()
        assert grown.startswith(first)
        assert len(grown) > len(first)

    def test_missing_store_reads_empty(self, tmp_path):
        assert rp.read(tmp_path) == []
        view = rp.fold(tmp_path)
        assert len(view.cells) == 0
        assert view.cell("sig-a", "static-first") is None

    def test_dirty_rows_skipped_fail_open(self, tmp_path):
        p = tmp_path / rp.STORE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps({"schema": rp.SCHEMA, "state": "s", "arm": "a",
                           "ts": TS, "gamma": 1.0, "outcome": 1,
                           "alpha_add": 1.0, "beta_add": 0.0})
        p.write_text("{not json\n" + good + "\n", encoding="utf-8")
        rows = rp.read(tmp_path)
        assert len(rows) == 1 and rows[0]["state"] == "s"

    def test_unknown_schema_version_never_half_read(self, tmp_path):
        """The version wall: a row from a FOREIGN schema version is
        skipped loudly, never merged into the fold (no-backcompat)."""
        p = tmp_path / rp.STORE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"schema": "posterior-store/9", "state": "s", "arm": "a",
             "ts": TS, "gamma": 1.0, "outcome": 1,
             "alpha_add": 1.0, "beta_add": 0.0}) + "\n", encoding="utf-8")
        assert rp.read(tmp_path) == []
        assert len(rp.fold(tmp_path).cells) == 0

    def test_unicode_identity_round_trips(self, tmp_path):
        rp.record(tmp_path, "签名", "家族", 1, gamma=0.9, ts=TS)
        view = rp.fold(tmp_path)
        cell = view.cell("签名", "家族")
        assert cell is not None
        _assert_hex("unicode alpha (γ=0.9: 0.9·1+1)", cell["alpha"],
                    _fhex(1.9))


# ---------- 2. fold math: γ decay at the READ face, bit-exact -----------------

class TestFoldMath:
    def test_gamma_unit_fold_equals_raw_counts_plus_priors(self, tmp_path):
        _seed_cell(tmp_path, "s", "a", [1, 1, 0], gamma=1.0)
        view = rp.fold(tmp_path)
        cell = view.cell("s", "a")
        assert cell["alpha"] == 3.0 and cell["beta"] == 2.0  # prior 1+1
        assert cell["n_effective"] == 3.0

    def test_gamma_decay_hand_pinned_bit_exact(self, tmp_path):
        """γ = 0.5, prior (1, 1), obs [pass, fail]:
        α: 0.5·1+1 = 1.5 → 0.5·1.5+0 = 0.75; β: 0.5·1+0 = 0.5 → 0.5·0.5+1 = 1.25.
        Exact binary fractions — the hex IS the hand computation."""
        _seed_cell(tmp_path, "s", "a", [1, 0], gamma=0.5)
        cell = rp.fold(tmp_path).cell("s", "a")
        _assert_hex("alpha decayed", cell["alpha"], "0x1.8000000000000p-1")
        _assert_hex("beta decayed", cell["beta"], "0x1.4000000000000p+0")
        _assert_hex("mean decayed", cell["mean"], "0x1.8000000000000p-2")
        _assert_hex("n_eff decayed", cell["n_effective"],
                    "0x1.8000000000000p+0")  # 1.5

    def test_decay_applies_to_priors_too(self, tmp_path):
        """The recurrence is uniform: pseudo-count priors seed the counts
        and decay under the same γ from cell birth."""
        _seed_cell(tmp_path, "s", "a", [1], gamma=0.5)
        cell = rp.fold(tmp_path).cell("s", "a")
        _assert_hex("alpha prior-decayed", cell["alpha"],
                    "0x1.8000000000000p+0")  # 0.5·1 + 1

    def test_input_order_changes_the_decayed_posterior(self, tmp_path):
        """(α,β) ← γ·(α,β)+obs is order-sensitive — pass-then-fail is NOT
        fail-then-pass under γ < 1. Both directions hand-pinned."""
        ws1 = tmp_path / "w1"
        ws2 = tmp_path / "w2"
        _seed_cell(ws1, "s", "a", [1, 0], gamma=0.5)
        _seed_cell(ws2, "s", "a", [0, 1], gamma=0.5)
        c1 = rp.fold(ws1).cell("s", "a")
        c2 = rp.fold(ws2).cell("s", "a")
        _assert_hex("order1 alpha", c1["alpha"], "0x1.8000000000000p-1")
        _assert_hex("order1 beta", c1["beta"], "0x1.4000000000000p+0")
        _assert_hex("order2 alpha", c2["alpha"], "0x1.4000000000000p+0")
        _assert_hex("order2 beta", c2["beta"], "0x1.8000000000000p-1")

    def test_fold_is_bit_reproducible(self, tmp_path):
        """Same store, two folds → bit-identical floats (replay
        determinism; the store is the only input)."""
        _seed_cell(tmp_path, "s", "a", [1, 0, 1, 1, 0], gamma=0.93)
        c1 = rp.fold(tmp_path).cell("s", "a")
        c2 = rp.fold(tmp_path).cell("s", "a")
        for key in ("alpha", "beta", "mean", "n_effective"):
            assert _fhex(c1[key]) == _fhex(c2[key]), key

    def test_numpy_view_matches_pure_python_scalar_replay(self, tmp_path):
        """The determinism discipline: the numpy view's floats are
        bit-identical to an independent pure-Python scalar replay of the
        recurrence (same IEEE ops, no shared code path)."""
        rows_spec = [("s", "a", o, g) for o, g in
                     ((1, 0.9), (0, 0.9), (1, 0.95), (1, 0.98), (0, 0.9))]
        for state, arm, out, g in rows_spec:
            assert rp.record(tmp_path, state, arm, out, gamma=g,
                             ts=TS)["appended"]
        view = rp.fold(tmp_path)
        alpha = beta = 1.0  # priors
        n = 0.0             # n_eff seeds at 0 at cell birth
        for _, _, out, g in rows_spec:
            alpha = g * alpha + (1.0 if out else 0.0)
            beta = g * beta + (0.0 if out else 1.0)
            n = g * n + 1.0
        cell = view.cell("s", "a")
        assert _fhex(cell["alpha"]) == _fhex(alpha)
        assert _fhex(cell["beta"]) == _fhex(beta)
        assert _fhex(cell["n_effective"]) == _fhex(n)
        assert _fhex(cell["mean"]) == _fhex(alpha / (alpha + beta))

    def test_per_row_recorded_gamma_is_the_default_read(self, tmp_path):
        """fold() without a schedule replays each row's OWN recorded γ —
        the store's truth is what the engine believed at event time."""
        ws = tmp_path
        for out, g in ((1, 0.9), (0, 1.0), (1, 0.8)):
            rp.record(ws, "s", "a", out, gamma=g, ts=TS)
        view = rp.fold(ws)
        alpha = beta = 1.0
        for out, g in ((1, 0.9), (0, 1.0), (1, 0.8)):
            alpha = g * alpha + float(out)
            beta = g * beta + float(1 - out)
        cell = view.cell("s", "a")
        assert _fhex(cell["alpha"]) == _fhex(alpha)
        assert _fhex(cell["beta"]) == _fhex(beta)

    def test_counterfactual_refold_under_other_schedule(self, tmp_path):
        """The same store re-folded under a DIFFERENT schedule is a
        counterfactual — the calibration replay face EX-2 consumes."""
        _seed_cell(tmp_path, "s", "a", [1, 0, 1], gamma=1.0)  # 2 passes 1 fail
        raw = rp.fold(tmp_path).cell("s", "a")
        decayed = rp.fold(tmp_path, schedule=rp.gamma_constant(0.5)).cell(
            "s", "a")
        assert raw["alpha"] == 3.0 and raw["beta"] == 2.0
        assert decayed["alpha"] < raw["alpha"]
        assert decayed["beta"] < raw["beta"]

    def test_priors_are_the_learning_rate_knob(self, tmp_path):
        """Pseudo-count prior strength = how many observations a cell
        carries at birth: a strong prior barely moves on one obs."""
        weak = tmp_path / "weak"
        strong = tmp_path / "strong"
        _seed_cell(weak, "s", "a", [1], gamma=1.0)
        _seed_cell(strong, "s", "a", [1], gamma=1.0)
        c_weak = rp.fold(weak, prior_alpha=1.0, prior_beta=1.0).cell("s", "a")
        c_strong = rp.fold(strong, prior_alpha=50.0,
                           prior_beta=50.0).cell("s", "a")
        assert c_weak["mean"] == pytest.approx(2.0 / 3.0)
        assert c_strong["mean"] == pytest.approx(51.0 / 101.0)  # (51, 50)
        assert abs(c_strong["mean"] - 0.5) < 0.01

    def test_cells_keep_insertion_order_and_arm_separation(self, tmp_path):
        _seed_cell(tmp_path, "s1", "arm-b", [1], gamma=1.0)
        _seed_cell(tmp_path, "s1", "arm-a", [0], gamma=1.0)
        _seed_cell(tmp_path, "s2", "arm-b", [1], gamma=1.0)
        view = rp.fold(tmp_path)
        assert view.cells == [("s1", "arm-b"), ("s1", "arm-a"),
                              ("s2", "arm-b")]
        assert view.cell("s1", "arm-b")["alpha"] == 2.0
        assert view.cell("s1", "arm-a")["beta"] == 2.0
        assert view.cell("s2", "arm-b")["alpha"] == 2.0


# ---------- 3. the numpy view: shapes, boundaries, no leaked scalars ----------

class TestNumpyView:
    def test_view_fields_are_python_floats_not_numpy_scalars(self, tmp_path):
        """numpy policy 3: no numpy floats escape a module boundary
        (json cannot serialize np.float64 — a leak is a bug)."""
        _seed_cell(tmp_path, "s", "a", [1, 0], gamma=0.9)
        view = rp.fold(tmp_path)
        cell = view.cell("s", "a")
        for v in cell.values():
            assert type(v) is float, (v, type(v))
        for m in view.means():
            assert type(m) is float

    def test_means_and_widths_match_per_cell_math(self, tmp_path):
        _seed_cell(tmp_path, "s", "a", [1, 1, 0], gamma=1.0)
        view = rp.fold(tmp_path)
        means = view.means()
        assert len(means) == 1
        assert means[0] == pytest.approx(3.0 / 5.0)
        widths = view.widths()
        import math
        expected = math.sqrt(3.0 * 2.0 / (25.0 * 6.0))
        assert widths[0] == pytest.approx(expected)

    def test_width_shrinks_with_effective_count(self, tmp_path):
        """Cold-start width pin (owner: 冷启动偏向更大探索空间): the SAME
        observations leave a γ < 1 posterior wider (more uncertain →
        wider exploration) than a γ = 1 posterior."""
        wide_ws = tmp_path / "wide"
        narrow_ws = tmp_path / "narrow"
        outcomes = [1, 1, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0,
                    1, 1]
        _seed_cell(wide_ws, "s", "a", outcomes, gamma=0.9)
        _seed_cell(narrow_ws, "s", "a", outcomes, gamma=1.0)
        wide = rp.fold(wide_ws).cell("s", "a")
        narrow = rp.fold(narrow_ws).cell("s", "a")
        assert wide["n_effective"] < narrow["n_effective"]
        assert wide["width"] > narrow["width"]

    def test_cell_query_unknown_returns_none(self, tmp_path):
        _seed_cell(tmp_path, "s", "a", [1], gamma=1.0)
        view = rp.fold(tmp_path)
        assert view.cell("s", "other") is None
        assert view.cell("other", "a") is None

    def test_sample_returns_python_floats_via_stdlib_beta(self, tmp_path):
        """DTS sampling stays stdlib betavariate (numpy policy 4):
        the view samples the DECAYED posterior per cell."""
        _seed_cell(tmp_path, "s", "a", [1, 1, 1, 0], gamma=0.9)
        view = rp.fold(tmp_path)
        draws = view.sample(random.Random(11))
        assert len(draws) == 1
        assert type(draws[0]) is float
        cell = view.cell("s", "a")
        # Fresh same-seed rng: the reference draw the sampler must match.
        reference = random.Random(11).betavariate(cell["alpha"],
                                                  cell["beta"])
        assert draws[0] == reference


# ---------- 4. TS invariant (issue 428 pin) ----------------------------------------

class TestTSInvariant:
    def test_sampling_frequencies_match_decayed_posterior(self, tmp_path):
        """The TS invariant: argmax-sampling frequencies across cells
        match the decayed posteriors' probabilities. Validated against an
        INDEPENDENT direct-posterior Monte Carlo (never against the
        view's own sampler)."""
        outcomes_a = [1] * 6 + [0] * 4   # Beta(7, 5) after priors
        outcomes_b = [1] * 4 + [0] * 6   # Beta(5, 7) after priors
        _seed_cell(tmp_path, "s", "arm-a", outcomes_a, gamma=1.0)
        _seed_cell(tmp_path, "s", "arm-b", outcomes_b, gamma=1.0)
        view = rp.fold(tmp_path)

        n_draws = 20000
        rng = random.Random(7)
        via_view = sum(
            1 for _ in range(n_draws)
            if view.sample(rng)[0] >= view.sample(rng)[1])
        # Independent path: direct betavariate on the same decayed counts.
        rng_direct = random.Random(7)
        ca, cb = view.cell("s", "arm-a"), view.cell("s", "arm-b")
        direct = sum(
            1 for _ in range(n_draws)
            if rng_direct.betavariate(ca["alpha"], ca["beta"])
            >= rng_direct.betavariate(cb["alpha"], cb["beta"]))
        assert abs(via_view - direct) / n_draws < 0.02

    def test_samples_come_from_the_decayed_not_raw_counts(self, tmp_path):
        """Construct a stream where decayed ≠ raw: a run of early fails
        then equal passes. Under γ = 0.8 the sampled mean must track the
        DECAYED posterior mean, not the raw-count mean."""
        outcomes = [0] * 30 + [1] * 30
        _seed_cell(tmp_path, "s", "a", outcomes, gamma=0.8)
        view = rp.fold(tmp_path)
        cell = view.cell("s", "a")
        raw_alpha = 1.0 + 30.0
        raw_beta = 1.0 + 30.0
        raw_mean = raw_alpha / (raw_alpha + raw_beta)
        assert cell["mean"] > raw_mean + 0.1  # decay actually moved it
        rng = random.Random(23)
        draws = [view.sample(rng)[0] for _ in range(20000)]
        sample_mean = sum(draws) / len(draws)
        assert sample_mean == pytest.approx(cell["mean"], abs=0.01)
        assert sample_mean > raw_mean + 0.05


# ---------- 5. self-heal (issue 428 pin) --------------------------------------------

class TestSelfHeal:
    MISATTRIBUTED = [1] * 30            # injected early misattribution
    # The truth arrives. Length is chosen so DILUTION alone cannot explain
    # recovery: at 40 contradicting obs the γ = 1 control still carries the
    # lie at mean 31/72 ≈ 0.43, while γ < 1 has DECAYED it away.
    CONTRADICTING = [0] * 40

    def test_early_misattribution_decays_out_under_gamma(self, tmp_path):
        ws_heal = tmp_path / "heal"
        ws_stuck = tmp_path / "stuck"
        stream = self.MISATTRIBUTED + self.CONTRADICTING
        _seed_cell(ws_heal, "s", "a", stream, gamma=0.9)
        _seed_cell(ws_stuck, "s", "a", stream, gamma=1.0)
        healed = rp.fold(ws_heal).cell("s", "a")["mean"]
        stuck = rp.fold(ws_stuck).cell("s", "a")["mean"]
        # The γ < 1 posterior RECOVERED toward the true rate (0.0 here);
        # the γ = 1 control is still dominated by the fake passes.
        assert healed < 0.25
        assert stuck > 0.30
        assert healed < stuck - 0.08

    def test_recovery_is_progressive_mid_contradiction(self, tmp_path):
        """Mid-contradiction checkpoint (20 obs in): recovery is underway
        well before the stream ends — decayed evidence is already
        minority-weight while the γ = 1 control still trusts the lie
        (31/52 ≈ 0.60)."""
        stream = self.MISATTRIBUTED + [0] * 20
        ws_heal = tmp_path / "heal"
        ws_stuck = tmp_path / "stuck"
        _seed_cell(ws_heal, "s", "a", stream, gamma=0.9)
        _seed_cell(ws_stuck, "s", "a", stream, gamma=1.0)
        assert rp.fold(ws_heal).cell("s", "a")["mean"] < 0.35
        assert rp.fold(ws_stuck).cell("s", "a")["mean"] > 0.45

    def test_adaptive_schedule_self_heals_too(self, tmp_path):
        """The outcome-adaptive schedule must also recover: a bad stretch
        (the misattribution's consequences) holds γ near the floor =
        strong forgetting precisely while wounded."""
        outcomes = self.MISATTRIBUTED + self.CONTRADICTING
        _seed_cell(tmp_path, "s", "a", outcomes,
                   gamma=None if False else 1.0)  # raw counts recorded at γ=1
        sched = rp.OutcomeAdaptiveGamma(gamma_floor=0.8, ema_lambda=0.9)
        view = rp.fold(tmp_path, schedule=sched)
        healed = view.cell("s", "a")["mean"]
        assert healed < 0.25


# ---------- 6. γ schedules ------------------------------------------------------

class TestSchedules:
    def test_gamma_constant_is_constant(self):
        sched = rp.gamma_constant(0.95)
        assert [sched.next_gamma(1) for _ in range(5)] == [0.95] * 5

    def test_gamma_constant_domain_enforced(self):
        for bad in (0, -1, 1.5, float("nan")):
            with pytest.raises(ValueError):
                rp.gamma_constant(bad)
        assert rp.gamma_constant(1.0).gamma() == 1.0

    def test_adaptive_poor_outcomes_hold_gamma_near_floor(self):
        """Owner semantics: poor recent outcomes → γ grows slowly (stays
        near the floor = strong forgetting → self-heal capacity)."""
        sched = rp.OutcomeAdaptiveGamma(gamma_floor=0.8, ema_lambda=0.9)
        first = sched.next_gamma(0)
        assert first == pytest.approx(0.9)  # m0 = 0.5 → γ0 = 0.8+0.2·0.5
        gammas = [sched.next_gamma(0) for _ in range(40)]
        assert all(g >= 0.8 for g in gammas)          # floor respected
        assert all(g2 <= g1 for g1, g2 in zip(gammas, gammas[1:]))
        assert gammas[-1] < 0.81                       # pinned near floor

    def test_adaptive_improving_outcomes_anneal_to_one(self):
        sched = rp.OutcomeAdaptiveGamma(gamma_floor=0.8, ema_lambda=0.9)
        [sched.next_gamma(0) for _ in range(10)]
        gammas = [sched.next_gamma(1) for _ in range(60)]
        assert all(g2 >= g1 for g1, g2 in zip(gammas, gammas[1:]))
        assert gammas[-1] > 0.99                       # γ → 1 when improving

    def test_adaptive_is_deterministic_and_isolated(self):
        """Two fresh schedules on the same stream produce identical γ
        sequences (no hidden global state), and one schedule's state
        never leaks into another."""
        def run():
            sched = rp.OutcomeAdaptiveGamma(gamma_floor=0.8, ema_lambda=0.9)
            return [sched.next_gamma(o) for o in (1, 0, 0, 1, 1, 0)]
        seq1, seq2 = run(), run()
        assert seq1 == seq2
        assert len(set(map(_fhex, seq1))) == len(seq1)

    def test_adaptive_domain_enforced(self):
        for floor, lam in ((0, 0.9), (-0.1, 0.9), (1.0, 0.9), (0.8, 0),
                           (0.8, 1), (0.8, 1.5), (float("nan"), 0.9)):
            with pytest.raises(ValueError):
                rp.OutcomeAdaptiveGamma(gamma_floor=floor, ema_lambda=lam)

    def test_adaptive_fold_replays_against_recorded_unit_gamma(self, tmp_path):
        """A store recorded at γ = 1 re-folded adaptively produces a
        DIFFERENT, wider-then-tightening posterior — the counterfactual
        calibration face is live through fold()."""
        _seed_cell(tmp_path, "s", "a", [0] * 20 + [1] * 20, gamma=1.0)
        adaptive = rp.fold(
            tmp_path,
            schedule=rp.OutcomeAdaptiveGamma(gamma_floor=0.8,
                                             ema_lambda=0.9)).cell("s", "a")
        unit = rp.fold(tmp_path).cell("s", "a")
        assert adaptive["n_effective"] < unit["n_effective"]


# ---------- 7. defaults ship as EX-2-cited constants ---------------------------

class TestDefaults:
    def test_named_constants_exist_and_are_in_domain(self):
        for name in ("PRIOR_ALPHA_DEFAULT", "PRIOR_BETA_DEFAULT",
                     "GAMMA_FLOOR_DEFAULT", "ADAPTIVE_EMA_LAMBDA_DEFAULT"):
            assert hasattr(rp, name), name
        assert 0.0 < rp.GAMMA_FLOOR_DEFAULT < 1.0
        assert 0.0 < rp.ADAPTIVE_EMA_LAMBDA_DEFAULT < 1.0
        assert rp.PRIOR_ALPHA_DEFAULT > 0.0
        assert rp.PRIOR_BETA_DEFAULT > 0.0

    def test_default_schedule_is_the_outcome_adaptive_one(self):
        sched = rp.default_schedule()
        assert isinstance(sched, rp.OutcomeAdaptiveGamma)
        assert sched.gamma_floor == rp.GAMMA_FLOOR_DEFAULT
        assert sched.ema_lambda == rp.ADAPTIVE_EMA_LAMBDA_DEFAULT

    def test_constants_cite_ex2_calibration(self):
        """The free-parameter discipline: defaults cite EX-2, not vibes —
        the module docstring + constant comments must carry the citation."""
        source = Path(rp.__file__).read_text(encoding="utf-8")
        assert "EX-2" in source
        assert "ex2-gamma-calibration" in source

    def test_shipped_write_default_folds_decayed(self, tmp_path):
        """DTS everywhere, day one (owner ruling 2026-09-29): rows written
        at the default γ (no schedule decision threaded) fold to a DECAYED
        posterior under the default read — the γ = 1 no-forgetting write
        is no longer a default anywhere. Control: the same stream recorded
        at explicit γ = 1 folds exact (the calibration face)."""
        outcomes = [1, 0, 1, 1, 0] * 4
        for out in outcomes:
            assert rp.record(tmp_path, "s", "a", out, ts=TS)["appended"]
        decayed = rp.fold(tmp_path).cell("s", "a")
        assert decayed["n_effective"] < len(outcomes)
        unit_ws = tmp_path / "unit-control"
        for out in outcomes:
            rp.record(unit_ws, "s", "a", out, gamma=1.0, ts=TS)
        exact = rp.fold(unit_ws).cell("s", "a")
        assert exact["n_effective"] == float(len(outcomes))
        assert decayed["width"] > exact["width"]
