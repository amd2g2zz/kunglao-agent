# -*- coding: utf-8 -*-
"""tests/test_experience_triples_396.py — (s, a, r) triple extraction to
runs/triples.csv + read-only Q report (issue 396, v0.1.6 recording face).

Pins the owner's 2026-09-27 separated-concerns ruling:
  - learning samples = triples (s, a, r); s carries the canonical state
    signature (the 2026-09-27 correction: signature survives, s' column
    REJECTED — no transition column anywhere in the CSV);
  - one row per round with credit (round_credit settlement rows), plus
    episode-grain rows (the episode-settlement experience_tuple) — both grains covered;
  - r = the round-credit / settled scalar ALREADY produced by the episode settlement —
    extraction never re-scores;
  - runs/triples.csv is a REGENERABLE derived view (ledger stays the
    system of record): extraction is deterministic and overwrites;
  - read-only Q report: per-(s_hash, a_arm) empirical mean + count —
    banking visibility, zero behavior.
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import experience_triples as xt  # noqa: E402
import rollout_ledger as rl  # noqa: E402
import scalar_settlement as ss  # noqa: E402
import state_signature as ssig  # noqa: E402

TS = "2026-09-27T00:00:00Z"


def _seed_episode(ws: Path, *, arm="arm-crypto", choices=None,
                  tier="GOLD", reward=1.0) -> str:
    """A settled task rollout carrying the eval-face signals + the episode-settlement
    experience_tuple birth certificate."""
    signals = [
        {"type": "strategy_arm", "source": "eval", "value": arm, "ts": TS},
        {"type": "method_choices", "source": "eval", "value":
            list(choices or []), "ts": TS},
        {"type": "unit_family", "source": "manifest", "value": "kdf",
         "ts": TS},
        {"type": "oracle_verdict", "source": "checker", "value": "pass",
         "ts": TS},
    ]
    rid = rl.record(ws, kind="task", anchor="T-1", signals=signals)
    assert rid.get("appended")
    rid_full = "task/T-1"
    st = {"reward": reward, "band": "SETTLED_GREEN", "rule_id": "r/1",
          "evidence_refs": [], "tier": tier, "tier_reward": reward,
          "tier_rule_id": f"tier/{tier.lower()}",
          "tier_dimensions": {}, "tier_evidence_refs": [],
          "experience_tuple": {
              "s": {"family": "kdf", "tier": "hard", "difficulty": "hard"},
              "a": {"arm": arm, "choices": list(choices or [])},
              "r": reward},
          "tier_settled_ts": TS}
    res = rl.settle(ws, rid_full, st)
    assert res.get("appended")
    return rid_full


def _seed_round(ws: Path, dispatch_id: str, r: float, claim="C-5") -> str:
    """A settled round_credit row (the issue-379 per-dispatch settlement)."""
    signals = [{"type": "round_credit_signal", "source": "scalar_settlement",
                "value": {"credited": int(r), "waste": 0}, "ts": TS}]
    rl.record(ws, kind=ss.KIND_ROUND_CREDIT, anchor=dispatch_id,
              signals=signals, ts=TS)
    st = {"reward": r, "band": ss.BAND_ROUND_CREDIT,
          "rule_id": ss.RULE_ROUND_CREDIT, "evidence_refs": [],
          "credited": ["F001"] if r > 0 else [], "waste": 0.0,
          "round": 1, "untraced": [], "settled_ts": TS}
    res = rl.settle(ws, f"{ss.KIND_ROUND_CREDIT}/{dispatch_id}", st)
    assert res.get("appended")
    return f"{ss.KIND_ROUND_CREDIT}/{dispatch_id}"


def _strategy_row(ws: Path, strategy: str, claim: str) -> None:
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    with (runs / "strategy-log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": TS, "event": "dispatch",
                             "strategy": strategy, "claim": claim,
                             "attempts_at_snapshot": 0}) + "\n")


def _read_csv_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "triples.csv"
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class TestExtract:
    def test_header_byte_pinned(self, tmp_path):
        xt.extract(tmp_path)
        text = (tmp_path / "runs" / "triples.csv").read_text("utf-8")
        assert text.splitlines()[0] == (
            "grain,rollout_id,s_signature,s_hash,a_arm,a_choices,r,"
            "r_source,ts")

    def test_round_and_episode_rows_present(self, tmp_path):
        _seed_episode(tmp_path)
        _seed_round(tmp_path, "C-5", 2.0)
        doc = xt.extract(tmp_path)
        assert doc["rows"] == 2
        rows = _read_csv_rows(tmp_path)
        grains = sorted(r["grain"] for r in rows)
        assert grains == ["episode", "round"]

    def test_round_row_r_from_round_credit_settlement(self, tmp_path):
        _seed_round(tmp_path, "C-5", 2.0)
        xt.extract(tmp_path)
        row = next(r for r in _read_csv_rows(tmp_path)
                   if r["grain"] == "round")
        assert row["rollout_id"] == "round_credit/C-5"
        assert float(row["r"]) == 2.0
        assert row["r_source"] == "round_credit"

    def test_round_row_a_arm_from_strategy_log_claim_join(self, tmp_path):
        _strategy_row(tmp_path, "static-first", "C-5")
        _seed_round(tmp_path, "C-5", 1.0)
        xt.extract(tmp_path)
        row = next(r for r in _read_csv_rows(tmp_path)
                   if r["grain"] == "round")
        assert row["a_arm"] == "static-first"

    def test_episode_row_a_from_experience_tuple_signals(self, tmp_path):
        _seed_episode(tmp_path, arm="arm-replay", choices=["floss", "ghidra"])
        xt.extract(tmp_path)
        row = next(r for r in _read_csv_rows(tmp_path)
                   if r["grain"] == "episode")
        assert row["a_arm"] == "arm-replay"
        assert row["a_choices"] == "floss;ghidra"
        assert float(row["r"]) == 1.0
        assert row["r_source"] == "experience_tuple"

    def test_s_column_is_state_signature(self, tmp_path):
        _seed_round(tmp_path, "C-5", 1.0)
        doc = xt.extract(tmp_path)
        snap = ssig.snapshot(tmp_path)
        assert doc["s_signature"] == ssig.signature_str(snap)
        row = _read_csv_rows(tmp_path)[0]
        assert row["s_signature"] == doc["s_signature"]
        assert row["s_hash"] == ssig.signature_hash(snap)

    def test_no_transition_column_quadruple_rejected(self, tmp_path):
        """The 2026-09-27 owner correction: quadruple REJECTED, the triple
        suffices. The CSV must not grow an s' / s_next column."""
        _seed_round(tmp_path, "C-5", 1.0)
        xt.extract(tmp_path)
        header = (tmp_path / "runs" / "triples.csv").read_text(
            "utf-8").splitlines()[0]
        for needle in ("s_next", "s'", "sprime", "s_t1"):
            assert needle not in header.lower()

    def test_regenerable_overwrite_deterministic(self, tmp_path):
        _seed_round(tmp_path, "C-5", 1.0)
        first = xt.extract(tmp_path)
        text1 = (tmp_path / "runs" / "triples.csv").read_text("utf-8")
        # same inputs -> byte-identical regeneration (derived view)
        second = xt.extract(tmp_path)
        text2 = (tmp_path / "runs" / "triples.csv").read_text("utf-8")
        assert text1 == text2
        assert first["rows"] == second["rows"]

    def test_empty_ledger_header_only_csv(self, tmp_path):
        doc = xt.extract(tmp_path)
        assert doc["rows"] == 0
        lines = (tmp_path / "runs" / "triples.csv").read_text(
            "utf-8").splitlines()
        assert len(lines) == 1  # header only

    def test_unsettled_rollouts_absent(self, tmp_path):
        rl.record(tmp_path, kind="task", anchor="T-x", signals=[
            {"type": "strategy_arm", "source": "eval", "value": "a",
             "ts": TS}])
        assert xt.extract(tmp_path)["rows"] == 0

    def test_episode_row_without_tuple_falls_back_to_scalar(self, tmp_path):
        signals = [{"type": "strategy_arm", "source": "eval",
                    "value": "arm-x", "ts": TS}]
        rl.record(tmp_path, kind="task", anchor="T-2", signals=signals)
        rl.settle(tmp_path, "task/T-2", {
            "reward": 0.7, "band": "SETTLED_GREEN", "rule_id": "r/1",
            "evidence_refs": [], "tier": "SILVER", "tier_reward": 0.7,
            "tier_rule_id": "tier/silver", "tier_dimensions": {},
            "tier_evidence_refs": [], "tier_settled_ts": TS})
        xt.extract(tmp_path)
        row = next(r for r in _read_csv_rows(tmp_path)
                   if r["grain"] == "episode")
        assert float(row["r"]) == 0.7
        assert row["r_source"] == "tier_scalar"
        assert row["a_arm"] == "arm-x"


class TestQReport:
    def test_per_cell_mean_and_count(self, tmp_path):
        _seed_round(tmp_path, "C-1", 1.0)
        _seed_round(tmp_path, "C-2", 3.0)
        _seed_episode(tmp_path)
        xt.extract(tmp_path)
        doc = xt.q_report(tmp_path)
        assert doc["schema"] == "q-report/1"
        assert doc["rows"] == 3
        cell = next(c for c in doc["cells"] if c["a_arm"] == "arm-crypto")
        assert cell["n"] == 1
        assert cell["mean_r"] == pytest.approx(1.0)

    def test_cells_sorted_deterministic(self, tmp_path):
        _seed_round(tmp_path, "C-1", 1.0)
        _seed_round(tmp_path, "C-2", 3.0)
        xt.extract(tmp_path)
        cells = xt.q_report(tmp_path)["cells"]
        keys = [(c["s_hash"], c["a_arm"]) for c in cells]
        assert keys == sorted(keys)

    def test_read_only_never_writes(self, tmp_path):
        _seed_round(tmp_path, "C-1", 1.0)
        xt.extract(tmp_path)
        before = (tmp_path / "runs" / "triples.csv").read_bytes()
        xt.q_report(tmp_path)
        after = (tmp_path / "runs" / "triples.csv").read_bytes()
        assert before == after

    def test_cold_start_empty_cells(self, tmp_path):
        doc = xt.q_report(tmp_path)
        assert doc["cells"] == []
        assert doc["rows"] == 0

    def test_q_derives_from_v_expectation_family_doc(self, tmp_path):
        """Same (s_hash, a_arm) cell with two rewards: the report's mean is
        the per-cell empirical mean — the issue-386 Q-table arithmetic, no
        learning (V(s) = expectation of Q over actions is the same family)."""
        _seed_round(tmp_path, "C-1", 1.0)
        _seed_round(tmp_path, "C-2", 3.0)
        # both rounds share one signature (same ws, no other face moved):
        # force identical cells by checking they landed in the same cell
        xt.extract(tmp_path)
        doc = xt.q_report(tmp_path)
        round_cells = [c for c in doc["cells"]
                       if c["a_arm"] == ""]  # round rows: no strategy log
        assert len(round_cells) == 1
        assert round_cells[0]["n"] == 2
        assert round_cells[0]["mean_r"] == pytest.approx(2.0)
