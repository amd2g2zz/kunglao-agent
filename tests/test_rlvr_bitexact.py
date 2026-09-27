# -*- coding: utf-8 -*-
"""tests/test_rlvr_bitexact.py — the settlement determinism wall (issue 420).

Phase 1 of the RLVR unification froze the CURRENT numerical outputs of the
RLVR statistical surface as golden pins; the Phase-2 numpy migration must
reproduce them BIT-EXACTLY. A pin failure is a STOP, never a tolerance
tweak; replacing a golden requires an owner ruling on a new sealed segment
(issue #420 constraint section). Pins are written against the hand-rolled
implementations and PASS on them.

Pinned categories (issue 420 Phase 1 item 3):
  1. Beta prior means — compute_priors over a synthetic multi-source
     workspace pair (case bank + posterior ledger + settled rollout rows +
     tier scalars): aggregate alpha/beta/mean plus the per-source
     decomposition and the pooled Normal-Gamma scalar posterior.
  2. Normal-Gamma pooled parameters — the exact-recovery pattern:
     merge_normal_gamma_posts of per-workspace posteriors vs a direct
     update over all observations, pinned independently (they differ by
     1 ulp today — the pins freeze exactly that structure).
  3. Settled receipts — a settled reward receipt (band / rule_id /
     reward / evidence_refs) and a settled tier receipt (tier scalar +
     dimensions) under the repo's versioned rules table.
  4. Continuity window verdicts — the (alive, detail) pairs of
     evaluate_tick_continuity for healthy / stalled / stale / single-tick
     histories. NOTE: the detail strings are pinned verbatim; if a
     landed change rewords them, re-minting the pins is a merge-sync
     decision recorded in the PR — never a silent edit.

Float encoding: every pinned float is `float.hex()` — exact,
repr-stable, interpreter-independent. Fixtures are SYNTHETIC (privacy
rule) and rebuilt per test run; only numeric/doc content is pinned,
never tmp paths.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import case_bank as cb  # noqa: E402
import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402
import scalar_settlement as ss  # noqa: E402
from posteriors import CasePosterior, PosteriorLedger  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"

_TS = "2026-09-20T00:00:00Z"
_AMEND_TS = "2026-09-20T00:05:00Z"


def _fhex(value) -> str:
    """The pinned encoding of one float: exact hex (never approx)."""
    return float(value).hex()


def _assert_hex(label: str, value, golden_hex: str) -> None:
    assert _fhex(value) == golden_hex, (
        f"BIT-EXACT PIN FAILED: {label}: got {float(value).hex()} "
        f"({value!r}), golden {golden_hex} — settlement determinism wall "
        f"(issue 420): STOP, do not loosen; re-mint needs an owner ruling")


# ---------- shared synthetic fixture (deterministic, no clock/rng) ----------

def _settle(ws: Path, rid: str, kind: str, anchor: str, signals: list,
            settlement: dict) -> None:
    rl.record(ws, kind=kind, anchor=anchor, signals=signals, ts=_TS)
    res = rl.settle(ws, rid, settlement)
    assert res.get("appended"), res


def _seed_ws1(ws: Path) -> None:
    """Bank 2 POSITIVE + 1 NEGATIVE, one posterior case, one GOLD + one
    SILVER settled task rollout."""
    ws.mkdir(parents=True, exist_ok=True)
    for entry in ({"claim_id": "C-1", "roi_class": "POSITIVE"},
                  {"claim_id": "C-2", "roi_class": "POSITIVE"},
                  {"claim_id": "C-3", "roi_class": "NEGATIVE",
                   "attribution": "wrong primitive assumed"}):
        cb.append(ws, dict(entry, method="device-trace(x)",
                           context_tags=["auth"]))
    led = PosteriorLedger()
    led.cases["case-a"] = CasePosterior("case-a", alpha=3.5, beta=1.25)
    led.save(ws)
    green = {"reward": 1.0, "band": "SETTLED_GREEN",
             "rule_id": "task/oracle-green", "evidence_refs": ["pin"]}
    _settle(ws, "task/C-10", "task", "C-10",
            [{"type": "oracle_verdict", "source": "oracle_runner",
              "value": "pass", "ts": _TS}], green)
    st = rl.fold(ws, "task/C-10")["settlement"]
    _settle(ws, "task/C-10", "task", "C-10", rl.fold(ws, "task/C-10")["signals"],
            dict(st, tier="GOLD", tier_reward=1.0, tier_rule_id="tier/gold",
                 tier_dimensions={}, tier_evidence_refs=["pin"],
                 tier_settled_ts=_AMEND_TS,
                 experience_tuple={"s": {"family": "chain-py", "tier": "l1",
                                         "difficulty": "hard"},
                                   "a": {"arm": "static-first",
                                         "choices": ["x"]},
                                   "r": 1.0}))
    red = {"reward": 0.0, "band": "SETTLED_RED",
           "rule_id": "task/oracle-red", "evidence_refs": ["pin"]}
    _settle(ws, "task/C-11", "task", "C-11",
            [{"type": "oracle_verdict", "source": "oracle_runner",
              "value": "fail", "ts": _TS}], red)
    st11 = rl.fold(ws, "task/C-11")["settlement"]
    _settle(ws, "task/C-11", "task", "C-11", rl.fold(ws, "task/C-11")["signals"],
            dict(st11, tier="SILVER", tier_reward=0.7,
                 tier_rule_id="tier/silver", tier_dimensions={},
                 tier_evidence_refs=["pin"], tier_settled_ts=_AMEND_TS))


def _seed_ws2(ws: Path) -> None:
    """Bank 1 NEGATIVE, one BRONZE settled task rollout."""
    ws.mkdir(parents=True, exist_ok=True)
    cb.append(ws, {"claim_id": "C-4", "roi_class": "NEGATIVE",
                   "attribution": "wrong arm", "method": "m",
                   "context_tags": []})
    green = {"reward": 1.0, "band": "SETTLED_GREEN",
             "rule_id": "task/oracle-green", "evidence_refs": ["pin"]}
    _settle(ws, "task/C-12", "task", "C-12",
            [{"type": "oracle_verdict", "source": "oracle_runner",
              "value": "pass", "ts": _TS}], green)
    st = rl.fold(ws, "task/C-12")["settlement"]
    _settle(ws, "task/C-12", "task", "C-12", rl.fold(ws, "task/C-12")["signals"],
            dict(st, tier="BRONZE", tier_reward=0.4,
                 tier_rule_id="tier/bronze", tier_dimensions={},
                 tier_evidence_refs=["pin"], tier_settled_ts=_AMEND_TS))


# ---------- 1. Beta prior means (compute_priors) ------------------------------

class TestBetaPriorMeans:
    @pytest.fixture(scope="class")
    def prior(self, tmp_path_factory):
        from compute_priors import compute_priors
        ws1 = tmp_path_factory.mktemp("ws1")
        ws2 = tmp_path_factory.mktemp("ws2")
        _seed_ws1(ws1)
        _seed_ws2(ws2)
        return compute_priors([ws1, ws2])

    def test_aggregate_alpha_beta_mean(self, prior):
        assert prior["schema"] == "aggregate-prior/1"
        _assert_hex("aggregate alpha", prior["alpha"],
                    "0x1.e000000000000p+2")  # 7.5
        _assert_hex("aggregate beta", prior["beta"],
                    "0x1.1000000000000p+2")  # 4.25
        _assert_hex("aggregate mean", prior["mean"],
                    "0x1.46cefa8d9df52p-1")  # 0.6382978723404256

    def test_source_decomposition(self, prior):
        src = prior["sources"]
        assert src["case_bank"] == {"alpha": 2, "beta": 2}
        assert src["rollout_ledger"] == {"alpha": 2, "beta": 1}
        _assert_hex("posteriors alpha", src["posteriors"]["alpha"],
                    "0x1.4000000000000p+1")  # 2.5
        _assert_hex("posteriors beta", src["posteriors"]["beta"],
                    "0x1.0000000000000p-2")  # 0.25
        assert src["scalar_ledger"]["n"] == 3
        _assert_hex("scalar mean", src["scalar_ledger"]["mean"],
                    "0x1.6666666666667p-1")  # 0.7000000000000001

    def test_scalar_ledger_pooled_posterior(self, prior):
        post = prior["sources"]["scalar_ledger"]["posterior"]
        assert post["n"] == 3
        _assert_hex("pooled NG mu", post["mu"], "0x1.4cccccccccccdp-1")
        _assert_hex("pooled NG kappa", post["kappa"], "0x1.0000000000000p+2")
        _assert_hex("pooled NG alpha", post["alpha"], "0x1.4000000000000p+1")
        _assert_hex("pooled NG beta", post["beta"], "0x1.1ae147ae147aep+0")
        _assert_hex("pooled NG var", post["var"], "0x1.eb851eb851ebbp-5")

    def test_prior_read_faces(self, tmp_path):
        _seed_ws1(tmp_path / "ws1")
        assert ss.scalar_observations(tmp_path / "ws1") == [1.0, 0.7]
        assert rs.prior_observations(tmp_path / "ws1") == (1, 1)
        tup = ss.tuples(tmp_path / "ws1")
        assert len(tup) == 1
        _assert_hex("experience_tuple r", tup[0]["r"], "0x1.0000000000000p+0")
        assert tup[0]["rollout_id"] == "task/C-10"


# ---------- 2. Normal-Gamma pooled parameters (exact-recovery) ----------------

class TestNormalGammaPooled:
    OBS = [1.0, 0.7, 0.4, 0.4, 0.0, 0.7]

    @pytest.fixture(scope="class")
    def docs(self):
        direct = ss.normal_gamma_update(self.OBS)
        p1 = ss.normal_gamma_update(self.OBS[:2])
        p2 = ss.normal_gamma_update(self.OBS[2:4])
        p3 = ss.normal_gamma_update(self.OBS[4:])
        merged = ss.merge_normal_gamma_posts([p1, p2, p3])
        weak = ss.normal_gamma_update([])
        return direct, merged, p1, weak

    def test_direct_update(self, docs):
        direct, _, _, _ = docs
        assert direct["n"] == 6
        _assert_hex("direct mu", direct["mu"], "0x1.0ea0ea0ea0ea1p-1")
        _assert_hex("direct kappa", direct["kappa"], "0x1.c000000000000p+2")
        _assert_hex("direct alpha", direct["alpha"], "0x1.0000000000000p+2")
        _assert_hex("direct beta", direct["beta"], "0x1.4c118de5ab278p+0")
        _assert_hex("direct var", direct["var"], "0x1.950c83fb72ea7p-4")

    def test_merge_recovers_direct_within_one_ulp_structure(self, docs):
        """The exact-recovery pin: the pooled posterior reproduces the
        direct update BIT-EXACTLY as pinned — today merge lands 1 ulp
        above direct on beta/var, and the pins freeze exactly that."""
        direct, merged, _, _ = docs
        assert merged["n"] == direct["n"] == 6
        for key in ("mu", "kappa", "alpha"):
            assert merged[key] == direct[key], key
        _assert_hex("merged beta", merged["beta"], "0x1.4c118de5ab279p+0")
        _assert_hex("merged var", merged["var"], "0x1.950c83fb72ea8p-4")

    def test_single_workspace_posterior(self, docs):
        _, _, p1, _ = docs
        assert p1["n"] == 2
        _assert_hex("p1 mu", p1["mu"], "0x1.7777777777778p-1")
        _assert_hex("p1 kappa", p1["kappa"], "0x1.8000000000000p+1")
        _assert_hex("p1 alpha", p1["alpha"], "0x1.0000000000000p+1")
        _assert_hex("p1 beta", p1["beta"], "0x1.10369d0369d03p+0")
        _assert_hex("p1 var", p1["var"], "0x1.70a3d70a3d70cp-6")

    def test_weak_prior_is_the_documented_constants(self, docs):
        _, _, _, weak = docs
        assert weak["n"] == 0
        _assert_hex("weak mu", weak["mu"], "0x1.0000000000000p-1")  # 0.5
        _assert_hex("weak kappa", weak["kappa"], "0x1.0000000000000p+0")
        _assert_hex("weak alpha", weak["alpha"], "0x1.0000000000000p+0")
        _assert_hex("weak beta", weak["beta"], "0x1.0000000000000p+0")
        _assert_hex("weak var", weak["var"], "0x0.0p+0")


# ---------- 3. settled receipts ----------------------------------------------

class TestSettledReceipts:
    @pytest.fixture(scope="class")
    def rules_doc(self):
        return rs.load_rules(RULES_PATH)

    def test_reward_receipt_oracle_green(self, rules_doc):
        receipt = rs.classify("task", [
            {"type": "claim_terminal", "source": "convergence_check",
             "value": "PROVEN", "ts": _TS},
            {"type": "oracle_verdict", "source": "oracle_runner",
             "value": "pass", "ts": _TS},
            {"type": "redteam_confirmed", "source": "outcome_capture",
             "value": True, "ts": _TS},
        ], rules_doc)
        assert receipt["band"] == "SETTLED_GREEN"
        assert receipt["rule_id"] == "task/oracle-green"
        assert receipt["evidence_refs"] == [
            "runs/oracle-status.json", "claim-register.yaml",
            'claim_terminal:convergence_check="PROVEN"',
            'oracle_verdict:oracle_runner="pass"']
        _assert_hex("receipt reward", receipt["reward"],
                    "0x1.0000000000000p+0")

    def test_reward_receipt_single_signal_stays_pending(self, rules_doc):
        receipt = rs.classify("task", [
            {"type": "claim_terminal", "source": "convergence_check",
             "value": "OPEN", "ts": _TS},
        ], rules_doc)
        assert receipt == {"reward": 0.0, "band": "NEUTRAL",
                           "rule_id": "task/pending",
                           "evidence_refs": [
                               'claim_terminal:convergence_check="OPEN"']}

    def test_tier_receipt_gold(self, rules_doc):
        receipt = ss.classify_tier([
            {"type": "oracle_verdict", "source": "oracle_runner",
             "value": "pass", "ts": _TS},
            {"type": "unit_difficulty", "source": "unit-manifest",
             "value": "hard", "ts": _TS},
            {"type": "evidence_class", "source": "verify",
             "value": "reproducible", "ts": _TS},
            {"type": "session_cost", "source": "cost", "value": 0.5,
             "ts": _TS},
            {"type": "unit_class", "source": "unit-manifest",
             "value": "cc-default", "ts": _TS},
        ], rules_doc["tier_table"], rules_doc["cost_reference"])
        assert receipt["tier"] == "GOLD"
        assert receipt["tier_rule_id"] == "tier/gold"
        _assert_hex("tier reward", receipt["tier_reward"],
                    "0x1.0000000000000p+0")
        dims = receipt["dimensions"]
        _assert_hex("cost ratio", dims["cost"]["ratio"],
                    "0x1.5555555555555p-2")  # 0.3333333333333333
        _assert_hex("outcome p", dims["outcome"]["p"],
                    "0x1.0000000000000p+0")
        assert receipt["evidence_refs"] == [
            'oracle_verdict:oracle_runner="pass"',
            'unit_difficulty:unit-manifest="hard"',
            'evidence_class:verify="reproducible"',
            'session_cost:cost=0.5',
            'unit_class:unit-manifest="cc-default"']


# ---------- 4. continuity window verdicts --------------------------------------

class TestContinuityVerdicts:
    NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    FMT = "%Y-%m-%dT%H:%M:%SZ"

    def _ticks(self, minutes_ago: list[int]) -> list[str]:
        return [((self.NOW - timedelta(minutes=m)).strftime(self.FMT))
                for m in minutes_ago]

    def _state(self, history):
        return {"interval_min": 5, "tick_history": history}

    def _assert_verdict(self, state, alive_golden, detail_golden):
        from heartbeat import evaluate_tick_continuity
        alive, detail = evaluate_tick_continuity(state, now=self.NOW)
        assert alive is alive_golden
        assert detail == detail_golden

    def test_healthy_cadence_alive(self):
        self._assert_verdict(
            self._state(self._ticks([25, 20, 15, 10, 5, 0])),
            True,
            "continuous ticks OK (6 in window, latest 2026-09-28T12:00:00Z, "
            "cadence <= 10m)")

    def test_mid_life_stall_rejected(self):
        self._assert_verdict(
            self._state(self._ticks([125, 120, 60, 55, 5])),
            False,
            "cadence GAP between adjacent ticks (60 min > 10 min = 2x5m): "
            "2026-09-28T10:00:00Z -> 2026-09-28T11:00:00Z - the cron stalled "
            "mid-life; re-arm with heartbeat_tick.py <ws> or re-register the "
            "/loop")

    def test_stale_history_rejected(self):
        self._assert_verdict(
            self._state(self._ticks([65, 60, 55, 50, 45])),
            False,
            "heartbeat STALE (last tick 45 min ago > 35) - continuous-tick "
            "history present but the loop died")

    def test_single_tick_is_the_blind_spot(self):
        self._assert_verdict(
            self._state(self._ticks([0])),
            False,
            "single tick only (registration-time tick, cron never fired "
            "again) - wait for the SECOND tick (<= 2x interval) or check "
            "the /loop cron is alive; "
            "tick_history=['2026-09-28T12:00:00Z']")

    def test_aged_out_stall_is_surfaced(self):
        """A stall older than the sliding window stops voting but is
        counted in the detail — pinned including the aged-out note. The
        history carries 14 ticks so the ancient pair drops out of the
        last-12 tick-count bound (and is past the 24h age bound)."""
        history = self._ticks([3000, 2995] + list(range(55, -1, -5)))
        self._assert_verdict(
            self._state(history),
            True,
            "continuous ticks OK (12 in window, latest 2026-09-28T12:00:00Z, "
            "cadence <= 10m); window: last 12 ticks (older history excluded: "
            "1 stall(s) aged out)")
