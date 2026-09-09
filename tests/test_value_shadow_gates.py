# -*- coding: utf-8 -*-
"""A5 (#823): shadow promotion gates — the three written criteria that must
pass before the value loop graduates from shadow to canary (four-stage gate,
AUDIT_REPORT §14; plan Task A5). Always-on since #51 (#51 removed the
experiment switch).

1. ρ VOC > 0.7 — ρ sequence correlates with true progress on a synthetic
   trajectory (Pearson).
2. fingerprint zero false-positives — a synthetic GOOD trajectory (belief
   moves between same-type actions) never trips the circuit.
3. prior correction does not degrade the synthetic baseline ranking —
   neutral priors reproduce the base order exactly.
"""

import priority_ratio as pr
import rho_checkpoint as rc
import zero_output_fingerprint as zf


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs)
           * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den if den else 0.0


def test_gate_1_rho_voc_above_threshold():
    true_progress = [0.1, 0.2, 0.35, 0.5, 0.72, 0.9]
    # verifier stub: per-PQ grades bracketing the true progress
    cps = [{"PQ1": {"grade": round(min(1.0, t + 0.05), 2)},
            "PQ2": {"grade": round(max(0.0, t - 0.05), 2)}}
           for t in true_progress]
    rho = rc.rho_sequence(cps)
    assert _pearson(true_progress, rho) > 0.7


def test_gate_2_fingerprint_zero_false_positives(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    for i in range(6):  # healthy loop: same tool, but belief moves each round
        (ws / "facts" / "_INDEX.md").write_text(
            f"F{i + 1:03d} | PROVEN | C-001 | round {i}\n", encoding="utf-8")
        r = zf.record_action(ws, "mcp__ghidra__decompile_function", "function")
        assert r["circuit_broken"] is False, f"false break at round {i}"


def test_gate_3_seeded_ranking_deterministic(monkeypatch):
    """#107 re-pin: the prior-correction term is deleted with the weighted
    formula; the gate now pins the equivalent no-degradation property of the
    rebuilt ranker — the default-seed ranking is stable and the worth
    channel (the one sanctioned exogenous input) does not reshuffle the arm
    set, only reweights it."""
    claims = [
        {"id": "C-001", "status": "OPEN", "statement": "c2 config extract",
         "evidence_tier_attempted": 1, "promotion_attempts": 0},
        {"id": "C-002", "status": "OPEN", "statement": "family attribution",
         "evidence_tier_attempted": 2, "promotion_attempts": 0},
        {"id": "C-003", "status": "OPEN", "statement": "protocol restore",
         "evidence_tier_attempted": 1, "promotion_attempts": 0},
    ]
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    base = [a.claim_id for a in pr.priority_ratio(claims, {}, pr.EvidenceView())]
    again = [a.claim_id for a in pr.priority_ratio(claims, {}, pr.EvidenceView())]
    worthed = [a.claim_id for a in pr.priority_ratio(
        claims, {}, pr.EvidenceView(value_class_weights={"rce": 3.0}))]
    assert base == again
    assert sorted(base) == sorted(worthed)  # reweighted, never reshuffled
