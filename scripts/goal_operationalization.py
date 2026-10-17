#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goal_operationalization.py — Phase-0 goal operationalization validator (#128).

The user's task stays VERBATIM in <ws>/task-oracle.yaml (#473, unchanged);
the goal -> operationalization translation lives beside it in
<ws>/goal-operationalization.yaml and is the audited artifact:

    deliverables:      what counts as delivered
    acceptance:        how a deliverable is checked
    not_done:          counterexamples — "X does not count as done"
    diff_vs_verbatim:  declared delta vs the verbatim task
    probe_cases:       fresh-input / no-dependency / materialized-artifact
    generalization:    declared structural bit — required | not-applicable |
                       unknown
    constraint_witness: per-row mechanical witnesses for not_done (schema
                       constraint-witness/1): exactly one of
                       check: <command> (exit 0 = constraint holds) or
                       none: <reason> (explicitly unwitnessable)

Rules (mechanical; per the owner amendments there is NO user confirmation
round — the human lives at the verbatim task and at the delivery receipt):

  R1 not_done must be non-empty: a goal without counterexamples is
     unaudited (capability substitution and scope narrowing hide exactly
     there; every later step is "honest" against a narrowed goal).
  R2 diff_vs_verbatim must be non-empty and may not rubber-stamp identity
     ("identical to the verbatim task" = silent equivalence, refused).
  R3 declared generalization bit (task taxonomy is un-enumerable — nobody
     classifies the task, the machine holds the declaration): one
     structural question — must the deliverable work on inputs beyond the
     captured/observed evidence? required/unknown => probe_cases must
     include the fresh-input case (fail-closed; for client simulation the
     fresh-input case IS the master oracle, replay is the ladder, never
     the closure); not-applicable => the non-generalization MUST also
     appear as an explicit diff_vs_verbatim entry (declaring it is a
     narrowing, made visible). Missing/invalid value = loud rejection.
  R4 pre-registration is timestamped (declared_ts) — an unstamped
     translation is not a record.
  R5 post-dispatch the file is append-only: --stamp-dispatch freezes the
     constitution (the five lists + generalization + the witness block);
     from then on dropping or rewording a not_done / deliverables /
     acceptance entry is REFUSED (an edit that contradicts the
     constitution), generalization never flips, and every other drift
     becomes a re-scope record that the
     delivery receipt must restate. Delivery restates the not_done list +
     the generalization declaration (restatement()) — that is the user's
     audit point; ask_for_direction stays the only escalation channel.
  R6 every not_done counterexample carries a mechanical witness under
     `constraint_witness` (schema constraint-witness/1): one entry per
     not_done row binding exactly one of `check: <command>` (exit 0 = the
     constraint holds at the delivered workspace) or `none: <reason>` (an
     explicit declaration that no mechanical witness exists). A row with
     no witness is refused here — settlement prices the row jointly
     (verdict = witness AND outcome), so an unwitnessed row would be
     reward-blind.

File IO mirrors scripts/hypothesis_store.py (read -> parse -> validate;
writes happen only through stamp_dispatch(), which refuses an unaudited
file). Loud rejection (GoalOpError) for unreadable files, unknown schema
versions, and an undeclared generalization bit — no fail-open walls.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_ID = "goal-operationalization/1"
WITNESS_SCHEMA = "constraint-witness/1"
GENERALIZATION_VALUES = ("required", "not-applicable", "unknown")

LIST_FIELDS = ("deliverables", "acceptance", "not_done", "diff_vs_verbatim",
               "probe_cases")
# The post-dispatch constitution: entries here survive verbatim (append-only).
CONSTITUTION_FIELDS = ("deliverables", "acceptance", "not_done")
FRESH_INPUT_MARKERS = ("fresh-input", "fresh input")
NOT_APPLICABLE_MARKERS = ("not-applicable", "not applicable")

# R2: literal identity claims are rubber stamps, not declared deltas.
RUBBER_STAMPS = frozenset((
    "identical to the verbatim task", "same as the verbatim task",
    "no delta", "no difference", "none",
))


class GoalOpError(ValueError):
    """Loud rejection: unreadable/malformed file, unknown schema version,
    or an undeclared generalization bit."""


def _string_list(doc: dict, name: str) -> list:
    value = doc.get(name)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def witness_block(doc: dict) -> dict | None:
    """The declared constraint-witness block, or None when absent or not
    a mapping (the shape the lint and the oracle both read)."""
    block = doc.get("constraint_witness")
    return block if isinstance(block, dict) else None


def witness_map(doc: dict) -> dict:
    """{not_done row: witness spec} — {} when the block is absent, not a
    mapping, or carries a foreign schema."""
    block = witness_block(doc)
    if not block or block.get("schema") != WITNESS_SCHEMA:
        return {}
    witnesses = block.get("witnesses")
    return dict(witnesses) if isinstance(witnesses, dict) else {}


def _witness_spec_error(spec) -> str | None:
    """R6 spec shape: a mapping with exactly one non-empty check/none."""
    if not isinstance(spec, dict):
        return "witness spec must be a mapping (check: or none:)"
    check, none = spec.get("check"), spec.get("none")
    has_check = isinstance(check, str) and bool(check.strip())
    has_none = isinstance(none, str) and bool(none.strip())
    if has_check == has_none:
        return ("needs exactly one of check: (exit 0 = the constraint "
                "holds) or none: <reason>")
    extra = sorted(k for k in spec if k not in ("check", "none"))
    if extra:
        return f"unknown witness keys: {', '.join(str(k) for k in extra)}"
    return None


def _witness_errors(doc: dict) -> list[str]:
    """R6: every not_done row binds 1:1 to a witness declaration."""
    rows = _string_list(doc, "not_done")
    if not rows:
        return []
    block = witness_block(doc)
    if block is None:
        return ["constraint_witness: missing — every not_done entry needs "
                "a mechanical witness (check:) or an explicit declaration "
                "(none: reason)"]
    if block.get("schema") != WITNESS_SCHEMA:
        return [f"constraint_witness.schema: expected {WITNESS_SCHEMA!r}, "
                f"got {block.get('schema')!r} — refusing an unknown "
                "witness format"]
    witnesses = block.get("witnesses")
    if not isinstance(witnesses, dict):
        return ["constraint_witness.witnesses: must be a mapping of "
                "not_done entry -> witness spec"]
    errors: list[str] = []
    for row in rows:
        if row not in witnesses:
            errors.append(f"constraint_witness: not_done entry has no "
                          f"mechanical witness ({row!r}) — declare check: "
                          "<command> or none: <reason>")
            continue
        spec_error = _witness_spec_error(witnesses[row])
        if spec_error:
            errors.append(f"constraint_witness: {row!r} {spec_error}")
    for key in witnesses:
        if key not in rows:
            errors.append(f"constraint_witness: {key!r} is not a declared "
                          "not_done entry — witnesses bind 1:1 to the "
                          "constitution")
    return errors


def _generalization_errors(bit: str, diff: list, probes: list) -> list[str]:
    """R3: the declared structural bit — fail-closed on both sides."""
    errors: list[str] = []
    if bit == "not-applicable":
        if not any(m in " ".join(diff).lower()
                   for m in NOT_APPLICABLE_MARKERS):
            errors.append(
                "generalization: not-applicable must also be declared as an "
                "explicit diff_vs_verbatim entry — a non-generalization "
                "claim is a scope narrowing and becomes visible")
        return errors
    if not probes:  # required | unknown — fail-closed
        errors.append(
            "probe_cases: empty while generalization is "
            f"{bit!r} — derive the fresh-input / no-dependency / "
            "materialized-artifact cases")
    elif not any(m in " ".join(probes).lower()
                 for m in FRESH_INPUT_MARKERS):
        errors.append(
            "probe_cases: the fresh-input case is mandatory when "
            f"generalization is {bit!r} — generate-valid-output-for-"
            "never-captured-inputs is the master oracle, replay is "
            "only the ladder")
    return errors


def _content_errors(doc: dict) -> list[str]:
    """R1-R4: the content rules over the declared lists + the bit."""
    errors: list[str] = []
    for name in LIST_FIELDS:
        if _string_list(doc, name) != (doc.get(name) or []):
            errors.append(f"{name}: must be a list of non-empty strings")
    if not _string_list(doc, "deliverables"):
        errors.append(
            "deliverables: empty — an operationalization must name what "
            "counts as delivered")
    if not _string_list(doc, "not_done"):
        errors.append(
            "not_done: empty — a goal without not-done counterexamples is "
            "unaudited (the load-bearing half, #128)")
    diff = _string_list(doc, "diff_vs_verbatim")
    if not diff:
        errors.append(
            "diff_vs_verbatim: empty — silent equivalence; declare the "
            "delta vs the verbatim task")
    else:
        for entry in diff:
            if entry.strip().lower() in RUBBER_STAMPS:
                errors.append(
                    f"diff_vs_verbatim: {entry.strip()!r} is a rubber stamp "
                    "— silent equivalence is refused")
    errors += _generalization_errors(
        doc["generalization"], diff, _string_list(doc, "probe_cases"))
    errors += _witness_errors(doc)
    if not (doc.get("declared_ts") or "").strip():
        errors.append(
            "declared_ts: empty — a pre-registration without a timestamp "
            "is not a record")
    return errors


def _constitution_errors(doc: dict) -> list[str]:
    """R5 refusal face: post-dispatch edits that contradict the frozen
    constitution (drop/reword of a declared entry, generalization flip)."""
    con = doc.get("constitution")
    if not isinstance(con, dict):
        return ["constitution: missing on a dispatched file — stamp with "
                "--stamp-dispatch before the first dispatch"]
    errors: list[str] = []
    for name in CONSTITUTION_FIELDS:
        frozen = [e for e in (con.get(name) or []) if isinstance(e, str)]
        current = _string_list(doc, name)
        for entry in frozen:
            if entry not in current:
                errors.append(
                    f"{name}: post-dispatch withdrawal refused — a declared "
                    f"entry may not be withdrawn ({entry!r} left the "
                    "append-only constitution)")
    if doc["generalization"] != con.get("generalization"):
        errors.append(
            "generalization: post-dispatch flip refused — the declared bit "
            "is immutable; narrowing goes through ask_for_direction, never "
            "a silent edit")
    frozen_w = con.get("constraint_witness")
    if isinstance(frozen_w, dict) and frozen_w:
        if witness_block(doc) is None:
            errors.append(
                "constraint_witness: post-dispatch withdrawal refused — "
                "the frozen witness block left the append-only "
                "constitution")
        else:
            current = witness_map(doc)
            for row, spec in frozen_w.items():
                if current.get(row) != spec:
                    errors.append(
                        "constraint_witness: post-dispatch witness "
                        f"withdrawal/weakening refused ({row!r})")
    return errors


def _rescope_records(doc: dict) -> list[str]:
    """R5 record face: post-dispatch drift the delivery receipt must
    restate (appends to the constitution lists, edits to the soft fields)."""
    con = doc.get("constitution")
    if not isinstance(con, dict):
        return []  # hand-corrupted constitution: the refusal face already fired
    records: list[str] = []
    for name in LIST_FIELDS:
        frozen = {e for e in (con.get(name) or []) if isinstance(e, str)}
        current = [e for e in _string_list(doc, name) if e not in frozen]
        if current:
            records.append(f"{name}: +{len(current)} appended post-dispatch")
        dropped = len([e for e in (con.get(name) or [])
                       if isinstance(e, str)]) - (
            len(_string_list(doc, name)) - len(current))
        if name not in CONSTITUTION_FIELDS and dropped > 0:
            records.append(
                f"{name}: {dropped} entry(ies) dropped post-dispatch — "
                "delivery must restate")
    return records


def validate(doc: dict) -> dict:
    """Structural + rule validation. Returns a report dict; raises
    GoalOpError only on the walls (type/schema/generalization — loud)."""
    if not isinstance(doc, dict):
        raise GoalOpError("goal operationalization must be a YAML mapping")
    if doc.get("schema") != SCHEMA_ID:
        raise GoalOpError(
            f"schema mismatch: expected {SCHEMA_ID!r}, got {doc.get('schema')!r} "
            "— refusing an unknown format (no-backcompat policy)")
    bit = doc.get("generalization")
    if bit not in GENERALIZATION_VALUES:
        raise GoalOpError(
            f"generalization: must be one of {GENERALIZATION_VALUES}, got "
            f"{bit!r} — the structural bit is declared, never inferred")
    post_dispatch = bool((doc.get("first_dispatch_ts") or "").strip())
    errors = _content_errors(doc)
    rescopes: list[str] = []
    if post_dispatch:
        errors += _constitution_errors(doc)
        rescopes = _rescope_records(doc)
    return {"schema": SCHEMA_ID, "errors": errors, "rescopes": rescopes,
            "post_dispatch": post_dispatch,
            "generalization": bit}


def stamp_dispatch(doc: dict, ts: str) -> dict:
    """R5 entry act: freeze the constitution + stamp the first dispatch.
    Refuses an already-stamped or unaudited file. Returns a new dict."""
    report = validate(doc)
    if (doc.get("first_dispatch_ts") or "").strip():
        raise GoalOpError(
            f"already stamped at {doc['first_dispatch_ts']!r} — the "
            "constitution freezes once")
    if report["errors"]:
        raise GoalOpError(
            "refusing to stamp an unaudited operationalization: "
            + "; ".join(report["errors"]))
    constitution = {"generalization": doc["generalization"]}
    for name in LIST_FIELDS:
        constitution[name] = list(_string_list(doc, name))
    constitution["constraint_witness"] = copy.deepcopy(witness_map(doc))
    return dict(doc, first_dispatch_ts=ts, constitution=constitution)


def restatement(doc: dict) -> str:
    """The delivery-receipt audit block: the not_done constitution and the
    generalization declaration, restated verbatim (A3 item 4)."""
    lines = [
        "goal operationalization — delivery audit (#128)",
        f"generalization: {doc.get('generalization')!r} "
        f"(declared {doc.get('declared_ts')!r})",
        "not done — none of the following counts as done:",
    ]
    lines += [f"- {e}" for e in _string_list(doc, "not_done")]
    if doc.get("first_dispatch_ts"):
        lines.append(f"first dispatch: {doc['first_dispatch_ts']}")
    return "\n".join(lines)


def load(path) -> dict:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoalOpError(f"unreadable {p}: {exc}") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GoalOpError(f"malformed YAML {p}: {exc}") from exc
    if not isinstance(doc, dict):
        raise GoalOpError(f"{p}: top level must be a mapping")
    return doc


def dump(path, doc: dict) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="goal-operationalization validator (#128): validate, "
                    "stamp the first dispatch, or print the delivery "
                    "restatement for a workspace goal-operationalization.yaml")
    parser.add_argument("file", help="path to goal-operationalization.yaml")
    parser.add_argument("--stamp-dispatch", action="store_true",
                        help="freeze the constitution + stamp "
                             "first_dispatch_ts (first dispatch only)")
    parser.add_argument("--restatement", action="store_true",
                        help="print the delivery-audit block (not_done + "
                             "generalization) for the final report")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        doc = load(args.file)
        if args.stamp_dispatch:
            doc = stamp_dispatch(doc, now)
            dump(args.file, doc)
        report = validate(doc)
        if args.restatement:
            print(restatement(doc))
    except GoalOpError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    if not args.restatement:
        print(json.dumps(report, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
