# -*- coding: utf-8 -*-
"""tests/test_governance_binding_867.py — #867 governance-wording machine binding.

Three contracts, pinned after the #867 closeout:

1. DEPRECATED live-caller closeout — external_kicker ranks via the canonical
   scorer (priority_ratio), not the DEPRECATED weighted shim (D2 scenario:
   deleting priority.py must NOT silently degrade the kicker's ordering).
2. Retirement-gate ratchet — the real repo carries ZERO baselined retirement
   debt (the #861-assigned finding `priority<-external_kicker` is cleared).
3. (with T5/T6) Gate 8 "Governance Binding" registration + the SKILL teaching
   shape and evals reconciliation checks it mounts.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "devkit"))
sys.path.insert(0, str(ROOT / "tests"))

import external_kicker as ek  # noqa: E402
import governance_binding as gb  # noqa: E402
import priority_ratio  # noqa: E402
import retirement_gate as rg  # noqa: E402

# Same import-face regex retirement_gate uses (module-import statements only,
# never prose mentions).
DEPRECATED_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+priority\b|from\s+priority\b)", re.MULTILINE)

SKILL_SAMPLE_LINE = (
    'The shape is fixed: a **v1 canonical JSON envelope** opening the dispatch '
    'prompt — `{"kunglao_dispatch": {"version": 1, "claim": "C-NN", '
    '"tier": <N>, "tools": [...], "agent": "<agent>"}}` — parsed by '
    '`hooks/lib_kunglao.py:parse_dispatch` (single source, v1-first; the legacy '
    '`[T<N> tools=...] claim C-NN` text prefix is replay-only, never for new '
    'dispatches). Example: `{"kunglao_dispatch": {"version": 1, '
    '"claim": "C-007", "tier": 1, "tools": ["grep", "xxd"], '
    '"agent": "kunglao-worker"}}` followed by the task text.'
)


def _seed(root: Path, files: dict) -> None:
    for rel, body in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")


def _tmp_repo(tmp_path: Path, files: dict) -> Path:
    """Tmp repo seeded with files + the REAL detector (same-source rule:
    teaching-shape checks must parse through the production parser)."""
    _seed(tmp_path, files)
    (tmp_path / "hooks").mkdir(exist_ok=True)
    shutil.copy(ROOT / "hooks" / "lib_kunglao.py",
                tmp_path / "hooks" / "lib_kunglao.py")
    return tmp_path


# ---------- 1. closeout: no deprecated shim on the live path ----------

def test_external_kicker_source_has_no_deprecated_priority_import() -> None:
    src = (ROOT / "scripts" / "external_kicker.py").read_text(encoding="utf-8")
    assert not DEPRECATED_IMPORT_RE.search(src), (
        "external_kicker still lives off the DEPRECATED priority shim — "
        "#867 closeout: rank via priority_ratio (the #499 authority)")
    assert "priority_ratio" in src, (
        "closeout must name the canonical scorer it switched to")


def test_retirement_gate_real_repo_zero_findings() -> None:
    r = rg.scan(ROOT, [])
    assert r["findings"] == [], (
        "#867 clears the baselined debt; any finding is a NEW violation: "
        f"{r['findings']}")


def test_retirement_baseline_has_no_entries() -> None:
    bp = ROOT / "scripts" / ".retirement-gate-baseline.txt"
    if not bp.exists():
        return
    entries = [ln.strip() for ln in bp.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    assert entries == [], (
        "the #861 baseline was cleared by #867; do not re-baseline debt "
        f"without a new audit entry: {entries}")


def test_kicker_ranks_via_ratio_even_without_deprecated_module(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D2 scenario pin: with the priority shim unimportable (the #446
    retirement end-state), the kicker still ranks by the canonical scorer
    instead of silently falling back to register order."""
    ws = tmp_path
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("# index\n", encoding="utf-8")
    reg = {"claims": [
        {"id": "C-001", "status": "OPEN", "tier": 1},
        {"id": "C-002", "status": "OPEN", "tier": 1,
         "answers_question": "who built the loader?"},
    ]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(reg), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    open_ids = ["C-001", "C-002"]

    evidence = priority_ratio.EvidenceView.from_workspace(ws)
    actions = priority_ratio.priority_ratio(reg["claims"], {}, evidence)
    expected = [a.claim_id for a in actions]
    assert expected == ["C-002", "C-001"], (
        f"fixture sanity: the discriminator must reorder ({expected})")

    # Simulate the #446 retirement end-state: the shim is gone.
    monkeypatch.setitem(sys.modules, "priority", None)
    assert ek._priority_ordered_ids(open_ids, ws) == expected, (
        "kicker ordering must come from priority_ratio, not a silent "
        "register-order fallback")


# ---------- 3. Gate 8 registration lockstep ----------

class TestGate8Registration:
    def test_gate8_registered_in_gates(self) -> None:
        import quality_gates as qg
        assert 8 in qg.GATES, "Gate 8 (Governance Binding) not registered"
        assert qg.GATES[8][0] == "Governance Binding"

    def test_gate8_implementation_exists_and_is_callable(self) -> None:
        import quality_gates as qg
        fn = getattr(qg, "_gate8_governance_binding", None)
        assert fn is not None, "quality_gates.py missing _gate8_governance_binding"

    def test_gate8_name_in_docstring(self) -> None:
        import quality_gates as qg
        assert "Governance Binding" in (qg.__doc__ or "")

    def test_pre_commit_quick_set_matches_registry(self) -> None:
        """The hook quick-set must equal GATES minus opt-in Gate 2
        (registry-derived — mirrors test_agents_lint/test_doc_sync)."""
        src = (ROOT / "devkit" / "githooks" / "pre-commit").read_text(encoding="utf-8")
        import quality_gates as qg
        expected = " ".join(str(g) for g in sorted(qg.GATES) if g != 2)
        assert src.count(expected) == 1, (
            f"pre-commit quiet run must list the registry quick set {expected}")

    def test_ci_workflow_runs_gate8(self) -> None:
        src = (ROOT / ".github" / "workflows" / "release-check.yml").read_text(
            encoding="utf-8")
        assert "devkit/quality_gates.py 1 3 4 8" in src, (
            "release-check CI must run the governance-binding gate")


# ---------- 4. sub-check (b): SKILL teaching shape vs detector ----------

class TestSkillTeachingShape:
    def test_real_repo_skill_teaches_parsable_envelope(self) -> None:
        violations = gb.check_skill_teaching(ROOT, verbose=False)
        assert violations == [], violations

    def test_placeholder_schema_and_concrete_sample_both_parse(self, tmp_path) -> None:
        root = _tmp_repo(tmp_path, {"skills/kunglao-agent/SKILL.md": SKILL_SAMPLE_LINE})
        assert gb.check_skill_teaching(root, verbose=False) == []

    def test_broken_envelope_sample_is_red(self, tmp_path) -> None:
        bad = ('Example: `{"kunglao_dispatch": {"version": 1, '
               '"claim": "claim-1", "tier": 1, "tools": []}}`')
        root = _tmp_repo(tmp_path, {"skills/kunglao-agent/SKILL.md": bad})
        v = gb.check_skill_teaching(root, verbose=False)
        assert any("does not match the detector" in x for x in v), v

    def test_v0_shape_without_replay_marker_is_red(self, tmp_path) -> None:
        body = ('Example: `{"kunglao_dispatch": {"version": 1, "claim": "C-007", '
                '"tier": 1, "tools": []}}`\n'
                'Dispatch like `[T1 tools=grep] claim C-7` at the top.')
        root = _tmp_repo(tmp_path, {"skills/kunglao-agent/SKILL.md": body})
        v = gb.check_skill_teaching(root, verbose=False)
        assert any("replay-only/legacy marker" in x for x in v), v

    def test_no_samples_fail_closed(self, tmp_path) -> None:
        root = _tmp_repo(tmp_path, {"skills/kunglao-agent/SKILL.md": "no envelope here"})
        v = gb.check_skill_teaching(root, verbose=False)
        assert any("teaches no kunglao_dispatch envelope" in x for x in v), v

    def test_missing_skill_fail_closed(self, tmp_path) -> None:
        v = gb.check_skill_teaching(tmp_path, verbose=False)
        assert any("missing" in x for x in v), v


# ---------- 5. sub-check (c): evals vs deprecation reconciliation ----------

class TestEvalsReconciliation:
    def test_real_repo_evals_clean(self) -> None:
        assert gb.check_evals(ROOT, verbose=False) == []

    def test_real_repo_evals_pin_the_authority(self) -> None:
        text = (ROOT / "evals" / "evals.json").read_text(encoding="utf-8")
        assert "priority.py" not in text, (
            "evals must not pin the DEPRECATED shim's ordering (#867)")
        assert "priority_ratio.py" in text, (
            "eval #1 must pin the canonical scorer")

    def test_deprecated_ref_in_evals_is_red(self, tmp_path) -> None:
        root = _tmp_repo(tmp_path, {
            "scripts/legacy_mod.py": "DEPRECATED = True\n",
            "evals/evals.json": json.dumps({
                "evals": [{"id": 1, "prompt": "follow legacy_mod.py ordering"}]}),
        })
        v = gb.check_evals(root, verbose=False)
        assert any("legacy_mod" in x for x in v), v

    def test_exception_allow_list_suppresses(self, tmp_path) -> None:
        root = _tmp_repo(tmp_path, {
            "scripts/legacy_mod.py": "DEPRECATED = True\n",
            "evals/evals.json": json.dumps({
                "evals": [{"id": 1, "prompt": "follow legacy_mod.py ordering"}]}),
            "devkit/governance-exceptions.json": json.dumps({
                "evals_allowed_refs": [
                    {"file": "evals/evals.json", "pattern": "legacy_mod.py",
                     "reason": "audited historical fixture"}]}),
        })
        assert gb.check_evals(root, verbose=False) == []

    def test_docstring_prose_line_not_registered(self, tmp_path) -> None:
        """AST registry precision: a docstring line starting with
        DEPRECATED=True (retirement_gate.py header shape) must NOT
        register a deprecation."""
        root = _tmp_repo(tmp_path, {
            "scripts/prose_only.py": '"""Gate doc.\n\nDEPRECATED=True but '
                                     'prose only, no assignment.\n"""\n',
            "evals/evals.json": json.dumps({"evals": []}),
        })
        assert gb._deprecated_stems(root) == []
        assert gb.check_evals(root, verbose=False) == []
