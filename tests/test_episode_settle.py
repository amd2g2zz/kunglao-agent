# -*- coding: utf-8 -*-
"""tests/test_episode_settle.py — the learning fuel pipe (terminal wire).

The unified model's three organs — settlement (rlvr.reward), the A1
reward signal, and the episode pool — exist but nothing chains them at
a workspace's TERMINAL. This face is that chain: mission terminal ->
settle pending rollouts -> build ONE episode document from the
workspace's own state (dispatch ledger commits, claim-register outcome,
cost events) -> stamp the A1 reward -> land it through the pool's
WRITE gate -> refresh the derived views.

Faces pinned on a REAL fixture workspace (stamped claims, dispatch
ledger rows, cost events):

  (a) TERMINAL SETTLE — a terminal register + pending rollout rows
      settle into ONE episode file, reward-stamped, cost-honest;
  (b) IDEMPOTENT — a second settle writes nothing;
  (c) NON-TERMINAL REFUSAL — OPEN claims refuse loudly;
  (d) DERIVED VIEWS REFRESH — the pool indexer's value-table face sees
      the new episode;
  (e) REWARD STAMPED — the reward block is the A1 face's own output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import episode_settle as es  # noqa: E402
from rlvr import commit_semantics  # noqa: E402
from rlvr import meta_policy  # noqa: E402
from rlvr import reward_signal  # noqa: E402
from rlvr import timeout_triage as tt  # noqa: E402


def _mk_ws(tmp_path: Path, *, terminal: bool = True) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    claims = {
        "claims": [
            {"id": "C-001", "status": "PROVEN", "title": "packaging"},
            {"id": "C-002", "status": "PROVEN", "title": "control points"},
            {"id": "C-003", "status": "PROVEN" if terminal else "OPEN",
             "title": "trainer"},
        ]
    }
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    runs = ws / "runs"
    runs.mkdir()
    rows = [
        {"schema": "rollout-ledger/1",
         "rollout_id": "mainline_decision/t1", "kind": "mainline_decision",
         "ts": "t1", "signals": [], "reward": None},
        {"schema": "rollout-ledger/1",
         "rollout_id": "mainline_decision/t2", "kind": "mainline_decision",
         "ts": "t2", "signals": [], "reward": None},
    ]
    (runs / "rollout-ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (ws / "cost_events.jsonl").write_text(
        '{"amount": 0.4}\n{"amount": 0.25}\n', encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq1\n  q: produce the trainer\n",
        encoding="utf-8")
    return ws


class TestTerminalSettle:
    def test_terminal_workspace_settles_one_rewarded_episode(self,
                                                              tmp_path):
        ws = _mk_ws(tmp_path)
        out = es.settle_mission(ws)
        assert out["episodes_written"] == 1
        eps = list(es.episode_pool.list_episodes(ws))
        assert len(eps) == 1, "one mission = one episode"
        doc = yaml.safe_load(eps[0].read_text(encoding="utf-8"))
        assert doc["outcome"]["status"] == "completed"
        assert isinstance(doc["reward"], float)
        assert doc["cost"]["spend_usd"] == pytest.approx(0.65)

    def test_second_settle_is_idempotent(self, tmp_path):
        ws = _mk_ws(tmp_path)
        es.settle_mission(ws)
        out2 = es.settle_mission(ws)
        assert out2["episodes_written"] == 0
        assert len(list(es.episode_pool.list_episodes(ws))) == 1

    def test_open_claims_refuse_loudly(self, tmp_path):
        ws = _mk_ws(tmp_path, terminal=False)
        with pytest.raises(es.MissionNotTerminal):
            es.settle_mission(ws)

    def test_value_table_sees_the_episode(self, tmp_path):
        ws = _mk_ws(tmp_path)
        es.settle_mission(ws)
        vt = es.pool_indexer.value_table(ws)
        assert vt, "the derived value-table face must see the episode"


    def test_reward_is_stamped_not_placeholder(self, tmp_path):
        ws = _mk_ws(tmp_path)
        es.settle_mission(ws)
        ep = next(iter(es.episode_pool.list_episodes(ws)))
        doc = yaml.safe_load(ep.read_text(encoding="utf-8"))
        assert doc.get("reward") is not None
        assert "reward_block" in doc


# ------------------------------------------------- P2 settlement card pins
# The card's own pins: the trust-gate fix, the timeout triage, and the
# Φ step-reward distribution fixture (the calibration gate).

def _hyp(hid: str, claim: str) -> dict:
    return {"id": hid, "claim": claim,
            "kill_test": f"an experiment that flips {hid}"}


def _failed_doc(*, attribution: str = "the static lane lacked a "
                "disassembler; the claim needed the dynamic trace") -> dict:
    """A failed-but-verified episode: the negative sample the old trust
    gate could never land."""
    return {
        "schema": "episode/1",
        "id": "mission-C-009",
        "claim": "C-009",
        "created": "2026-10-29T00:00:00Z",
        "updated": "2026-10-29T00:00:00Z",
        "context_features": ["register:negative"],
        "commits": [{"seq": 1, "action": "verify",
                     "summary": "attempted the dynamic trace lane"}],
        "outcome": {"status": "failed", "verified": True,
                    "evidence_ref": ""},
        "cost": {"tokens": 0, "seconds": 0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": [],
        "milestones": [],
        "attribution": attribution,
    }


def _failing_record(ws, claim: str, word: str = "refuted") -> None:
    """A real (or mirror) failing verification record for the claim at
    canonical position 0."""
    p = ws / "runs" / f"verification-{claim}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"verdict: {word}\nclaim: {claim}\n", encoding="utf-8")


class TestTrustGateFix:
    def test_failed_verified_attribution_admits(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _failing_record(ws, "C-009")
        path = es.episode_pool.write_episode(ws, _failed_doc())
        assert path.is_file(), "the negative sample lands (A4 fuel)"
        doc, _body = es.episode_schema.read_episode_file(path)
        assert doc["outcome"]["status"] == "failed"

    def test_unattributed_failure_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(es.episode_pool.WriteRefused):
            es.episode_pool.write_episode(ws, _failed_doc(attribution=""))

    def test_unverified_failure_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        doc = _failed_doc()
        doc["outcome"]["verified"] = False
        with pytest.raises(es.episode_pool.WriteRefused):
            es.episode_pool.write_episode(ws, doc)

    def test_forged_failure_without_surface_refuses(self, tmp_path):
        ws = _mk_ws(tmp_path)
        with pytest.raises(es.episode_pool.WriteRefused,
                           match="verification record"):
            es.episode_pool.write_episode(ws, _failed_doc())

    def test_failure_binds_to_a_real_record_any_polarity(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _failing_record(ws, "C-009", word="verified")
        path = es.episode_pool.write_episode(ws, _failed_doc())
        assert path.is_file(), "a resolved real record binds the failure"

    def test_real_failing_record_blocks_the_mirror(self, tmp_path):
        """A real verdict at a later canonical position must NOT be
        shadowed by a position-0 mirror (the decisive-order attack)."""
        ws = _mk_ws(tmp_path)
        note = ws / "runs" / "C-003-verify-note.md"
        note.write_text("verdict: refuted\n", encoding="utf-8")
        es.settle_mission(ws)
        assert not (ws / "runs" / "verification-C-003.md").exists()
        from verifier_integrity import resolve_verification  # noqa: E402
        passed, word, _detail = resolve_verification(ws, "C-003", "")
        assert passed is False and word == "refuted"

    def test_failed_mission_settles_through_the_mirror(self, tmp_path):
        ws = _mk_ws(tmp_path)
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8"))
        reg["claims"][2]["status"] = "NEGATIVE"
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump(reg), encoding="utf-8")
        out = es.settle_mission(ws)
        assert out["episodes_written"] == 1
        eps = list(es.episode_pool.list_episodes(ws))
        assert len(eps) == 1
        mirror = ws / "runs" / "verification-C-003.md"
        assert mirror.is_file(), "the failing claim rides the mirror"
        assert "verdict: refuted" in mirror.read_text(encoding="utf-8")
        doc, _body = es.episode_schema.read_episode_file(eps[0])
        assert doc["outcome"]["status"] == "failed"
        assert str(doc.get("claim")) == "C-003"
        assert str(doc.get("attribution") or "").strip()
        assert es.settle_mission(ws)["episodes_written"] == 0


class TestTimeoutTriage:
    ENVELOPE = {"action": "envelope_timeout",
                "detail": {"tier": 2, "over": [{"dim": "wall_s"}]}}

    def test_granularity_fault_lands_sizing_never_method(self):
        out = tt.classify_timeout([{"id": "ck1", "status": "open"}],
                                  dict(self.ENVELOPE), [])
        assert out["verdict"] == "granularity_fault"
        assert out["memory_landing"] == "sizing_record"
        assert out["method_memory_negative"] is False
        assert out["memory_landing"] != "method_memory"

    def test_envelope_too_tight_lands_pricing_only(self):
        out = tt.classify_timeout(
            [{"id": "ck1", "status": "closed"},
             {"id": "ck2", "status": "open"}],
            {"kind": "timeout"}, ["evidence/trace.log"])
        assert out["verdict"] == "envelope_too_tight"
        assert out["memory_landing"] == "pricing_update"
        assert out["method_memory_negative"] is False

    def test_method_fail_is_the_only_method_memory_negative(self):
        out = tt.classify_timeout([{"id": "ck1", "status": "open"}],
                                  {"timeout": True}, ["facts/F001.md"])
        assert out["verdict"] == "method_fail"
        assert out["memory_landing"] == "method_memory"
        assert out["method_memory_negative"] is True

    def test_non_timeout_refuses_loudly(self):
        with pytest.raises(ValueError):
            tt.classify_timeout([], {"action": "worker_return"}, [])


class TestPhiStepRewardDistribution:
    def test_gain_distribution_is_sane(self):
        """THE calibration gate (P2): the Φ gain distribution over
        ~10 synthetic step pairs must show active contraction > 0,
        no-contraction == 0, and refutation gain >= confirmation gain —
        the constants (PHI_KILL/PHI_CONFIRM) are sane iff this holds."""
        hyps = [_hyp("H1", "the family is md5"),
                _hyp("H2", "the primitive is poisoned"),
                _hyp("H3", "the composition swaps padding")]
        pairs_refute = [
            "H1 dies: the constant set matches sha256, not md5",
            "H2 is refuted: the known-answer test passes unmutated",
            "H1 and H2 are refuted; H3 survives on the replay evidence",
        ]
        gains_refute = [reward_signal.phi_contraction_gain(hyps, c)
                        for c in pairs_refute]
        pairs_confirm = [
            "H1 survives: the digest matches the mutated md5",
            "H1 and H2 survive: both KATs pass",
            "H3 holds: the padding order replays the capture",
            "H2 holds: the mutated round function reproduces the KAT",
        ]
        gains_confirm = [reward_signal.phi_contraction_gain(hyps, c)
                         for c in pairs_confirm]
        gains_none = [
            reward_signal.phi_contraction_gain(
                hyps, "the weather was pleasant during the run"),
            reward_signal.phi_contraction_gain([], "H1 dies"),
            reward_signal.phi_contraction_gain(hyps, ""),
        ]
        assert len(gains_refute) + len(gains_confirm) + len(gains_none) >= 10
        assert all(0.0 < g <= 1.0 for g in gains_refute), gains_refute
        assert all(0.0 < g <= 1.0 for g in gains_confirm), gains_confirm
        assert gains_none == [0.0, 0.0, 0.0], gains_none
        assert gains_refute[0] > gains_confirm[0], \
            "symmetric 1-vs-1: refutation must outweigh confirmation"
        assert gains_refute[2] > gains_confirm[1]

    def test_step_reward_zero_gate_and_cost_bill(self):
        hyps = [_hyp("H1", "the family is md5"),
                _hyp("H2", "the primitive is poisoned"),
                _hyp("H3", "the composition swaps padding")]
        kill_one = "H1 dies: the constant set matches sha256, not md5"
        assert reward_signal.step_reward(hyps, kill_one, True, True,
                                         0, 0) == pytest.approx(1 / 3)
        assert reward_signal.step_reward(hyps, kill_one, False, True,
                                         0, 0) == 0.0
        assert reward_signal.step_reward(hyps, kill_one, True, False,
                                         0, 0) == 0.0
        theater = ("the run continued; nothing about the hypotheses "
                   "was decided today")
        assert reward_signal.step_reward(hyps, theater, True, True,
                                         0, 0) == 0.0
        assert reward_signal.step_reward(hyps, kill_one, True, True,
                                         5000, 0) == pytest.approx(
            1 / 3 - 0.5)
        assert reward_signal.step_reward(hyps, kill_one, True, True,
                                         20000, 3600) < 0


class TestFloatRewardConsumers:
    def test_surprise_check_survives_float_reward_pools(self, tmp_path):
        """The bare-float reward shape (RED-pinned) must not crash the
        pool's later consumers."""
        ws = _mk_ws(tmp_path)
        es.settle_mission(ws)  # the float-reward mission episode lands
        _failing_record(ws, "C-777")
        other = _failed_doc()
        other["claim"] = "C-777"
        other["id"] = "mission-C-777"
        other["context_features"] = ["register:proven"]
        other["commits"] = [{"seq": 1, "action": "switch",
                             "summary": "same cell as the mission"}]
        other["reward"] = 1.0
        es.episode_pool.write_episode(ws, other)
        settled_doc, _body = es.episode_schema.read_episode_file(
            next(iter(es.episode_pool.list_episodes(ws))))
        out = commit_semantics.surprise_check(ws, settled_doc)
        assert out["n"] == 1
        assert out["expected_mean_reward"] == pytest.approx(1.0)

    def test_utility_chain_reads_the_float_reward(self, tmp_path):
        ws = _mk_ws(tmp_path)
        es.settle_mission(ws)
        doc, _body = es.episode_schema.read_episode_file(
            next(iter(es.episode_pool.list_episodes(ws))))
        out = meta_policy.utility_chain(doc)
        assert out["improved"] is True
