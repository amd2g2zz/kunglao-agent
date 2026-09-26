# -*- coding: utf-8 -*-
"""tests/test_state_signature_396.py — canonical state signature + V anchor
(issue 396, v0.1.6 recording face).

Pins the owner's 2026-09-27 state-signature spec:
  - canonical DISCRETIZED encoding over EXISTING faces only:
    fact count (bucketed) from facts/F*.md frontmatter, claim states
    pattern from claim-register.yaml, budget fraction from the cost
    telemetry (tuition_curve.cost_state), chain progress k/N from the
    probe/oracle/mission-ledger faces, phase from the issue-461 hook-state
    lifecycle face;
  - sides field RESERVED (empty) — v0.2 side-trajectory tree;
  - canonical signature string + short hash (the issue-386 Q-table key);
  - V(s) deterministic progress anchor: pure function over the
    signature, no learning, no data files, present-dim renormalization;
  - mainline situation snapshot stream (append-only, fail-open).
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import state_signature as ssig  # noqa: E402


def _fact(ws: Path, fid: str, status: str, creator: str = "d-1") -> Path:
    p = ws / "facts" / f"{fid}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\nid: {fid}\nstatus: {status}\ncreator: {creator}\n"
        f"---\n\n# {fid}\nbody\n", encoding="utf-8")
    return p


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")


def _cost(ws: Path, amounts: list[float]) -> None:
    p = ws / "cost_events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for a in amounts:
            fh.write(json.dumps({"amount": a}) + "\n")


# ---------- fact face ----------

class TestFactFace:
    def test_counts_and_terminal_verified(self, tmp_path):
        _fact(tmp_path, "F001", "PROVEN")
        _fact(tmp_path, "F002", "VERIFIED")
        _fact(tmp_path, "F003", "OPEN")
        face = ssig.fact_face(tmp_path)
        assert face == {"count": 3, "verified": 2}

    def test_empty_workspace_zero(self, tmp_path):
        assert ssig.fact_face(tmp_path) == {"count": 0, "verified": 0}

    def test_unreadable_frontmatter_skipped(self, tmp_path):
        _fact(tmp_path, "F001", "PROVEN")
        (tmp_path / "facts" / "F002.md").write_text(
            "not frontmatter at all", encoding="utf-8")
        face = ssig.fact_face(tmp_path)
        assert face["count"] >= 1  # tolerant: never raises, counts what reads


class TestFactBucket:
    def test_bucket_edges_pinned(self):
        assert ssig.fact_bucket(0) == 0
        assert ssig.fact_bucket(1) == 1
        assert ssig.fact_bucket(4) == 1
        assert ssig.fact_bucket(5) == 2
        assert ssig.fact_bucket(9) == 2
        assert ssig.fact_bucket(10) == 3
        assert ssig.fact_bucket(19) == 3
        assert ssig.fact_bucket(20) == 4
        assert ssig.fact_bucket(49) == 4
        assert ssig.fact_bucket(50) == 5
        assert ssig.fact_bucket(1000) == 5


# ---------- claim pattern ----------

class TestClaimPattern:
    def test_pattern_canonical_sorted_counts(self, tmp_path):
        _register(tmp_path, [
            {"id": "C-1", "status": "OPEN"},
            {"id": "C-2", "status": "PROVEN"},
            {"id": "C-3", "status": "OPEN"},
            {"id": "C-4", "status": "NEGATIVE"},
        ])
        assert ssig.claim_pattern(tmp_path) == "NEGATIVE=1|OPEN=2|PROVEN=1"

    def test_empty_register_empty_pattern(self, tmp_path):
        assert ssig.claim_pattern(tmp_path) == ""

    def test_unreadable_register_is_empty_not_crash(self, tmp_path):
        (tmp_path / "claim-register.yaml").write_text(
            "::: not yaml [", encoding="utf-8")
        assert ssig.claim_pattern(tmp_path) == ""


# ---------- budget fraction ----------

class TestBudgetFraction:
    def test_fraction_from_cost_telemetry(self, tmp_path):
        _cost(tmp_path, [12.5])
        frac = ssig.budget_fraction(tmp_path)
        assert frac == pytest.approx(12.5 / 50.0)

    def test_clamped_at_one(self, tmp_path):
        _cost(tmp_path, [80.0])
        assert ssig.budget_fraction(tmp_path) == 1.0

    def test_no_cost_file_zero(self, tmp_path):
        assert ssig.budget_fraction(tmp_path) == 0.0

    def test_bucket_edges_pinned(self):
        assert ssig.budget_bucket(0.0) == 0
        assert ssig.budget_bucket(0.09) == 0
        assert ssig.budget_bucket(0.10) == 1
        assert ssig.budget_bucket(0.25) == 2
        assert ssig.budget_bucket(0.50) == 3
        assert ssig.budget_bucket(0.75) == 4
        assert ssig.budget_bucket(1.0) == 5
        assert ssig.budget_bucket(1.5) == 5


# ---------- chain progress k/N ----------

class TestChainProgress:
    def test_probe_signals_face_wins(self, tmp_path):
        # last non-null dense_layers value across ledger rows wins
        rl.record(tmp_path, kind="task", anchor="T-a", signals=[
            {"type": "dense_layers", "source": "oracle", "value":
                {"passed": 1, "total": 4}, "ts": "2026-09-27T00:00:00Z"}])
        rl.record(tmp_path, kind="task", anchor="T-b", signals=[
            {"type": "dense_layers", "source": "oracle", "value":
                {"passed": 3, "total": 4}, "ts": "2026-09-27T01:00:00Z"}])
        assert ssig.chain_progress(tmp_path) == (3, 4)

    def test_replay_and_static_probe_faces_aggregate(self, tmp_path):
        rl.record(tmp_path, kind="task", anchor="T-a", signals=[
            {"type": "static_probes", "source": "checker", "value":
                {"passed": 2, "total": 5}, "ts": "2026-09-27T00:00:00Z"},
            {"type": "replay_probes", "source": "checker", "value":
                {"passed": 1, "total": 3}, "ts": "2026-09-27T00:00:00Z"}])
        assert ssig.chain_progress(tmp_path) == (3, 8)

    def test_oracle_status_fallback(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        (runs / "oracle-status.json").write_text(json.dumps({
            "cases": {"c1": {"status": "pass"}, "c2": {"status": "pass"},
                      "c3": {"status": "fail"}}}), encoding="utf-8")
        assert ssig.chain_progress(tmp_path) == (2, 3)

    def test_mission_ledger_history_last_vector(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        (runs / "mission_ledger.yaml").write_text(yaml.safe_dump({
            "mission": {"history": [
                {"oracle_pass": 0, "checks_impl": 2},
                {"oracle_pass": 1, "checks_impl": 3}]}}), encoding="utf-8")
        assert ssig.chain_progress(tmp_path) == (1, 3)

    def test_probe_face_outranks_oracle_and_mission(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        (runs / "oracle-status.json").write_text(json.dumps(
            {"cases": {"c1": {"status": "pass"}}}), encoding="utf-8")
        rl.record(tmp_path, kind="task", anchor="T-a", signals=[
            {"type": "dense_layers", "source": "oracle", "value":
                {"passed": 2, "total": 6}, "ts": "2026-09-27T00:00:00Z"}])
        assert ssig.chain_progress(tmp_path) == (2, 6)

    def test_no_face_none(self, tmp_path):
        assert ssig.chain_progress(tmp_path) is None


# ---------- phase + sides ----------

class TestPhaseAndSides:
    def test_phase_from_hook_state(self, tmp_path):
        (tmp_path / ".hook_state.json").write_text(json.dumps(
            {"phase": "DISPATCH"}), encoding="utf-8")
        assert ssig.phase(tmp_path) == "DISPATCH"

    def test_phase_absent_none(self, tmp_path):
        assert ssig.phase(tmp_path) is None

    def test_sides_reserved_empty(self, tmp_path):
        """v0.2 side-trajectory tree: the field exists, always empty."""
        snap = ssig.snapshot(tmp_path)
        assert snap["sides"] == {}


# ---------- snapshot + canonical signature ----------

class TestSnapshotAndSignature:
    def _full_ws(self, tmp_path: Path) -> Path:
        _fact(tmp_path, "F001", "PROVEN")
        _fact(tmp_path, "F002", "VERIFIED")
        _fact(tmp_path, "F003", "OPEN")
        _fact(tmp_path, "F004", "PROVEN")
        _fact(tmp_path, "F005", "PROVEN")
        _register(tmp_path, [{"id": "C-1", "status": "PROVEN"},
                             {"id": "C-2", "status": "OPEN"}])
        _cost(tmp_path, [10.0])
        (tmp_path / ".hook_state.json").write_text(json.dumps(
            {"phase": "VERIFY"}), encoding="utf-8")
        rl.record(tmp_path, kind="task", anchor="T-a", signals=[
            {"type": "dense_layers", "source": "oracle", "value":
                {"passed": 2, "total": 4}, "ts": "2026-09-27T00:00:00Z"}])
        return tmp_path

    def test_snapshot_document_shape(self, tmp_path):
        snap = ssig.snapshot(self._full_ws(tmp_path))
        assert snap["schema"] == "state-sig/1"
        assert snap["facts"] == {"count": 5, "verified": 4, "bucket": 2}
        assert snap["claims"] == {"pattern": "OPEN=1|PROVEN=1"}
        assert snap["budget"]["fraction"] == pytest.approx(0.2)
        assert snap["budget"]["bucket"] == 1
        assert snap["budget"]["present"] is True
        assert snap["chain"] == {"k": 2, "n": 4}
        assert snap["phase"] == "VERIFY"
        assert snap["sides"] == {}

    def test_signature_str_byte_pinned(self, tmp_path):
        sig = ssig.signature_str(ssig.snapshot(self._full_ws(tmp_path)))
        assert sig == ("state-sig/1|fc=2|fv=4|cp=OPEN=1|PROVEN=1"
                       "|bg=1|ch=2/4|ph=VERIFY|sd=-")

    def test_signature_deterministic_and_order_stable(self, tmp_path):
        ws = self._full_ws(tmp_path)
        s1 = ssig.signature_str(ssig.snapshot(ws))
        _fact(ws, "F006", "PROVEN")  # 6 facts, still bucket 2
        s2 = ssig.signature_str(ssig.snapshot(ws))
        assert s1 != s2  # verified count moved
        assert "fc=2" in s2

    def test_signature_hash_short_stable(self, tmp_path):
        ws = self._full_ws(tmp_path)
        h = ssig.signature_hash(ssig.snapshot(ws))
        assert len(h) == 12
        assert h == ssig.signature_hash(ssig.snapshot(ws))
        assert h != ssig.signature_hash(ssig.snapshot(tmp_path / "bare"))

    def test_cold_workspace_signature(self, tmp_path):
        sig = ssig.signature_str(ssig.snapshot(tmp_path))
        assert sig == "state-sig/1|fc=0|fv=0|cp=-|bg=0|ch=-|ph=-|sd=-"


# ---------- V anchor (deterministic, lookup-only) ----------

class TestVAnchor:
    @staticmethod
    def _snap(*, count=0, verified=0, fraction=0.0, present=True,
              chain=None) -> dict:
        return {"schema": "state-sig/1",
                "facts": {"count": count, "verified": verified,
                          "bucket": ssig.fact_bucket(count)},
                "claims": {"pattern": "OPEN=1" if count else ""},
                "budget": {"fraction": fraction, "bucket": 0,
                           "present": present},
                "chain": chain,
                "phase": "DISPATCH", "sides": {}}

    def test_cold_start_zero(self, tmp_path):
        """No faces present -> anchor 0.0 (no facts, no chain, no cost)."""
        assert ssig.v_anchor(ssig.snapshot(tmp_path)) == 0.0

    def test_full_progress_anchor_one(self):
        snap = self._snap(count=3, verified=3, fraction=0.0,
                          chain={"k": 4, "n": 4})
        # all terms 1.0 (chain 4/4, verified share 1.0, budget remaining 1.0)
        assert ssig.v_anchor(snap) == pytest.approx(1.0)

    def test_weighted_mean_hand_computed(self):
        snap = self._snap(count=4, verified=1, fraction=0.5,
                          chain={"k": 1, "n": 4})
        # (0.5*0.25 + 0.3*0.25 + 0.2*0.5) / 1.0 = 0.125+0.075+0.1 = 0.3
        assert ssig.v_anchor(snap) == pytest.approx(0.3)

    def test_absent_dims_renormalize(self):
        snap = self._snap(count=2, verified=1, fraction=0.0, chain=None)
        # facts term 0.5 weight 0.3; budget remaining 1.0 weight 0.2
        # (0.3*0.5 + 0.2*1.0) / 0.5 = 0.35 / 0.5 = 0.7
        assert ssig.v_anchor(snap) == pytest.approx(0.7)

    def test_budget_present_only_with_cost_face(self, tmp_path):
        # no cost_events.jsonl -> budget dim absent; no facts/chain -> V 0
        assert ssig.v_anchor(ssig.snapshot(tmp_path)) == 0.0
        _cost(tmp_path, [50.0])  # spent everything, remaining 0
        assert ssig.v_anchor(ssig.snapshot(tmp_path)) == pytest.approx(0.0)

    def test_bounds_and_determinism(self):
        import random
        rng = random.Random(396)
        for _ in range(50):
            snap = self._snap(
                count=rng.randint(0, 30), verified=rng.randint(0, 30),
                fraction=rng.random(),
                chain={"k": rng.randint(0, 5), "n": 5}
                if rng.random() < 0.7 else None)
            if snap["facts"]["verified"] > snap["facts"]["count"]:
                snap["facts"]["verified"] = snap["facts"]["count"]
            v = ssig.v_anchor(snap)
            assert 0.0 <= v <= 1.0
            assert v == ssig.v_anchor(snap)  # pure, deterministic

    def test_no_learning_no_data_files(self, tmp_path):
        """The anchor is a pure function: no banked-data file is read even
        when one exists next to the workspace (empirical correction is the
        documented v0.2 seam)."""
        (tmp_path / "v-corrections.json").write_text(
            json.dumps({"x": 99.0}), encoding="utf-8")
        ws = tmp_path
        _fact(ws, "F001", "PROVEN")
        _fact(ws, "F002", "VERIFIED")
        _fact(ws, "F003", "OPEN")
        _fact(ws, "F004", "PROVEN")
        _fact(ws, "F005", "PROVEN")
        _cost(ws, [10.0])
        v = ssig.v_anchor(ssig.snapshot(ws))
        # facts 4/5=0.8 (w .3); budget remaining 0.8 (w .2); no chain face
        expected = (0.3 * 0.8 + 0.2 * 0.8) / 0.5
        assert v == pytest.approx(expected)


# ---------- situation snapshot stream ----------

class TestSituationStream:
    def test_append_row_shape(self, tmp_path):
        res = ssig.append_snapshot(tmp_path, trigger="worker_return",
                                   tick=3, ts="2026-09-27T00:00:00Z")
        assert res["appended"] is True
        row = res["row"]
        assert row["schema"] == "situation/1"
        assert row["trigger"] == "worker_return"
        assert row["tick"] == 3
        assert row["state"]["schema"] == "state-sig/1"
        assert row["signature"] == ssig.signature_str(row["state"])
        assert row["signature_hash"] == ssig.signature_hash(row["state"])
        p = tmp_path / "runs" / "situation-stream.jsonl"
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["trigger"] == "worker_return"

    def test_append_only_stream_grows(self, tmp_path):
        ssig.append_snapshot(tmp_path, trigger="worker_return")
        ssig.append_snapshot(tmp_path, trigger="terminal")
        p = tmp_path / "runs" / "situation-stream.jsonl"
        assert len(p.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_tick_inherited_from_convergence_ledger(self, tmp_path):
        (tmp_path / ".convergence_ledger.jsonl").write_text(
            json.dumps({"open_count": 2}) + "\n", encoding="utf-8")
        res = ssig.append_snapshot(tmp_path, trigger="terminal")
        assert res["row"]["tick"] == 1

    def test_fail_open_never_raises(self, tmp_path):
        # a read-only workspace root must not explode the caller
        ro = tmp_path / "ro"
        ro.mkdir()
        ro.chmod(0o444)
        try:
            res = ssig.append_snapshot(ro, trigger="terminal")
            assert res["appended"] is False
        finally:
            ro.chmod(0o755)
