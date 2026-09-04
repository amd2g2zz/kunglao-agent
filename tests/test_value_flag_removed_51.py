# -*- coding: utf-8 -*-
"""#51: KUNGLAO_VALUE_ALGO experiment flag removed — value loop unified.

Owner ruling (no-backcompat policy, 2026-09-01): leftover compat layers
are top removal candidates. The #823 N-arm value algorithm becomes the
ONLY path: priority_ratio feed-side terms (prior_p, capability bonus,
mission gap), rho_checkpoint.attach_signals and the zero-output circuit
run unconditionally. These tests pin (a) zero flag residue, (b) the
unified priority_ratio values on a default environment, (c) that
attach_signals no longer early-returns.
"""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def _default_env(monkeypatch):
    """Pin the true default environment: shells that still carry the
    experiment-era KUNGLAO_VALUE_ALGO=1 must not mask the unified path."""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)


# ---------- (a) zero residue ----------

def _scan_sources(trees, suffixes):
    for tree in trees:
        for p in sorted((ROOT / tree).rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            if p.suffix not in suffixes:
                continue
            yield p


def test_no_flag_residue_in_scripts_and_hooks():
    """KUNGLAO_VALUE_ALGO appears nowhere under scripts/ or hooks/."""
    hits = [str(p) for p in _scan_sources(("scripts", "hooks"),
                                          {".py", ".md", ".yaml", ".json"})
            if "KUNGLAO_VALUE_ALGO" in p.read_text(encoding="utf-8",
                                                   errors="replace")]
    assert hits == [], f"flag residue left behind: {hits}"


def test_value_config_module_deleted():
    """The whole module was the flag — deleted, not stubbed."""
    assert not (ROOT / "scripts" / "value_config.py").exists()


def test_no_value_config_imports():
    """No consumer still imports the deleted module."""
    pat = re.compile(r"^\s*(?:import|from)\s+value_config\b", re.MULTILINE)
    hits = [str(p) for p in _scan_sources(("scripts", "hooks"), {".py"})
            if pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert hits == [], f"dangling value_config imports: {hits}"


# ---------- shared fixture ----------

def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(
        {"primary_questions": [{"id": "q1", "question": "RCE reachability?"}],
         "depth": "deep"}), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-gap", "status": "OPEN", "promotion_attempts": 0,
         "statement": "c2 config extract", "evidence_tier_attempted": 3,
         "answers_question": "q1"},
        {"id": "C-junk", "status": "OPEN", "promotion_attempts": 0,
         "statement": "family attribution", "evidence_tier_attempted": 1},
    ]}, allow_unicode=True), encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text("", encoding="utf-8")
    return ws


# ---------- (b) priority_ratio unified path ----------

def test_from_workspace_resolves_mission_gap(tmp_path):
    """Mission-ledger gaps reach the view unconditionally — previously
    short-circuited to the neutral mission_active=False without the flag."""
    import mission_ledger as ml
    import priority_ratio as pr
    ws = _mk_ws(tmp_path)
    ml.init(ws)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_active is True
    assert ev.mission_gap.get("q1") == pytest.approx(1.0)


def test_gap_hit_claim_leads_ranking(tmp_path):
    """A claim answering an open PQ leads the dispatch ranking —
    previously every gap_bucket stayed 0 (flat neutral ordering)."""
    import mission_ledger as ml
    import priority_ratio as pr
    ws = _mk_ws(tmp_path)
    ml.init(ws)
    claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))["claims"]
    ev = pr.EvidenceView.from_workspace(ws)
    acts = pr.priority_ratio(claims, {}, ev)
    assert acts[0].claim_id == "C-gap"
    assert acts[0].gap_bucket == 1


def test_from_workspace_resolves_prior_p(tmp_path):
    """prior_p comes from the replay priors — previously pinned to the
    neutral 1.0 without the flag."""
    import priority_ratio as pr
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "value-priors.yaml").write_text(yaml.safe_dump(
        {"schema": "kunglao-value-priors/1",
         "buckets": {"deep|*": {"n": 30, "p_complete": 0.75}}}),
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.prior_p_complete == pytest.approx(0.75)


def test_low_prior_inflates_effective_cost():
    """With the unified path the cost correction is live: a pessimistic
    prior scores strictly below an optimistic one for the same claim."""
    import priority_ratio as pr
    claim = {"id": "C-001", "status": "OPEN", "statement": "c2 config extract",
             "evidence_tier_attempted": 1, "promotion_attempts": 0}
    pessimistic = pr.priority_ratio(
        [claim], {}, pr.EvidenceView(prior_p_complete=0.25))[0].score
    optimistic = pr.priority_ratio(
        [claim], {}, pr.EvidenceView(prior_p_complete=0.9))[0].score
    assert pessimistic < optimistic


# ---------- (c) rho_checkpoint.attach_signals unified path ----------

def test_attach_signals_no_longer_early_returns(tmp_path):
    """On a default environment the decision dict gains value_signals and
    the shadow emit lands in the ledger (previously a flag-off no-op)."""
    import rho_checkpoint as rc
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "logs").mkdir()
    (ws / "runs" / "value-priors.yaml").write_text(yaml.safe_dump(
        {"schema": "kunglao-value-priors/1",
         "buckets": {"deep|*": {"n": 30, "p_complete": 0.75}}}),
        encoding="utf-8")
    decision = rc.attach_signals(ws, {"decision": "DISPATCH"})
    sig = decision["value_signals"]
    assert sig["v"] == pytest.approx(0.75)
    assert sig["source"] == "depth_bucket"
    assert "d" in sig and "eta_min" in sig
    logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert logs, "shadow emit missing"
    rows = [json.loads(line)
            for p in logs for line in p.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("action") == "rho_checkpoint" for r in rows)
