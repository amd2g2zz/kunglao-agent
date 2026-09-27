#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_case_admission.py — #301 oracle case minting standard: the
SEMANTIC admission gate over ``<ws>/oracle/cases/*.yaml``.

The oracle verdict is the system's only trusted currency. #108 half C made
byte anchors mandatory, #126 made the structure resolvable (refs resolve,
signature dedup, mutations required, cross-candidate separation) and #128
operationalizes the task layer — but case-level SEMANTIC quality had no
admission rule, so counterfeit coins could mint:

  1. category-existence  "当前样本存在加密算法" — the criterion itself is
     fuzzy, so the verdict degenerates into LLM judgment (forgeable);
  2. comprehension-claim "理解了这个协议" — no byte-level criterion;
  3. activity-claim      "分析了 so 文件" — doing is not knowing.

A LEGAL case is a quantified verification contract. Its ``verification:``
clause carries the 4-tuple::

    verification:
      artifact: <named artifact — concrete address / constant / pair set /
                 frame set / hook-observable state>
      artifact_kind: address|constant|pair-set|frame-set|hook-state
      criterion: <one MECHANICAL_CRITERIA — comparator runnable without
                  any LLM>
      threshold: {min_hits: N} | {min_hits: N, of: M} | {all: true}
                 | {exact: true}
      feeds_decision: <the decision/claim/priority-question the resolution
                       feeds — decision coupling>

A vague question is a ROOT of a case tree, never a bankable case. It must
either DECOMPOSE — ``decomposition: [child ids]``, each child a sibling
case carrying its own 4-tuple (the issue's example: "contains encryption"
-> C1 constant-hit / C2 pair-match >=11 of 14 / C3 canary round-trip) —
or BOUNCE back to the task layer for re-operationalization (#128 path):
``bounce: {reason, target}``. The MODEL decomposes; the MACHINE only
validates the tree SHAPE (children resolve, are legal, depth-1 — no
auto-decomposer). A valid root is skipped by load_cases the way a #146
retired case is: it is not runnable, its children are.

Surfaces:
  - oracle_runner.load_cases probes root faces BEFORE the structural lints
    and runs the legality lint LAST (refusal priority of #108/#126 kept);
  - admit_set(cases_dir) is the registration face: the report whose
    `admitted` rows each carry the full 4-tuple (THE bank invariant) and
    whose `refused` rows name the rejection class;
  - sweep(cases_dir) is the legacy-bank migration diff (keep / decompose /
    retire / bounced) with retirement-gate-style baseline ratchet;
    retirement rows follow the #146 case-abandonment taxonomy
    (attribution_class=case-wrong + disconfirmation).

stdlib + PyYAML only; pure functions over the cases dir (no workspace IO
beyond reading case YAML files).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# ----------------------------------------------------- rejection classes

CATEGORY_EXISTENCE = "category-existence"
COMPREHENSION_CLAIM = "comprehension-claim"
ACTIVITY_CLAIM = "activity-claim"
MISSING_VERIFICATION = "missing-verification"
NON_MECHANICAL_CRITERION = "non-mechanical-criterion"
BAD_TREE = "bad-tree"

# The 4-tuple's closed vocabularies. Mechanical = the comparator is
# runnable without any LLM: byte comparisons, counted pair agreement,
# encode/decode round-trips, canary replay, constant-table hits, frame
# completeness, hook-observable state deltas. "Looks similar" is not here.
ARTIFACT_KINDS = ("address", "constant", "pair-set", "frame-set",
                  "hook-state")
MECHANICAL_CRITERIA = ("byte-match", "pair-match", "round-trip",
                       "canary-agreement", "constant-hit", "frame-complete",
                       "state-change")
COUNTED_CRITERIA = ("byte-match", "pair-match", "frame-complete")

# Decision coupling: the resolution must NAME the decision it feeds.
VAGUE_DECISIONS = frozenset((
    "", "tbd", "todo", "none", "na", "n/a", "future", "later", "pending",
))

# The three counterfeit-coin classes, bilingual (zh + en). Deliberately
# NARROW: the scan surfaces are the case's verification clause and its
# `question` — never descriptions, field names or values — so ordinary
# structured cases cannot false-positive.
_ILLEGAL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CATEGORY_EXISTENCE, (
        r"存在.{0,8}(?:加密|算法|解密|压缩|混淆)",
        r"(?:contains?|has|embeds?|uses?)\s+(?:an?\s+|some\s+)?"
        r"(?:encryption|crypto|compress|obfusc)",
    )),
    (COMPREHENSION_CLAIM, (
        r"理解(?:了|这|该)",
        r"\b(?:understands?|understood|comprehends?|comprehended)\b",
    )),
    (ACTIVITY_CLAIM, (
        r"(?:分析|逆向|追踪|调试|跟踪)了",
        r"\b(?:analyzed|analysed|traced|reversed|debugged|disassembled|"
        r"monitored)\b",
    )))


class CaseAdmissionError(ValueError):
    """Registration-time refusal (#301) — loud, never silently banked."""


def classify_prose(text: str) -> str | None:
    """Rejection class of a clause text, or None when it matches none of
    the three counterfeit-coin classes. Pure."""
    s = str(text or "")
    for klass, patterns in _ILLEGAL_PATTERNS:
        if any(re.search(p, s, re.IGNORECASE) for p in patterns):
            return klass
    return None


# --------------------------------------------------- clause surfaces

def _clause_surfaces(doc: dict) -> list[str]:
    """Where a verification clause can hide in the case doc: the `question`
    key and the free-text faces of the verification block. Structured
    fields (params/expected/mutations) are never prose-scanned."""
    surfaces: list[str] = []
    q = doc.get("question")
    if isinstance(q, str) and q.strip():
        surfaces.append(q)
    v = doc.get("verification")
    if isinstance(v, dict):
        for key in ("artifact", "criterion"):
            val = v.get(key)
            if isinstance(val, str) and val.strip():
                surfaces.append(val)
    return surfaces


def _has_real_claims(doc: dict) -> bool:
    """True when at least one expected entry claims an observable value
    (no pending-observation marker): a contract is owed for real claims,
    never for scaffolds — pending is the honest unknown (#108)."""
    expected = doc.get("expected")
    if not isinstance(expected, list):
        return False
    return any(isinstance(e, dict) and not e.get("pending-observation")
               for e in expected)


def _all_pending_scaffold(doc: dict) -> bool:
    """True when the case is an EXPLICIT scaffold: a non-empty expected
    list whose every entry carries the pending-observation marker (the
    honest unknown — claims nothing, so there is no green face to forge).
    A doc with no expected list at all is not a scaffold; it is a husk."""
    expected = doc.get("expected")
    if not isinstance(expected, list) or not expected:
        return False
    return all(isinstance(e, dict) and e.get("pending-observation")
               for e in expected)


# ------------------------------------------------ verification 4-tuple

def _threshold_errors(criterion: str, threshold) -> list[str]:
    """The numeric-threshold face: a clause without a number quantifies
    nothing. Recognized shapes: {min_hits: N[, of: M]} | {all: true}
    | {exact: true}."""
    if not isinstance(threshold, dict) or not threshold:
        return [f"verification.threshold: required for criterion "
                f"{criterion!r} — a clause without a numeric threshold "
                f"(min_hits/of/all/exact) is not quantified (#301)"]
    errors: list[str] = []
    unknown = set(threshold) - {"min_hits", "of", "all", "exact"}
    if unknown:
        errors.append(f"verification.threshold: unknown key(s) "
                      f"{sorted(unknown)} (have min_hits/of/all/exact)")
    min_hits = threshold.get("min_hits")
    if "min_hits" in threshold and (isinstance(min_hits, bool)
                                    or not isinstance(min_hits, int)
                                    or min_hits < 1):
        errors.append("verification.threshold: min_hits must be an "
                      "integer >= 1")
    if "of" in threshold:
        of = threshold["of"]
        floor = min_hits if isinstance(min_hits, int) \
            and not isinstance(min_hits, bool) else 1
        if isinstance(of, bool) or not isinstance(of, int) or of < floor:
            errors.append("verification.threshold: `of` must be an integer "
                          ">= min_hits (>=N of M pairs)")
    for flag in ("all", "exact"):
        if flag in threshold and threshold[flag] is not True:
            errors.append(f"verification.threshold: {flag} must be `true`")
    if not errors and not ({"min_hits", "all", "exact"} & set(threshold)):
        errors.append("verification.threshold: `of` alone quantifies "
                      "nothing — add min_hits/all/exact")
    return errors


def validate_verification(verification) -> list[str]:
    """Schema-validate the 4-tuple. Returns violation strings (empty when
    the clause is a legal quantified verification contract)."""
    if not isinstance(verification, dict):
        return ["verification: required mapping (artifact, artifact_kind, "
                "criterion, threshold, feeds_decision) — the quantified "
                "verification contract (#301)"]
    errors: list[str] = []
    if not str(verification.get("artifact") or "").strip():
        errors.append("verification.artifact: empty — name the artifact "
                      "(address / constant / pair set / frame set / "
                      "hook-observable state)")
    kind = str(verification.get("artifact_kind") or "").strip()
    if kind not in ARTIFACT_KINDS:
        errors.append(f"verification.artifact_kind: {kind!r} is not one of "
                      f"{list(ARTIFACT_KINDS)}")
    criterion = verification.get("criterion")
    klass = classify_prose(criterion) if isinstance(criterion, str) else None
    if klass is not None:
        errors.append(f"verification.criterion {criterion!r} is the "
                      f"{klass} class (#301: a counterfeit coin — the "
                      f"criterion itself is fuzzy, the verdict would "
                      f"degenerate into LLM judgment)")
    elif criterion not in MECHANICAL_CRITERIA:
        errors.append(f"verification.criterion: {criterion!r} is a "
                      f"{NON_MECHANICAL_CRITERION} — the comparator must "
                      f"be executable without any LLM "
                      f"(closed vocabulary: {list(MECHANICAL_CRITERIA)})")
    errors += _threshold_errors(
        str(criterion), verification.get("threshold"))
    feeds = str(verification.get("feeds_decision") or "").strip()
    if feeds.lower() in VAGUE_DECISIONS:
        errors.append("verification.feeds_decision: empty/vague — decision "
                      "coupling requires the resolution to NAME the "
                      "decision it feeds (#301)")
    return errors


def verification_is_legal(doc: dict) -> bool:
    """A doc whose clause classifies clean AND schema-validates clean."""
    if any(classify_prose(s) for s in _clause_surfaces(doc)):
        return False
    if _has_real_claims(doc) and not isinstance(doc.get("verification"),
                                                dict):
        return False
    return not validate_verification(doc.get("verification"))


# --------------------------------------------------- case tree faces

def load_case_docs(cases_dir) -> dict[str, dict]:
    """Tolerant read of every sibling ``*.yaml``: id -> doc (unparseable
    files are skipped — structural lints own malformed YAML)."""
    cases_dir = Path(cases_dir)
    docs: dict[str, dict] = {}
    if not cases_dir.is_dir():
        return docs
    for p in sorted(cases_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(doc, dict):
            cid = str(doc.get("id") or p.stem).strip()
            if cid:
                docs[cid] = doc
    return docs


def _root_face(doc: dict) -> tuple[str, dict] | None:
    """The declared face of a vague root, or None: (face, payload)."""
    bounce = doc.get("bounce")
    if isinstance(bounce, dict):
        return "bounce", bounce
    dec = doc.get("decomposition")
    if isinstance(dec, list) and dec:
        return "decomposition", dec
    return None


def _validate_decomposition(children: list, docs: dict[str, dict]) -> list[str]:
    """Tree SHAPE, machine-validated: every child resolves to a sibling,
    is legal (carries its own 4-tuple, no counterfeit clause), and is not
    itself a root (depth-1 tree — no diamonds)."""
    errors: list[str] = []
    if not children or not all(isinstance(c, str) and c.strip()
                               for c in children):
        return ["decomposition: must be a non-empty list of sibling case "
                "ids (#301: the vague root is a tree ROOT, the children "
                "carry the contracts)"]
    for child in children:
        doc = docs.get(child.strip())
        if doc is None:
            errors.append(
                f"decomposition: child {child!r} does not resolve to a "
                f"sibling case in this set (#301 bad-tree) — the model "
                f"mints the children, the machine only validates shape")
            continue
        if _root_face(doc) is not None:
            errors.append(
                f"decomposition: child {child.strip()!r} is itself a root "
                f"(depth-1 trees only — a diamond cannot attribute "
                f"verdicts, #301 bad-tree)")
            continue
        if not verification_is_legal(doc):
            errors.append(
                f"decomposition: child {child.strip()!r} carries no legal "
                f"verification contract — decomposed children must each "
                f"carry the (artifact, criterion, threshold, "
                f"feeds_decision) tuple (#301)")
    return errors


def _validate_bounce(bounce: dict) -> list[str]:
    if not str(bounce.get("reason") or "").strip() \
            or not str(bounce.get("target") or "").strip():
        return ["bounce: requires a non-empty {reason, target} — an "
                "unreasoned bounce is a silent drop (#301: the #128 "
                "re-operationalization path is a record, not a shrug)"]
    return []


def probe_root_face(doc: dict, cases_dir) -> dict | None:
    """load_cases hook, run BEFORE the structural lints: a case declaring
    a decomposition/bounce face is a vague ROOT. Valid face -> {"skip":
    True, ...} (not runnable — its children are, the way #146 retired
    cases yield); invalid face -> {"errors": [...]}. Faceless cases get
    None and fall through to the structural lints + the legality lint."""
    face = _root_face(doc)
    if face is None:
        return None
    kind, payload = face
    if kind == "bounce":
        errors = _validate_bounce(payload)
        return {"skip": not errors, "face": kind, "errors": errors}
    docs = load_case_docs(cases_dir)
    errors = _validate_decomposition(payload, docs)
    return {"skip": not errors, "face": kind,
            "children": [str(c).strip() for c in payload],
            "errors": errors}


# ------------------------------------------------------ legality lint

def classify_case(doc: dict) -> str:
    """The counterfeit-coin refusal message for the case's clause surfaces
    (empty string when none classifies illegal). The class is the
    fundamental defect: structure cannot redeem a fuzzy criterion, so
    load_cases raises it BEFORE the structural lints."""
    for surface in _clause_surfaces(doc):
        klass = classify_prose(surface)
        if klass is not None:
            return (f"verification clause {surface!r} is the {klass} class "
                    f"(#301 counterfeit coin) — decompose into named-"
                    f"artifact children or bounce to the task layer "
                    f"(#128); a vague clause never enters the bank")
    return ""


def pre_gate(doc: dict, cases_dir) -> tuple[bool, str]:
    """The EARLY #301 gate for load_cases: (skip, refusal).

    - a valid root face (decomposition/bounce) -> (True, ""): the case is
      not runnable, the way a #146 retired case is not — its children are;
    - an invalid face or a counterfeit-coin clause -> (False, refusal)
      with the rejection class NAMED;
    - faceless legal-shaped cases -> (False, ""): they fall through to
      the structural lints, which keep their refusal priority."""
    face = probe_root_face(doc, cases_dir)
    if face is not None:
        if face.get("errors"):
            return False, "; ".join(face["errors"])
        return True, ""
    classification = classify_case(doc)
    if classification:
        return False, classification
    return False, ""


def lint_case(doc: dict) -> list[str]:
    """The #301 legality violations of ONE faceless case (empty = legal).
    In load_cases this runs AFTER the structural lints (they keep refusal
    priority for everything but the named counterfeit-coin classes, which
    fire earlier via classify_case)."""
    classification = classify_case(doc)
    if classification:
        return [classification]
    verification = doc.get("verification")
    if verification is None:
        if _has_real_claims(doc):
            return [f"{MISSING_VERIFICATION}: the case claims real "
                    f"observations with no verification block — the "
                    f"degenerate {CATEGORY_EXISTENCE} form: no mechanical "
                    f"criterion means the verdict degenerates into LLM "
                    f"judgment (#301)"]
        return []  # all-pending scaffold: claims nothing, contract owed
    return validate_verification(verification)


# ------------------------------------------------ registration + sweep

def admit_set(cases_dir) -> dict:
    """Registration face over a case set. Bank invariant (#301): every
    `admitted` row is EITHER a contract row carrying the FULL 4-tuple
    (artifact, artifact_kind, criterion, threshold, feeds_decision) OR an
    explicit all-pending scaffold row ({"scaffold": true} — every expected
    entry is pending-observation: it claims nothing, pending is never
    green, so there is no green face to forge; the contract is owed the
    moment a real claim appears, enforced at every load). A doc with no
    expected list and no verification block is a husk, not a scaffold —
    refused (missing-verification), never silently admitted. `refused`
    rows name the rejection class; valid vague roots are reported under
    `roots` / `bounced` (not runnable, machine-validated shape)."""
    docs = load_case_docs(cases_dir)
    admitted: list[dict] = []
    refused: list[dict] = []
    roots: list[dict] = []
    bounced: list[dict] = []
    for cid, doc in sorted(docs.items()):
        face = _root_face(doc)
        if face is not None:
            kind, payload = face
            errors = (_validate_bounce(payload) if kind == "bounce"
                      else _validate_decomposition(payload, docs))
            if errors:
                refused.append({"id": cid, "class": BAD_TREE,
                                "reason": "; ".join(errors)})
            elif kind == "bounce":
                bounced.append({"id": cid, "reason": str(payload["reason"]),
                                "target": str(payload["target"])})
            else:
                roots.append({"id": cid,
                              "children": [str(c).strip() for c in payload]})
            continue
        violations = lint_case(doc)
        if violations:
            refused.append({"id": cid,
                            "class": _violation_class(violations[0]),
                            "reason": "; ".join(violations)})
            continue
        verification = doc.get("verification")
        if isinstance(verification, dict):
            # contract row — the 4-tuple (tolerant `or {}` mirrors the
            # runner face: validate_verification already ensured a legal
            # mapping, the guard is belt-and-braces against dict(None)).
            admitted.append({"id": cid,
                             "verification": dict(verification or {})})
        elif _all_pending_scaffold(doc):
            # scaffold row — explicit, claims nothing, no green face.
            admitted.append({"id": cid, "scaffold": True})
        else:
            refused.append({"id": cid, "class": MISSING_VERIFICATION,
                            "reason": "no expected claims and no "
                                      "verification contract — nothing to "
                                      "admit; the degenerate "
                                      f"{CATEGORY_EXISTENCE} form (#301)"})
    return {"admitted": admitted, "refused": refused, "roots": roots,
            "bounced": bounced}


def _violation_class(message: str) -> str:
    for klass in (CATEGORY_EXISTENCE, COMPREHENSION_CLAIM, ACTIVITY_CLAIM,
                  MISSING_VERIFICATION, NON_MECHANICAL_CRITERION, BAD_TREE):
        if klass in message:
            return klass
    return "malformed-verification"


def bounce_records(cases_dir) -> list[dict]:
    """The #128 re-operationalization queue: valid bounce faces in the set,
    with their reason and target."""
    return admit_set(cases_dir)["bounced"]


def _retire_row(cid: str, reason: str) -> dict:
    """A #146-lineage retirement proposal (case-abandonment taxonomy:
    `case-wrong` — the case as minted cannot go red mechanically)."""
    from oracle_runner import RETIREMENT_ATTRIBUTION_CLASSES  # lazy: cycle
    assert "case-wrong" in RETIREMENT_ATTRIBUTION_CLASSES
    return {"id": cid,
            "attribution_class": "case-wrong",
            "disconfirmation": "no quantified verification contract — the "
                               "clause cannot go red mechanically (#301 "
                               "sweep)",
            "reason": reason,
            "replacement": "re-operationalize via #128, then mint "
                           "children that each carry the 4-tuple"}


def sweep(cases_dir, baseline_file=None) -> dict:
    """Legacy-bank migration diff: keep (legal) / decompose (a declared
    decomposition whose children are not minted yet) / retire (vague, no
    face — #146 case-wrong) / bounced + roots (valid faces). Baseline
    ratchet a la retirement_gate.py: ids listed in the baseline file are
    handled debt; only NEW findings surface in `new_findings`."""
    report = admit_set(cases_dir)
    docs = load_case_docs(cases_dir)
    decompose: list[dict] = []
    retire: list[dict] = []
    root_ids = {r["id"] for r in report["roots"]} \
        | {r["id"] for r in report["bounced"]}
    for row in report["refused"]:
        doc = docs.get(row["id"], {})
        if row["class"] == BAD_TREE and isinstance(
                doc.get("decomposition"), list):
            children = [str(c).strip() for c in doc["decomposition"]]
            missing = [c for c in children if c not in docs]
            decompose.append({
                "id": row["id"],
                "reason": f"finish minting the declared children "
                          f"(missing: {missing or children}) — "
                          f"{row['reason']}"})
            continue
        if row["id"] in root_ids:
            continue
        retire.append(_retire_row(row["id"], row["reason"]))
    keep = [{"id": r["id"], "name": r["id"]} for r in report["admitted"]]
    baseline: set[str] = set()
    if baseline_file is not None:
        p = Path(baseline_file)
        if p.exists():
            baseline = {ln.strip()
                        for ln in p.read_text(encoding="utf-8").splitlines()
                        if ln.strip()}
    handled = [r["id"] for r in decompose + retire]
    new = sorted(set(handled) - baseline)
    return {"keep": keep, "decompose": decompose, "retire": retire,
            "roots": report["roots"], "bounced": report["bounced"],
            "new_findings": new, "baseline_count": len(baseline)}


# ----------------------------------------------------------------- CLI

def _print_human(report: dict) -> None:
    for row in report.get("admitted", []):
        if row.get("scaffold"):
            print(f"ADMIT   {row['id']}: all-pending scaffold "
                  f"(claims nothing — no contract owed)")
        else:
            print(f"ADMIT   {row['id']}: "
                  f"{row['verification'].get('criterion')}")
    for row in report.get("refused", []):
        print(f"REFUSE  {row['id']}: [{row['class']}] {row['reason']}")
    for row in report.get("decompose", []):
        print(f"DECOMP  {row['id']}: {row['reason']}")
    for row in report.get("retire", []):
        print(f"RETIRE  {row['id']}: [{row['attribution_class']}] "
              f"{row['reason']}")
    for row in report.get("bounced", []):
        print(f"BOUNCE  {row['id']} -> {row['target']}: {row['reason']}")


def main(argv: list[str] | None = None) -> int:
    """CLI: python oracle_case_admission.py <cases_dir> [--sweep] [--json]
    [--baseline-file f]. Exit 0 = clean, 1 = refusals/findings, 2 = bad
    input."""
    ap = argparse.ArgumentParser(
        prog="oracle_case_admission.py",
        description="#301 case minting standard — semantic admission, "
                    "tree/bounce faces, legacy-bank sweep")
    ap.add_argument("cases_dir", help="the <ws>/oracle/cases directory "
                                      "(or any bank of case YAML files)")
    ap.add_argument("--sweep", action="store_true",
                    help="legacy-bank migration diff instead of admission")
    ap.add_argument("--baseline-file",
                    help="sweep ratchet: handled case ids, one per line")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)
    if not Path(args.cases_dir).is_dir():
        print(json.dumps({"error": f"no such cases dir: "
                                   f"{args.cases_dir}"}))
        return 2
    if args.sweep:
        report = sweep(args.cases_dir, args.baseline_file)
        ok = not report["new_findings"] and not report["retire"] \
            and not report["decompose"]
    else:
        report = admit_set(args.cases_dir)
        ok = not report["refused"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
        print("ok" if ok else "refusals present — decompose, bounce, or "
                              "retire (#301)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
