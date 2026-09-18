# -*- coding: utf-8 -*-
"""Issue 250 — plan epistemics library (scripts/plan_epistemics.py).

The four bookkeeping pieces as pure units:
  - lint_plan_contingency: per-step if-fails branching (piece 1)
  - derive_must_master / mint_epistemic_claims / seed_situational_pqs:
    situational unknowns -> epistemic claims -> ledger.pqs (piece 2)
  - apply_and_measure: signed-gain bookkeeping over the in-place
    PQCategorical.update_* API (EXP-3 call shape; piece 2 convention)
  - settle_coverage: settle-time coverage annotation (piece 4)
  - semantic matching helpers shared with refutation_propagate (piece 3)

Conventions pinned by the EXP-3 spike (.spike-exp3-findings.md):
  - pq_id == the answers_question string priority_ratio keys on
  - update_* mutate in place and return None — the CALLER snapshots entropy
  - delta_h_bits = H_before - H_after is SIGNED (softening raises entropy),
    never clamped
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_epistemics as pe  # noqa: E402
from posteriors import PQCategorical, PosteriorLedger  # noqa: E402


# ---------- piece 1: per-step if-fails contingency lint ----------

LINEAR_PLAN = (
    "goal: prove sub_1234 dispatch mode\n"
    "preflight:\n"
    "  - verify tool signatures\n"
    "steps:\n"
    "  1. run static xref on sub_1234 -> expect caller list\n"
    "  2. trace dispatch table -> expect handler address\n"
    "fallback:\n"
    "  - if all fails: report blocker\n"
)

BRANCHED_PLAN = (
    "goal: prove sub_1234 dispatch mode\n"
    "preflight:\n"
    "  - verify tool signatures\n"
    "steps:\n"
    "  1. run static xref on sub_1234 -> expect caller list\n"
    "     if-fails: if xref index empty -> try RegisterNatives scan\n"
    "  2. trace dispatch table -> expect handler address\n"
    "     if-fails: if trace refused -> emulate handler via qiling\n"
    "fallback:\n"
    "  - if all fails: report blocker\n"
)


def test_linear_plan_violations_found():
    violations = pe.lint_plan_contingency(LINEAR_PLAN)
    assert len(violations) == 2  # one per enumerated step
    assert all("if-fails" in v for v in violations)


def test_branched_plan_clean():
    assert pe.lint_plan_contingency(BRANCHED_PLAN) == []


def test_bare_if_fails_label_is_violation():
    text = (
        "goal: g\n"
        "steps:\n"
        "  1. step one -> expect out\n"
        "     if-fails:\n"
    )
    violations = pe.lint_plan_contingency(text)
    assert len(violations) == 1
    assert "condition" in violations[0] or "action" in violations[0]


def test_inline_single_value_steps_pass_legacy_shape():
    text = "goal: decode strings\nsteps: dump strings\nfallback: xxd walk\n"
    assert pe.lint_plan_contingency(text) == []


def test_no_steps_section_passes():
    assert pe.lint_plan_contingency("goal: g\npreflight: check\n") == []


def test_bulleted_steps_also_bound():
    text = (
        "goal: g\n"
        "steps:\n"
        "  - do the thing -> expect result\n"
        "fallback: f\n"
    )
    assert len(pe.lint_plan_contingency(text)) == 1


# ---------- piece 2: derive -> mint -> seed ----------

VMP_TASK_SPEC = {
    "lane": "malware",
    "primary_questions": [
        {"id": "q1", "q": "family?", "need": "yes_no_with_evidence",
         "candidates": []},
    ],
}


def _vmp_ws(ws: Path) -> Path:
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "die.json").write_text(
        '{"derived": {"detected_packer": "vmprotect"}}', encoding="utf-8")
    return ws


def test_vmp_target_derives_dispatch_and_pointer_unknowns(tmp_path):
    unknowns = pe.derive_must_master("vmp", VMP_TASK_SPEC)
    pq_ids = [u["pq_id"] for u in unknowns]
    assert "q_dispatch_mode" in pq_ids
    assert any("pointer" in p for p in pq_ids)
    for u in unknowns:
        assert u["candidates"], "unknowns must carry a competitor set"
        assert u["promotion_gate"].strip()


def test_android_target_derives_register_natives_unknown(tmp_path):
    unknowns = pe.derive_must_master("android", {})
    pq_ids = [u["pq_id"] for u in unknowns]
    assert "q_dispatch_mode" in pq_ids
    assert any("register_natives" in p for p in pq_ids)


def test_unknown_target_derives_nothing():
    assert pe.derive_must_master(None, {}) == []


def test_detect_target_class_vmp(tmp_path):
    _vmp_ws(tmp_path)
    assert pe.detect_target_class(tmp_path) == "vmp"


def test_detect_target_class_android_via_apkid(tmp_path):
    ev = tmp_path / "evidence"
    ev.mkdir(parents=True)
    (ev / "apkid.json").write_text('{"status": "ok"}', encoding="utf-8")
    assert pe.detect_target_class(tmp_path) == "android"


def test_detect_target_class_fail_open(tmp_path):
    assert pe.detect_target_class(tmp_path) is None


def test_mint_epistemic_claims_shape():
    unknowns = pe.derive_must_master("vmp", VMP_TASK_SPEC)
    minted = pe.mint_epistemic_claims([], unknowns, next_id_fn=lambda i: f"C-{100 + i}")
    assert minted
    for c in minted:
        assert c["boundary_type"] == "epistemic"
        assert c["status"] == "OPEN"
        assert c["answers_question"].startswith("q_")
        # signed-gain fields pinned at mint; delta may be negative later
        assert isinstance(c["h_standing_bits"], float)
        assert c["delta_h_bits"] == 0.0
        assert c["promotion_gate"].strip()


def test_mint_is_idempotent_by_pq_id():
    unknowns = pe.derive_must_master("vmp", VMP_TASK_SPEC)
    first = pe.mint_epistemic_claims([], unknowns, next_id_fn=lambda i: f"C-{100 + i}")
    second = pe.mint_epistemic_claims(first, unknowns,
                                      next_id_fn=lambda i: f"C-{200 + i}")
    assert second == []


def test_seed_situational_pqs_writes_ledger(tmp_path):
    _vmp_ws(tmp_path)
    unknowns = pe.derive_must_master("vmp", VMP_TASK_SPEC)
    minted = pe.mint_epistemic_claims([], unknowns, next_id_fn=lambda i: f"C-{100 + i}")
    report = pe.seed_situational_pqs(tmp_path, minted, VMP_TASK_SPEC)
    led = PosteriorLedger.load(tmp_path)
    for c in minted:
        pq = led.pqs.get(c["answers_question"])
        assert pq is not None, f"ledger.pqs missing {c['answers_question']}"
        assert pq.entropy() > 0.0
        row = next(r for r in report if r["pq_id"] == c["answers_question"])
        assert row["h_standing_bits"] == pytest.approx(pq.entropy(), abs=1e-6)


def test_seed_uses_task_spec_candidates_when_available(tmp_path):
    spec = {
        "primary_questions": [
            {"id": "q_dispatch_mode", "need": "model_selection",
             "candidates": ["static_xref", "register_natives"]},
        ],
    }
    unknowns = pe.derive_must_master("vmp", spec)
    minted = pe.mint_epistemic_claims([], unknowns, next_id_fn=lambda i: f"C-{i}")
    report = pe.seed_situational_pqs(tmp_path, minted, spec)
    led = PosteriorLedger.load(tmp_path)
    pq = led.pqs["q_dispatch_mode"]
    assert set(pq.probs.keys()) == {"static_xref", "register_natives"}
    row = next(r for r in report if r["pq_id"] == "q_dispatch_mode")
    assert row["source"] == "task_spec_candidates"


# ---------- piece 2 convention: signed apply_and_measure ----------

def test_apply_and_measure_evidence_positive_gain():
    pq = PQCategorical("q_jni_registration", {
        "jni_register_natives": 0.5, "static_xref_dlsym": 0.3,
        "runtime_dlopen": 0.2})
    row = pe.apply_and_measure(pq, ("evidence", "static_xref_dlsym", 2.5))
    assert row["delta_h_bits"] == pytest.approx(0.069654, abs=1e-4)
    assert row["h_standing_bits"] == pytest.approx(1.415821, abs=1e-4)
    assert row["h_before_bits"] == pytest.approx(1.485475, abs=1e-4)


def test_apply_and_measure_elimination_largest_gain():
    pq = PQCategorical("q_jni_registration", {
        "jni_register_natives": 0.5, "static_xref_dlsym": 0.3,
        "runtime_dlopen": 0.2})
    pe.apply_and_measure(pq, ("evidence", "static_xref_dlsym", 2.5))
    row = pe.apply_and_measure(pq, ("eliminate", "jni_register_natives"))
    assert row["delta_h_bits"] == pytest.approx(0.673333, abs=1e-4)


def test_apply_and_measure_softening_delta_negative_and_unclamped():
    pq = PQCategorical("q_ctrl", {"leader": 0.9375, "laggard": 0.0625})
    row = pe.apply_and_measure(pq, ("evidence", "leader", 0.5))
    assert row["delta_h_bits"] < 0  # signed, spike EXP-3b
    assert row["delta_h_bits"] == pytest.approx(-0.185269, abs=1e-4)


def test_apply_and_measure_last_candidate_eliminate_is_noop():
    pq = PQCategorical("q_one", {"only": 1.0})
    row = pe.apply_and_measure(pq, ("eliminate", "only"))
    assert row["delta_h_bits"] == 0.0
    assert pq.entropy() == 0.0  # survived, not crashed


# ---------- piece 4: settle-time coverage annotation ----------

def _write_fact(ws: Path, fid: str, claim_id: str, assumptions: list,
                title: str = "observation") -> None:
    d = ws / "facts"
    d.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump({
        "id": fid, "type": "fact", "title": title, "status": "PROVEN",
        "claim_id": claim_id, "assumptions": assumptions,
        "created": "2026-09-18", "last_reviewed": "2026-09-18",
    }, sort_keys=False)
    (d / f"{fid}.md").write_text(f"---\n{fm}---\n\nbody\n", encoding="utf-8")


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")


def test_settle_coverage_unresolved_open_presupposition(tmp_path):
    _write_fact(tmp_path, "F001-xref", "C-101", ["q_dispatch_mode=static"])
    _register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-110", "status": "OPEN", "boundary_type": "epistemic",
         "answers_question": "q_dispatch_mode"},
    ])
    row = pe.settle_coverage(tmp_path, "C-101")
    assert row["coverage"] == "uncovered"
    assert "q_dispatch_mode" in row["unresolved"]


def test_settle_coverage_terminal_presupposition_is_covered(tmp_path):
    _write_fact(tmp_path, "F001-xref", "C-101", ["q_dispatch_mode=static"])
    _register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-110", "status": "REFUTED", "boundary_type": "epistemic",
         "answers_question": "q_dispatch_mode"},
    ])
    row = pe.settle_coverage(tmp_path, "C-101")
    assert row["coverage"] == "covered"
    assert row["unresolved"] == []


def test_settle_coverage_no_assumptions_trivially_covered(tmp_path):
    _register(tmp_path, [{"id": "C-101", "status": "PROVEN"}])
    row = pe.settle_coverage(tmp_path, "C-101")
    assert row["coverage"] == "covered"


# ---------- piece 3 matcher (shared with refutation_propagate) ----------

def test_contradiction_matches_topic_with_opposite_polarity():
    assert pe.contradicts_assumption(
        "dispatch=static",
        "JNI_OnLoad registers natives via RegisterNatives; VM dispatch "
        "resolves calls dynamically")
    assert not pe.contradicts_assumption(
        "dispatch=static",
        "static xref finds two call sites in the dispatch table")
    assert not pe.contradicts_assumption(
        "not-an-assumption", "anything")


def test_split_assumption_rejects_unkeyed():
    assert pe.split_assumption("dispatch=static") == ("dispatch", "static")
    assert pe.split_assumption("static linkage") is None
