# -*- coding: utf-8 -*-
"""tests/test_policy_state_769.py — the policy-state projection (issue
#769) + the policy-state-fresh liveness fingerprint.

Three pins:

  1. The round close projects the LATEST plan receipt into
     runs/policy-state.json (schema policy-state/1: round / candidates /
     admitted / chosen / posterior summary / ts) — a projection over the
     SAME receipts the dispatch gate lands, never a re-sampling; a
     receipt-less workspace writes nothing; an unchanged receipt dedups.
  2. The dispatch-gate receipt carries the candidates projection
     (additive: admitted/chosen untouched), and the statusline snapshot
     carries the policy display face.
  3. The policy-state-fresh fingerprint: absence on a live workspace is
     a FAIL (a decorative face is the failure mode the gate exists to
     catch); the projection's EMIT word is registered.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
DEVKIT = ROOT / "devkit"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS), str(DEVKIT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _factories import write_claims_register  # noqa: E402

TS = "2026-10-19T00:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-5", "status": "OPEN"}])
    return ws


def _receipt_row(ws: Path, claim: str = "C-5") -> dict:
    """A plan-receipt/1 row in the deployed shape (#773 W3 + the #779
    candidates projection)."""
    row = {
        "schema": "plan-receipt/1",
        "ts": TS,
        "claim": claim,
        "state_signature": "sig-" + "a" * 12,
        "admitted": [f"dispatch/{claim}"],
        "chosen": f"dispatch/{claim}",
        "candidates": {
            f"dispatch/{claim}": {"action_kind": "dispatch", "cost": 1.0,
                                  "ratio": 3.5, "theta": 0.7, "alpha": 2.0,
                                  "beta": 1.0},
            f"park/{claim}": {"action_kind": "park", "cost": 0.0,
                              "ratio": 0.0, "theta": 0.5, "alpha": 1.0,
                              "beta": 1.0},
        },
    }
    p = ws / "runs" / "plan-receipts.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# =================== 2. the policy-state projection (#769) ===============

class TestPolicyStateProjection:
    def test_project_writes_policy_state_schema(self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        assert policy_state.run_face(ws) is True
        doc = json.loads((ws / "runs" / "policy-state.json")
                         .read_text(encoding="utf-8"))
        assert doc["schema"] == "policy-state/1"
        for key in ("round", "candidates", "admitted", "chosen",
                    "posterior", "ts"):
            assert key in doc, f"policy-state/1 field {key} missing"
        assert doc["admitted"] == ["dispatch/C-5"]
        assert doc["chosen"] == "dispatch/C-5"
        assert doc["claim"] == "C-5"

    def test_candidates_carry_the_sampled_shape(self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        policy_state.run_face(ws)
        doc = json.loads((ws / "runs" / "policy-state.json")
                         .read_text(encoding="utf-8"))
        cand = doc["candidates"]["dispatch/C-5"]
        for key in ("action_kind", "cost", "ratio", "theta", "alpha",
                    "beta"):
            assert key in cand, f"candidate projection key {key} missing"

    def test_posterior_summary_groups_by_action_kind(self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        policy_state.run_face(ws)
        doc = json.loads((ws / "runs" / "policy-state.json")
                         .read_text(encoding="utf-8"))
        post = doc["posterior"]
        assert post["state_signature"] == "sig-" + "a" * 12
        assert set(post["actions"]) == {"dispatch", "park"}
        assert post["actions"]["dispatch"]["alpha"] == 2.0

    def test_round_is_the_machine_independent_index(self, tmp_path):
        import policy_state
        import priority_ratio
        ws = _ws(tmp_path)
        _receipt_row(ws)
        policy_state.run_face(ws)
        doc = json.loads((ws / "runs" / "policy-state.json")
                         .read_text(encoding="utf-8"))
        assert doc["round"] == priority_ratio.round_index(ws)

    def test_no_receipt_writes_nothing(self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        assert policy_state.run_face(ws) is False
        assert not (ws / "runs" / "policy-state.json").exists(), (
            "no decision happened -> no projection (the fingerprint's "
            "absence-is-failure contract stays honest)")

    def test_unchanged_receipt_skips_the_rewrite(self, tmp_path):
        import datetime as dt
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        t0 = dt.datetime(2026, 10, 19, 12, 0, 0, tzinfo=dt.timezone.utc)
        assert policy_state.run_face(ws, now=t0) is True
        first = (ws / "runs" / "policy-state.json").read_text(
            encoding="utf-8")
        t1 = dt.datetime(2026, 10, 19, 12, 5, 0, tzinfo=dt.timezone.utc)
        assert policy_state.run_face(ws, now=t1) is False, (
            "an unchanged receipt dedups on the receipt identity, never "
            "on the wall clock (compose's content-hash discipline)")
        assert (ws / "runs" / "policy-state.json").read_text(
            encoding="utf-8") == first

    def test_old_receipt_without_candidates_projects_the_rest(
            self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        row = {"schema": "plan-receipt/1", "ts": TS, "claim": "C-5",
               "admitted": ["dispatch/C-5"], "chosen": "dispatch/C-5"}
        p = ws / "runs" / "plan-receipts.jsonl"
        p.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert policy_state.run_face(ws) is True
        doc = json.loads((ws / "runs" / "policy-state.json")
                         .read_text(encoding="utf-8"))
        assert doc["candidates"] == {}
        assert doc["posterior"]["actions"] == {}

    def test_round_closure_hosts_the_projection(self, tmp_path, capsys):
        import round_closure
        ws = _ws(tmp_path)
        _receipt_row(ws)
        rc = round_closure.main_with_payload(
            {"cwd": str(ws), "session_id": "sess-9",
             "transcript_path": str(ws / "t.jsonl")})
        capsys.readouterr()
        assert rc == 0
        assert (ws / "runs" / "policy-state.json").exists(), (
            "the round close is the projection's production host")

    def test_projection_emits_the_registered_word(self, tmp_path):
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        policy_state.run_face(ws)
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "the projection leaves one ledger row"
        rows = [json.loads(l) for l in
                logs[-1].read_text(encoding="utf-8").splitlines() if l]
        actions = [r.get("action") for r in rows]
        assert "policy_state_projected" in actions

    def test_receipt_gains_the_candidates_projection(self, tmp_path):
        """The dispatch-gate receipt row carries the candidate projection
        (additive — the consumers' admitted/chosen keys are untouched)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dispatch_gate_779", HOOKS / "dispatch_gate.py")
        dg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dg)
        ws = _ws(tmp_path)
        dg._write_plan_receipt(ws, "C-5")
        rows = [json.loads(l) for l in
                (ws / "runs" / "plan-receipts.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        row = rows[-1]
        assert row["admitted"] and row["chosen"], (
            "the legacy keys are untouched")
        assert "dispatch/C-5" in row["candidates"]
        assert "ratio" in row["candidates"]["dispatch/C-5"]
        assert row["state_signature"]

    def test_statusline_carries_the_policy_face(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        (ws / "analysis_state.txt").write_text(
            "# analysis_state\nproject_type=windows\n", encoding="utf-8")
        ws.joinpath("claim-register.yaml").write_text("claims: []\n",
                                                      encoding="utf-8")
        snap = sls.build_snapshot(ws)
        assert snap["policy"] is None, "absent source -> None (hidden)"
        _receipt_row(ws)
        import policy_state
        policy_state.run_face(ws)
        snap = sls.build_snapshot(ws)
        assert snap["policy"]["chosen"] == "dispatch/C-5"
        assert snap["policy"]["candidates_n"] == 2
        assert snap["policy"]["admitted_n"] == 1


# ================= 3. the policy-state-fresh liveness fingerprint ========

class TestPolicyStateFingerprint:
    def test_registry_has_the_fingerprint(self):
        from liveness_gate import load_fingerprints
        fps = load_fingerprints(DEVKIT / "liveness_fingerprints.json")
        ids = [f["id"] for f in fps["fingerprints"]]
        assert "policy-state-fresh" in ids

    def test_fingerprint_passes_on_a_projected_workspace(self, tmp_path):
        from liveness_gate import evaluate_fingerprint, load_fingerprints
        import policy_state
        ws = _ws(tmp_path)
        _receipt_row(ws)
        policy_state.run_face(ws)
        fps = load_fingerprints(DEVKIT / "liveness_fingerprints.json")
        fp = next(f for f in fps["fingerprints"]
                  if f["id"] == "policy-state-fresh")
        ok, _ = evaluate_fingerprint(ws, fp)
        assert ok, "a projected workspace proves the face fired"

    def test_fingerprint_fails_on_absence(self, tmp_path):
        from liveness_gate import evaluate_fingerprint, load_fingerprints
        ws = _ws(tmp_path)
        fps = load_fingerprints(DEVKIT / "liveness_fingerprints.json")
        fp = next(f for f in fps["fingerprints"]
                  if f["id"] == "policy-state-fresh")
        ok, detail = evaluate_fingerprint(ws, fp)
        assert not ok and "missing" in detail, (
            "absence of evidence is the failure (the gate's own contract)")

    def test_emit_word_is_registered(self):
        import event_taxonomy
        assert "policy_state_projected" in event_taxonomy.EMIT_ACTIONS
        words = event_taxonomy.EMIT_ACTIONS
        assert words == sorted(set(words)), (
            "the controlled vocabulary stays sorted + unique")

