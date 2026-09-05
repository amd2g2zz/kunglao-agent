# -*- coding: utf-8 -*-
"""tests/test_priority_data_hookup_9.py — #9 priority_ratio consumes the
dynamic feeds that already exist on dev (mission_ledger / tuition V_m
dynamics, difficulty_calibration, strategy-log dispatch rows).

Issue #9: after #51 (L/D/N always-on), #8 (mission_ledger settlement) and
#10 (v_norm / d_slope_norm), the SCORE still reads none of it — the L/D/N
terms stay on their static graph/register inputs and the VoI exploration
loop never closes (a converged mission ranks exactly like a fresh one).

Pre-change behavior (pinned by the neutral-path tests below, citing the
module docstring of priority_ratio.py on dev bd6dbdf):
  L(a) = leverage: |downstream OPEN claims| normalized (claim_deps reverse
         edges) — a claim with no dependents scored L=0.0 even when the
         mission ledger showed live V_m accrual on the PQ it answers;
  D(a) = discriminator: live competitor_group=1.0 / answers_question=0.5 /
         else=0.2 — difficulty evidence was never read;
  N(a) = 1 - min(1, (terminal facts in category + same-strategy failures)
         / NOVELTY_BASE) — dispatch-row repetition was not counted.

This suite pins: feeds flow in, missing feeds stay NEUTRAL with an explicit
reason, and the score assembly formula is unchanged (structure preservation
— data hookup, not algorithm redesign).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402


DIFF_DOC = {
    "schema": "difficulty-calibration/1",
    "tier": "max",
    "score": 0.812,
    "dominant_factor": "packer_present",
    "factors": {}, "families": {},
    "coverage": {"die": True, "apkid": True},
    "thresholds": {"medium": 0.15, "hard": 0.4, "max": 0.65},
    "notes": [],
}


def _claim(cid, status="OPEN", answers_question=None, competitor_group=None,
           statement=""):
    c = {"id": cid, "status": status, "evidence_tier_attempted": 0,
         "promotion_attempts": 0, "statement": statement or cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    if competitor_group is not None:
        c["competitor_group"] = competitor_group
    return c


def _mk_ws(tmp_path, name="ws", claims=(), pqs=None, with_difficulty=False):
    """Minimal workspace: register + PQ spec (+ optional difficulty mount)."""
    ws = tmp_path / name
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": list(claims)}, allow_unicode=True),
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": pqs or {}}, allow_unicode=True),
        encoding="utf-8")
    if with_difficulty:
        ev = ws / "evidence"
        ev.mkdir()
        (ev / "difficulty.json").write_text(json.dumps(DIFF_DOC), encoding="utf-8")
    return ws


def _seed_ledger(ws, settled: bool, rounds: int = 2):
    """mission_ledger at init; when settled, PROVEN C-0 answers PQ-1 between
    two value_m() calls → V_m history rises 0 -> 0.5 (2 PQs, Σw=2)."""
    import mission_ledger as ml
    ml.init(ws)
    ml.value_m(ws)
    if settled:
        ml.update(ws)
    for _ in range(rounds - 1):
        ml.value_m(ws)


# ---------- L <- mission value dynamics ----------

def test_rising_vm_makes_leverage_positive(tmp_path):
    """RED on dev: a claim answering an OPEN PQ in a ledger with RISING V_m
    history scored L=0.0 (no claim_deps edges). After the hookup the L term
    carries the mission-learning signal: headroom (1 - v_norm) x live slope
    x open-PQ linkage > 0."""
    claims = [_claim("C-0", status="PROVEN", answers_question="PQ-1"),
              _claim("C-1", answers_question="PQ-2")]
    ws = _mk_ws(tmp_path, claims=claims,
                pqs={"PQ-1": "which family?", "PQ-2": "which c2?"})
    _seed_ledger(ws, settled=True)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_v_norm == 0.5, "fixture sanity: one of two PQs settled"
    assert ev.mission_d_slope_norm > 0, "fixture sanity: V_m rising"
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-1"].leverage > 0.0, (
        "rising V_m + open-PQ linkage must lift the L term above the "
        "pre-change graph-only 0.0")
    # structure preserved: the Action still carries the combined L and the
    # score formula identity holds over the FINAL per-term values (cost_eff
    # = cost / prior — the #823 feed-side term from_workspace resolves)
    a = by["C-1"]
    cost_eff = a.cost / max(ev.prior_p_complete, 0.05)
    assert a.score == round(
        (0.45 * a.leverage + 0.30 * a.discriminator + 0.25 * a.novelty)
        / cost_eff, 3)
    assert "mission" in (a.feeds or {}).get("L", "")


def test_converged_mission_closes_L(tmp_path):
    """VoI loop closure: v_norm=1 (all PQs answered) -> headroom 0 -> the
    mission contribution to L collapses to 0 even while slope was live."""
    claims = [_claim("C-0", status="PROVEN", answers_question="PQ-1"),
              _claim("C-1", status="PROVEN", answers_question="PQ-2"),
              _claim("C-2", answers_question="PQ-2")]
    ws = _mk_ws(tmp_path, claims=claims,
                pqs={"PQ-1": "which family?", "PQ-2": "which c2?"})
    import mission_ledger as ml
    ml.init(ws)
    ml.value_m(ws)
    ml.update(ws)  # both PQs answered
    ml.value_m(ws)
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    by = {a.claim_id: a for a in out}
    assert ev.mission_v_norm == 1.0
    assert by["C-2"].leverage == 0.0, "converged mission must not re-inflate L"


def test_flat_vm_keeps_L_neutral(tmp_path):
    """Ledger present but zero accrual (flat history) -> no demonstrated
    learning -> the mission contribution stays 0 (and the reason says so)."""
    claims = [_claim("C-0", status="PROVEN", answers_question="PQ-1"),
              _claim("C-1", answers_question="PQ-2")]
    ws = _mk_ws(tmp_path, claims=claims,
                pqs={"PQ-1": "which family?", "PQ-2": "which c2?"})
    import mission_ledger as ml
    ml.init(ws)
    ml.value_m(ws)
    ml.value_m(ws)  # flat: two zero points
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    a = out[0]
    assert a.leverage == 0.0
    assert "flat" in (a.feeds or {}).get("L", "")


# ---------- D <- difficulty evidence ----------

def test_difficulty_max_reflects_in_discriminator(tmp_path):
    """RED on dev: difficulty.json tier=max left D at the legacy 0.2 floor.
    After the hookup the calibrated score lifts D mechanically (x
    1 + 0.5*score), clamped to the D ceiling 1.0."""
    claims = [_claim("C-1", statement="generic recon")]
    ws = _mk_ws(tmp_path, claims=claims, with_difficulty=True)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.difficulty_tier == "max" and ev.difficulty_score == 0.812
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    a = out[0]
    assert a.discriminator > 0.2, "tier=max must lift D above the legacy base"
    assert round(a.discriminator, 6) == round(0.2 * (1 + 0.5 * 0.812), 6)
    assert "difficulty" in (a.feeds or {}).get("D", "")


def test_difficulty_tier_only_doc_fallback(tmp_path):
    """A difficulty doc with a tier but no numeric score still maps (tier
    enum surface: easy 1.0 / medium 1.15 / hard 1.3 / max 1.5)."""
    claims = [_claim("C-1")]
    ws = _mk_ws(tmp_path, claims=claims)
    ev_dir = ws / "evidence"
    ev_dir.mkdir()
    doc = dict(DIFF_DOC)
    doc.pop("score")
    (ev_dir / "difficulty.json").write_text(json.dumps(doc), encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    assert round(out[0].discriminator, 6) == round(0.2 * 1.5, 6)


def test_difficulty_via_task_spec_mount(tmp_path):
    """#15's second face: the ``difficulty:`` key mounted in task_spec.yaml
    feeds D when evidence/difficulty.json is absent."""
    claims = [_claim("C-1")]
    ws = _mk_ws(tmp_path, claims=claims)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": {},
                        "difficulty": DIFF_DOC}, allow_unicode=True),
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    assert out[0].discriminator > 0.2


# ---------- N <- dispatch-row repetition (existing strategy-log feed) ----------

def test_dispatch_repetition_damps_novelty(tmp_path):
    """RED on dev: repeated same-strategy dispatch rows for a claim left N
    at 1.0. After the hookup the rows the strategy-log ALREADY carries
    (#496 read path, no new plumbing) count as method repetition."""
    claims = [_claim("C-1", statement="generic recon")]
    ws = _mk_ws(tmp_path, claims=claims)
    runs = ws / "runs"
    runs.mkdir()
    rows = [{"event": "dispatch", "strategy": "static", "claim": "C-1",
             "attempts_at_snapshot": 0},
            {"event": "dispatch", "strategy": "static", "claim": "C-1",
             "attempts_at_snapshot": 1}]
    (runs / "strategy-log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    a = out[0]
    assert ev.claim_dispatch_repeats == {"C-1": 2}
    assert a.novelty == round(1.0 - min(1.0, 2 / pr.NOVELTY_BASE), 3), (
        "two dispatch rows for the claim must damp N by 2/NOVELTY_BASE")
    fresh = pr.EvidenceView()
    assert pr.priority_ratio(claims, {"depends_on": {}}, fresh)[0].novelty == 1.0


def test_failed_rows_not_double_counted_in_novelty(tmp_path):
    """One signal, one channel: dispatch rows already counted by the #496
    failure channel (covers > snapshot) are NOT re-counted as #9 repeats —
    N keeps the pinned 2-failures arithmetic (1/3, not 0)."""
    claims = [_claim("C-1", statement="generic recon")]
    ws = _mk_ws(tmp_path, claims=claims)
    runs = ws / "runs"
    runs.mkdir()
    rows = [{"event": "dispatch", "strategy": "static", "claim": "C-1",
             "attempts_at_snapshot": 0},
            {"event": "dispatch", "strategy": "static", "claim": "C-1",
             "attempts_at_snapshot": 1}]
    (runs / "strategy-log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    analyses = ws / "analyses"
    analyses.mkdir()
    # covers_attempt=2 > both snapshots -> both rows are #496 failures
    (analyses / "failure-C-1.yaml").write_text(
        yaml.safe_dump({"claim": "C-1", "covers_attempt": 2,
                        "validated_capability": "", "identified_obstacle": ""}),
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.strategy_failures == {"static": 2}
    assert ev.claim_dispatch_repeats == {}, "failed rows are not #9 repeats"
    a = pr.priority_ratio(claims, {"depends_on": {}}, ev)[0]
    assert a.novelty == round(1.0 - min(1.0, 2 / pr.NOVELTY_BASE), 3)


# ---------- neutral fallbacks / regression ----------

def test_no_feeds_terms_neutral_and_score_unchanged():
    """No ledger, no difficulty, no dispatch rows -> every term takes the
    documented pre-change value, the formula identity holds byte-identical,
    and each term records an explicit neutral reason."""
    claims = [_claim("HUB"), _claim("L-1"), _claim("L-2")]
    deps = {"depends_on": {"L-1": ["HUB"], "L-2": ["HUB"]}}
    ev = pr.EvidenceView()  # direct construction == no feeds anywhere
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    hub = by["HUB"]
    assert hub.leverage == 1.0, "graph-only leverage unchanged"
    assert hub.discriminator == 0.2 and hub.novelty == 1.0
    assert hub.score == round(
        (0.45 * 1.0 + 0.30 * 0.2 + 0.25 * 1.0) / hub.cost, 3)
    feeds = hub.feeds or {}
    assert "graph leverage only" in feeds.get("L", "")
    assert "difficulty feed absent" in feeds.get("D", "")
    assert "dispatch" in feeds.get("N", "")
    # feeds are object-level diagnostics — the --json face (to_dict) keeps
    # its pre-#9 key set (full-payload equality across workspaces, qtable p3)
    assert set(hub.to_dict()) == {"claim_id", "action", "score", "skill",
                                  "weight"}


def test_neutral_reasons_on_bare_workspace(tmp_path):
    """from_workspace over a workspace with none of the feeds -> neutral
    terms + reasons (and the pre-change score, regression-pinned)."""
    claims = [_claim("C-1", statement="generic recon")]
    ws = _mk_ws(tmp_path, claims=claims)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_v_norm is None and ev.mission_d_slope_norm is None
    assert ev.difficulty_tier is None and ev.difficulty_score is None
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    a = out[0]
    # pre-change values, byte-identical: claim has no answers_question here
    assert (a.leverage, a.discriminator, a.novelty) == (0.0, 0.2, 1.0)
    cost_eff = a.cost / max(ev.prior_p_complete, 0.05)  # #823 prior feed
    assert a.score == round((0.30 * 0.2 + 0.25 * 1.0) / cost_eff, 3)
    feeds = a.feeds or {}
    assert "absent" in feeds.get("L", "") and "absent" in feeds.get("D", "")


def test_no_ledger_no_crash(tmp_path):
    """No runs/ dir at all -> from_workspace must not raise and the ranking
    must stay fully neutral (fail-open discipline)."""
    ws = tmp_path / "bare"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [_claim("C-1")]}, allow_unicode=True),
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio([_claim("C-1")], {"depends_on": {}}, ev)
    assert len(out) == 1
    assert ev.mission_active is False
    assert ev.mission_v_norm is None


def test_corrupt_feeds_fail_open(tmp_path):
    """Garbage difficulty.json + corrupt ledger yaml -> neutral, not crash,
    not faked signal."""
    claims = [_claim("C-1")]
    ws = _mk_ws(tmp_path, claims=claims, pqs={"PQ-1": "q"})
    (ws / "runs").mkdir()
    (ws / "runs" / "mission_ledger.yaml").write_text(
        "{not: [valid: yaml", encoding="utf-8")
    evd = ws / "evidence"
    evd.mkdir()
    (evd / "difficulty.json").write_text("<<<garbage>>>", encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    a = out[0]
    assert (a.leverage, a.discriminator, a.novelty) == (0.0, 0.2, 1.0)


def test_wrong_schema_difficulty_ignored(tmp_path):
    """A difficulty file that is not the #15 schema is NOT signal (never
    scored as difficulty) -> D stays legacy."""
    claims = [_claim("C-1")]
    ws = _mk_ws(tmp_path, claims=claims)
    evd = ws / "evidence"
    evd.mkdir()
    (evd / "difficulty.json").write_text(
        json.dumps({"tier": "max", "score": 0.9}), encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio(claims, {"depends_on": {}}, ev)
    assert out[0].discriminator == 0.2


# ---------- score differentiation (the issue's actual complaint) ----------

def test_converging_vs_flat_workspaces_different_top_scores(tmp_path):
    """Two synthetic workspaces identical except for ledger dynamics: the
    converging one (rising V_m) must outrank the flat one — the score stops
    being flat across mission states."""
    claims = [_claim("C-0", status="PROVEN", answers_question="PQ-1"),
              _claim("C-1", answers_question="PQ-2", statement="generic recon")]
    pqs = {"PQ-1": "which family?", "PQ-2": "which c2?"}
    ws_conv = _mk_ws(tmp_path, name="conv", claims=claims, pqs=pqs)
    ws_flat = _mk_ws(tmp_path, name="flat", claims=claims, pqs=pqs)
    _seed_ledger(ws_conv, settled=True)
    import mission_ledger as ml
    ml.init(ws_flat)
    ml.value_m(ws_flat)
    ml.value_m(ws_flat)
    ev_conv = pr.EvidenceView.from_workspace(ws_conv)
    ev_flat = pr.EvidenceView.from_workspace(ws_flat)
    top_conv = pr.priority_ratio(claims, {"depends_on": {}}, ev_conv)[0]
    top_flat = pr.priority_ratio(claims, {"depends_on": {}}, ev_flat)[0]
    assert top_conv.claim_id == top_flat.claim_id == "C-1"
    assert top_conv.score > top_flat.score, (
        "converging mission must outrank a flat one — the VoI score must "
        "differentiate on ledger dynamics")


def test_difficulty_lifts_rank_between_identical_workspaces(tmp_path):
    """Same workspace except difficulty mount -> the max-difficulty one ranks
    its claim higher (D channel differentiates)."""
    claims = [_claim("C-1", statement="generic recon")]
    pqs = {"PQ-1": "q"}
    ws_plain = _mk_ws(tmp_path, name="plain", claims=claims, pqs=pqs)
    ws_hard = _mk_ws(tmp_path, name="hard", claims=claims, pqs=pqs,
                     with_difficulty=True)
    ev_p = pr.EvidenceView.from_workspace(ws_plain)
    ev_h = pr.EvidenceView.from_workspace(ws_hard)
    s_p = pr.priority_ratio(claims, {"depends_on": {}}, ev_p)[0].score
    s_h = pr.priority_ratio(claims, {"depends_on": {}}, ev_h)[0].score
    assert s_h > s_p
