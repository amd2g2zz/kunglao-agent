# -*- coding: utf-8 -*-
"""tests/test_case_admission_301.py — #301 oracle case minting standard.

The oracle verdict is the system's only trusted currency. #126 guards the
STRUCTURE of a case (refs resolve, signature dedup, mutations required,
cross-candidate separation) and #128/#191 guard the TASK layer — but
case-level SEMANTIC quality had no admission rule, so counterfeit coins
could mint:

  1. category-existence  "当前样本存在加密算法" — the criterion itself is
     fuzzy, so the verdict degenerates into LLM judgment (forgeable);
  2. comprehension-claim "理解了这个协议" — no byte-level criterion;
  3. activity-claim      "分析了 so 文件" — doing is not knowing.

A LEGAL case is a quantified verification contract carrying the 4-tuple
    (artifact, criterion, threshold, feeds_decision)
— a named artifact, a MECHANICAL criterion (executable without any LLM,
closed vocabulary), a numeric threshold, and the decision the resolution
feeds. A vague question is a ROOT of a case tree: it must decompose into
children that each carry the 4-tuple (the model decomposes — the machine
only validates the tree SHAPE — there is no auto-decomposer), or bounce
back to the task layer for re-operationalization (#128 path) with a
recorded reason. It never enters the bank as-is.

Pinned here:
  - the three illegal classes are REFUSED at registration with the class
    named (the issue's exact specimen phrases);
  - the issue's own decomposition example (C1 constant-hit / C2 pair-match
    >=11 of 14 / C3 canary round-trip) loads clean as a tree: root skipped
    (not runnable), children armed;
  - bank invariant: every ADMITTED case carries the full 4-tuple;
  - sweep over a synthetic legacy bank (tests/fixtures/oracle301/) yields
    the decompose/retire diff list, with a retirement-gate-style baseline
    ratchet (re-sweep after handling reports nothing new);
  - the captured-pairs fixture is pinned against an independent Python
    model of the synthetic ARX target (the C2 shape is real, not prose).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_case_admission as oca  # noqa: E402  (RED: module absent)
import oracle_runner as orun  # noqa: E402

FIX301 = ROOT / "tests" / "fixtures" / "oracle301"

HYP_A = "H-301a"   # competitor_group: grp-301 (open)
HYP_B = "H-301b"   # grp-301's second OPEN member (live competition)


def _write_hypothesis(ws: Path, hyp_id: str, group: str) -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-301\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        "status: open\n"
        "schema_rev: 1\n"
        "---\n\npq:q301\n\nSeeded scaffold — a #301 child realizes this bet.\n",
        encoding="utf-8")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F301.md").write_text(
        "# F301\n\nSHA-1 K0 constant pinned at segment 0x179E5C "
        "(byte-anchored).\n", encoding="utf-8")
    _write_hypothesis(ws, HYP_A, "grp-301")
    _write_hypothesis(ws, HYP_B, "grp-301")
    return ws


def _write_case(ws: Path, case: dict, name: str) -> Path:
    p = ws / "oracle" / "cases" / name
    p.write_text(
        yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return p


def _legal_case(cid: str, hyp: str = HYP_A, **over) -> dict:
    """A minimally legal #301 case: #126-armed + the verification 4-tuple."""
    case = {
        "id": cid,
        "channel": "device-trace",
        "hypothesis_ref": hyp,
        "update_map": {"green_up": [hyp, HYP_B], "red_up": [HYP_B]},
        "params": {},
        "expected": [
            {"field": "sha1_k0_hit", "value": 1,
             "evidence_refs": ["F301"]},
        ],
        "mutations": [{"field": "sha1_k0_hit", "kind": "change"}],
        "verification": {
            "artifact": "SHA-1 family constant K0=0x5A827999 hit in the "
                        "0x179E5C segment constant table",
            "artifact_kind": "constant",
            "criterion": "constant-hit",
            "threshold": {"min_hits": 1},
            "feeds_decision": "pq:crypto-family",
        },
    }
    case.update(over)
    return case


# ------------------------------- 1. the three illegal classes (RED first)

@pytest.mark.parametrize("phrase, klass", [
    ("当前样本存在加密算法", "category-existence"),
    ("理解了这个协议", "comprehension-claim"),
    ("分析了 so 文件", "activity-claim"),
])
def test_illegal_class_phrase_refused_with_class_named(
        tmp_path: Path, phrase: str, klass: str) -> None:
    """The issue's three counterfeit-coin specimens, as the case's whole
    verification clause, are REFUSED at registration and the rejection
    class is NAMED in the refusal."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("specimen")
    case["verification"] = {"criterion": phrase}
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match=klass):
        orun.load_cases(ws / "oracle" / "cases")


def test_illegal_question_root_refused_with_class_named(
        tmp_path: Path) -> None:
    """The same specimens arriving as a vague `question` on an otherwise
    structured case are refused too — the clause surface does not matter."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("questionable")
    case.pop("verification")
    case["question"] = "当前样本存在加密算法"
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match="category-existence"):
        orun.load_cases(ws / "oracle" / "cases")


# ------------------------------------ 2. missing / non-mechanical clause

def test_missing_verification_refused(tmp_path: Path) -> None:
    """A case claiming non-pending observations with NO verification block
    is the degenerate category-existence form: the criterion itself is
    absent, so the verdict would degenerate into LLM judgment."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("no-contract")
    case.pop("verification")
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match="missing-verification"):
        orun.load_cases(ws / "oracle" / "cases")


def test_non_mechanical_criterion_refused(tmp_path: Path) -> None:
    """`criterion` is a CLOSED mechanical vocabulary (comparator runnable
    without any LLM). A judged/similarity phrasing is not executable."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("judged")
    case["verification"]["criterion"] = "output looks similar to the sample"
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError,
                       match="non-mechanical-criterion"):
        orun.load_cases(ws / "oracle" / "cases")


def test_unknown_artifact_kind_refused(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path)
    case = _legal_case("bad-kind")
    case["verification"]["artifact_kind"] = "vibes"
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match="artifact_kind"):
        orun.load_cases(ws / "oracle" / "cases")


def test_threshold_required_and_shape_checked(tmp_path: Path) -> None:
    """A counted criterion with no numeric threshold is not quantified —
    refused; min_hits must be a positive int and `of` must not undercut it."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("no-threshold")
    case["verification"]["criterion"] = "pair-match"
    case["verification"]["artifact_kind"] = "pair-set"
    case["verification"]["threshold"] = {}
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match="threshold"):
        orun.load_cases(ws / "oracle" / "cases")

    case2 = _legal_case("bad-threshold")
    case2["verification"]["criterion"] = "pair-match"
    case2["verification"]["artifact_kind"] = "pair-set"
    case2["verification"]["threshold"] = {"min_hits": 11, "of": 5}
    _write_case(ws, case2, "case-01.yaml")
    with pytest.raises(orun.OracleCaseError, match="threshold"):
        orun.load_cases(ws / "oracle" / "cases")


def test_vague_decision_coupling_refused(tmp_path: Path) -> None:
    """Decision coupling: the resolution must NAME the decision it feeds —
    a TBD stub couples to nothing."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("no-decision")
    case["verification"]["feeds_decision"] = "TBD"
    _write_case(ws, case, "case-00.yaml")
    with pytest.raises(orun.OracleCaseError, match="feeds_decision"):
        orun.load_cases(ws / "oracle" / "cases")


# ------------------------------------------- 3. decomposition / bounce

def _write_c123(ws: Path) -> None:
    """The issue's own decomposition example, as three leaf cases. The
    children observe through DISTINCT channels (static constant scan /
    replay reproduction / device hook) — #126 signature dedup requires
    marginal discriminative power, and the tree delivers exactly that."""
    _write_case(ws, _legal_case(
        "c1-constant-hit", channel="static",
        verification={
            "artifact": "0x179E5C segment constant table hit: "
                        "SHA-1 family K0=0x5A827999",
            "artifact_kind": "constant",
            "criterion": "constant-hit",
            "threshold": {"min_hits": 1},
            "feeds_decision": "pq:crypto-family",
        }), "case-c1.yaml")
    _write_case(ws, _legal_case(
        "c2-pair-reproduction", channel="replay",
        verification={
            "artifact": "captured (input,output) pair set, 14 pairs "
                        "(tests/fixtures/oracle301/captured_pairs.json)",
            "artifact_kind": "pair-set",
            "criterion": "pair-match",
            "threshold": {"min_hits": 11, "of": 14},
            "feeds_decision": "pq:crypto-family",
        }), "case-c2.yaml")
    _write_case(ws, _legal_case(
        "c3-kdf-canary", channel="device-trace",
        verification={
            "artifact": "derived KEY produced by this KDF "
                        "(canary plaintext round-trip)",
            "artifact_kind": "hook-state",
            "criterion": "canary-agreement",
            "threshold": {"exact": True},
            "feeds_decision": "pq:crypto-family",
        }), "case-c3.yaml")


def test_issue_decomposition_tree_admitted(tmp_path: Path) -> None:
    """'contains encryption' decomposed into C1/C2/C3 (the issue's exact
    example): the vague ROOT is skipped (not runnable — it carries no
    mechanical clause), each child is armed and carries the 4-tuple."""
    ws = _mk_ws(tmp_path)
    _write_c123(ws)
    root = {
        "id": "root-encryption",
        "question": "当前样本存在加密算法",
        "decomposition": ["c1-constant-hit", "c2-pair-reproduction",
                          "c3-kdf-canary"],
    }
    _write_case(ws, root, "case-00-root.yaml")
    cases = orun.load_cases(ws / "oracle" / "cases")
    assert [c["id"] for c in cases] == \
        ["c1-constant-hit", "c2-pair-reproduction", "c3-kdf-canary"], \
        "the vague root must not enter the runnable set; its children must"
    for c in cases:
        assert c["verification"]["criterion"]
        assert c["verification"]["threshold"]


def test_bounce_record_sends_root_back_to_task_layer(
        tmp_path: Path) -> None:
    """The #128 path: a vague root with no named artifacts bounces to the
    task layer for re-operationalization, with the reason recorded. The
    bounce record is machine-validated (reason + target non-empty)."""
    ws = _mk_ws(tmp_path)
    root = {
        "id": "root-bounced",
        "question": "理解了这个协议",
        "bounce": {"reason": "no byte-level criterion can be named from "
                             "the captured evidence; re-operationalize "
                             "the goal (#128)",
                   "target": "goal-operationalization"},
    }
    _write_case(ws, root, "case-00-root.yaml")
    assert orun.load_cases(ws / "oracle" / "cases") == []
    rec = oca.bounce_records(ws / "oracle" / "cases")
    assert [r["id"] for r in rec] == ["root-bounced"]
    assert rec[0]["reason"] and rec[0]["target"]


def test_bounce_without_reason_refused(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path)
    root = {"id": "root-bounced", "question": "理解了这个协议",
            "bounce": {"reason": "", "target": "goal-operationalization"}}
    _write_case(ws, root, "case-00-root.yaml")
    with pytest.raises(orun.OracleCaseError, match="bounce"):
        orun.load_cases(ws / "oracle" / "cases")


def test_vague_root_without_face_refused(tmp_path: Path) -> None:
    """A vague question with NEITHER a decomposition nor a bounce never
    enters the bank — refused, class named."""
    ws = _mk_ws(tmp_path)
    root = {"id": "root-naked", "question": "分析了 so 文件"}
    _write_case(ws, root, "case-00-root.yaml")
    with pytest.raises(orun.OracleCaseError, match="activity-claim"):
        orun.load_cases(ws / "oracle" / "cases")


def test_decomposition_children_must_exist_and_be_legal(
        tmp_path: Path) -> None:
    """Tree SHAPE is machine-validated: children must resolve to sibling
    cases, each child itself legal (carries the 4-tuple, is not itself a
    root — depth-1 tree)."""
    ws = _mk_ws(tmp_path)
    _write_case(ws, {"id": "root-x", "question": "当前样本存在加密算法",
                     "decomposition": ["ghost-child"]},
                "case-00-root.yaml")
    with pytest.raises(orun.OracleCaseError, match="ghost-child"):
        orun.load_cases(ws / "oracle" / "cases")

    ws2 = _mk_ws(tmp_path / "two")
    _write_case(ws2, {"id": "root-y", "question": "当前样本存在加密算法",
                      "decomposition": ["vague-child"]},
                "case-00-root.yaml")
    _write_case(ws2, {"id": "vague-child",
                      "question": "理解了这个协议"}, "case-01.yaml")
    with pytest.raises(orun.OracleCaseError, match="vague-child"):
        orun.load_cases(ws2 / "oracle" / "cases")


def test_nested_decomposition_refused(tmp_path: Path) -> None:
    """Depth-1 trees only: a child that itself declares a decomposition is
    a diamond the machine cannot attribute verdicts through — refused."""
    ws = _mk_ws(tmp_path)
    _write_case(ws, {"id": "root-z", "question": "当前样本存在加密算法",
                     "decomposition": ["mid"]}, "case-00-root.yaml")
    _write_case(ws, {"id": "mid", "question": "理解了这个协议",
                     "decomposition": ["leaf"]}, "case-01.yaml")
    with pytest.raises(orun.OracleCaseError, match="mid"):
        orun.load_cases(ws / "oracle" / "cases")


# ------------------------------------------ 4. bank invariant + registry

def test_bank_invariant_every_admitted_row_is_contract_or_scaffold(
        tmp_path: Path) -> None:
    """THE #301 bank invariant, stated so doc and test cannot drift: every
    row admit_set() admits is EITHER a contract row carrying the FULL
    (artifact, artifact_kind, criterion, threshold, feeds_decision) tuple
    OR an explicit all-pending scaffold ({"scaffold": true} — every
    expected entry is pending-observation: it claims nothing, pending is
    never green, there is no green face to forge)."""
    ws = _mk_ws(tmp_path)
    _write_c123(ws)
    scaffold = _legal_case("s-row")
    scaffold.pop("verification")
    scaffold["expected"] = [
        {"field": "sha1_k0_hit", "value": None,
         "evidence_refs": [], "pending-observation": True},
    ]
    _write_case(ws, scaffold, "case-s.yaml")
    report = oca.admit_set(ws / "oracle" / "cases")
    rows = {r["id"]: r for r in report["admitted"]}
    assert set(rows) == {"c1-constant-hit", "c2-pair-reproduction",
                         "c3-kdf-canary", "s-row"}
    for rid, row in rows.items():
        if row.get("scaffold"):
            assert "verification" not in row, \
                f"{rid}: a scaffold row carries no contract"
        else:
            v = row["verification"]
            assert v["artifact"] and v["artifact_kind"] in oca.ARTIFACT_KINDS
            assert v["criterion"] in oca.MECHANICAL_CRITERIA
            assert v["threshold"]
            assert v["feeds_decision"]
    assert rows["s-row"].get("scaffold") is True
    assert "verification" in rows["c1-constant-hit"]
    assert report["refused"] == []


def test_legacy_husk_gets_clean_decision_never_traceback(
        tmp_path: Path) -> None:
    """FIX regression: a pre-#301 legacy husk — an id (+ at most a question
    that evades the phrase tables) with NO expected list and NO
    verification block — is exactly the shape the sweep migrates. Both
    faces must return a clean refusal/decision for it, never a
    TypeError (dict(None)) traceback."""
    cases = tmp_path / "husk-bank"
    cases.mkdir(parents=True)
    (cases / "husk-bare.yaml").write_text(
        "id: husk-bare\n", encoding="utf-8")
    (cases / "husk-evasive.yaml").write_text(
        'id: husk-evasive\nquestion: "样本结构似乎有些特别"\n',
        encoding="utf-8")
    report = oca.admit_set(cases)  # must not raise
    assert report["admitted"] == []
    assert {r["id"] for r in report["refused"]} == \
        {"husk-bare", "husk-evasive"}
    assert all(r["class"] == "missing-verification"
               for r in report["refused"])
    diff = oca.sweep(cases)  # must not raise
    assert diff["keep"] == [] and diff["decompose"] == []
    assert {r["id"] for r in diff["retire"]} == \
        {"husk-bare", "husk-evasive"}
    for row in diff["retire"]:
        assert row["attribution_class"] == "case-wrong"


def test_admit_set_reports_illegal_classes(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path)
    for i, phrase in enumerate(("当前样本存在加密算法", "理解了这个协议",
                                "分析了 so 文件")):
        case = _legal_case(f"bad-{i}")
        case["verification"] = {"criterion": phrase}
        _write_case(ws, case, f"case-{i}.yaml")
    report = oca.admit_set(ws / "oracle" / "cases")
    assert report["admitted"] == []
    assert sorted(r["class"] for r in report["refused"]) == [
        "activity-claim", "category-existence", "comprehension-claim"]


# ------------------------------------------------- 5. sweep (legacy bank)

SWEEP_KEEP = ("bank-keep-1", "bank-keep-2")
SWEEP_DECOMPOSE = ("bank-root-decomp",)
SWEEP_RETIRE = ("bank-vague-1", "bank-vague-2")
LEGACY_BANK = FIX301 / "bank-legacy"


def test_sweep_diff_list_over_synthetic_legacy_bank() -> None:
    """The #301 acceptance sweep over the synthetic legacy bank (NO real
    workspace data): legal cases keep, a declared-but-unfinished
    decomposition proposes decompose, vague cases without a face propose
    retirement under the #146 case-abandonment taxonomy (case-wrong)."""
    diff = oca.sweep(LEGACY_BANK)
    assert [r["id"] for r in diff["keep"]] == list(SWEEP_KEEP)
    assert [r["id"] for r in diff["decompose"]] == list(SWEEP_DECOMPOSE)
    assert [r["id"] for r in diff["retire"]] == list(SWEEP_RETIRE)
    for row in diff["retire"]:
        assert row["attribution_class"] == "case-wrong"
        assert row["disconfirmation"]
        assert row["reason"]
    for row in diff["decompose"]:
        assert row["reason"]


def test_sweep_baseline_ratchet(tmp_path: Path) -> None:
    """retirement_gate.py semantics: handled ids go into a baseline; a
    re-sweep over the handled bank reports nothing NEW."""
    diff = oca.sweep(LEGACY_BANK)
    baseline = sorted(r["id"] for bucket in ("decompose", "retire")
                      for r in diff[bucket])
    bfile = tmp_path / "baseline.txt"
    bfile.write_text("\n".join(baseline) + "\n", encoding="utf-8")
    diff2 = oca.sweep(LEGACY_BANK, baseline_file=bfile)
    assert diff2["new_findings"] == []
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    diff3 = oca.sweep(LEGACY_BANK, baseline_file=empty)
    assert diff3["new_findings"], "without the baseline everything is new"


def test_sweep_cli_faces(tmp_path: Path, capsys) -> None:
    """CLI: admit face exits 0 on a legal set / 1 naming classes; sweep
    face prints the diff list; both are machine-readable via --json."""
    ws = _mk_ws(tmp_path)
    _write_c123(ws)
    cases_dir = str(ws / "oracle" / "cases")
    assert oca.main([cases_dir, "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert len(rep["admitted"]) == 3 and rep["refused"] == []
    assert oca.main([cases_dir, "--sweep", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rep["keep"]] == [
        "c1-constant-hit", "c2-pair-reproduction", "c3-kdf-canary"]
    bad = _legal_case("bad-cli")
    bad["verification"] = {"criterion": "理解了这个协议"}
    _write_case(ws, bad, "case-bad.yaml")
    assert oca.main([cases_dir, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert any(r["class"] == "comprehension-claim" for r in out["refused"])


# ------------------------------------- 6. admission respects #146 retirement

def test_retired_cases_stay_exempt(tmp_path: Path) -> None:
    """#146 lineage: a retired case has left the acceptance net and must
    not start refusing because #301 now demands a verification contract."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("old-case")
    case.pop("verification")
    case["status"] = "retired"
    case["retirement"] = {
        "attribution_class": "case-wrong",
        "disconfirmation": "superseded by c2-pair-reproduction",
        "replacement": "c2-pair-reproduction",
    }
    _write_case(ws, case, "case-00.yaml")
    assert orun.load_cases(ws / "oracle" / "cases") == []


# --------------------------------------------- 7. scaffold (all-pending)

def test_all_pending_scaffold_needs_no_contract(tmp_path: Path) -> None:
    """A scaffold whose every expected entry is pending-observation claims
    nothing — pending is the honest unknown, there is nothing to forge.
    The #301 contract is owed only when a real (non-pending) claim exists."""
    ws = _mk_ws(tmp_path)
    case = _legal_case("scaffold")
    case.pop("verification")
    case["expected"] = [
        {"field": "sha1_k0_hit", "value": None,
         "evidence_refs": [], "pending-observation": True},
    ]
    _write_case(ws, case, "case-00.yaml")
    cases = orun.load_cases(ws / "oracle" / "cases")
    assert [c["id"] for c in cases] == ["scaffold"]


# ------------------------------- 8. the C2 fixture is real, not prose

def test_captured_pairs_match_independent_python_model() -> None:
    """The 14 captured pairs are pinned against an independent Python
    model of the synthetic ARX target (the Go source's algorithm): byte
    agreement on all 14 is the mechanical criterion the C2 child names."""
    pairs = json.loads(
        (FIX301 / "captured_pairs.json").read_text(encoding="utf-8"))
    pairs = pairs["pairs"] if isinstance(pairs, dict) else pairs
    assert len(pairs) == 14

    def arx_step(x: int, y: int, rot: int) -> int:
        rotl = ((y << rot) | (y >> (32 - rot))) & 0xFFFFFFFF
        return ((x + rotl + 0x9E3779B9) & 0xFFFFFFFF) ^ 0x5A827999

    for i, row in enumerate(pairs):
        x = (i * 2654435761 + 1) & 0xFFFFFFFF
        assert row["in"] == x
        assert row["out"] == arx_step(x, i + 1, (i % 31) + 1), \
            f"pair {i} does not match the declared ARX model"


def test_go_source_declares_k0_and_arx() -> None:
    """The synthetic Go target carries the SHA-1 constant and the ARX step
    the C1/C2 contracts name (static, byte-anchored)."""
    src = (FIX301 / "sample_arx.go").read_text(encoding="utf-8")
    assert "0x5A827999" in src
    assert "func arxStep" in src
