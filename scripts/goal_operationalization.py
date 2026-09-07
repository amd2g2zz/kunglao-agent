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

Rules (the mechanical half — the ONE-round user confirmation is protocol
text, skills/kunglao-agent/SKILL.md "Goal operationalization read-back"):

  R1 not_done must be non-empty: a goal without counterexamples is
     unaudited (capability substitution and scope narrowing hide exactly
     there; every later step is "honest" against a narrowed goal).
  R2 diff_vs_verbatim must be non-empty and may not rubber-stamp identity
     ("identical to the verbatim task" = silent equivalence, refused).
  R3 capability rule: deliverables implying a reproducible capability
     (decrypt / extract-key / offline-reproduce family) require derived
     probe cases — validation refuses otherwise.
  R4 edit != confirmed: a confirmed file whose content hash no longer
     matches confirmed_sha256 validates as pending-confirmation again;
     re-scope forces re-confirmation (the agent cannot silently rewrite).

File IO mirrors scripts/hypothesis_store.py (read -> parse -> validate;
writes happen only through confirm(), which refuses to seal an invalid
file). Loud rejection (GoalOpError) for unreadable files and unknown
schema versions — no fail-open on the version wall.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

SCHEMA_ID = "goal-operationalization/1"
STATUS_PENDING = "pending-confirmation"
STATUS_CONFIRMED = "confirmed"
STATUSES = (STATUS_PENDING, STATUS_CONFIRMED)

# Payload fields — the goal content whose hash seals a confirmation (R4).
# The optional oracle_behavior_acknowledged flag and the status/seal fields
# themselves are bookkeeping, not goal content, and stay outside the hash.
PAYLOAD_FIELDS = ("verbatim_ref", "deliverables", "acceptance", "not_done",
                  "diff_vs_verbatim", "probe_cases")
LIST_FIELDS = PAYLOAD_FIELDS[1:]

# R3: deliverable text implying a reproducible capability (substring,
# case-insensitive; fail-closed — a false hit only demands probe cases).
CAPABILITY_MARKERS = (
    "decrypt", "extract", "recover", "reproduce", "offline",
    "unpack", "regenerat", "deobfuscat", "emulat",
)

# R2: literal identity claims are rubber stamps, not declared deltas.
RUBBER_STAMPS = frozenset((
    "identical to the verbatim task", "same as the verbatim task",
    "no delta", "no difference", "none",
))


class GoalOpError(ValueError):
    """Loud rejection: unreadable/malformed file or unknown schema version."""


def content_hash(doc: dict) -> str:
    """sha256 over the canonical JSON of the payload fields only (R4)."""
    payload = {k: doc.get(k) for k in PAYLOAD_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def implies_capability(deliverables: list) -> bool:
    text = " ".join(deliverables).lower()
    return any(marker in text for marker in CAPABILITY_MARKERS)


def _string_list(doc: dict, name: str) -> list:
    value = doc.get(name)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _content_errors(doc: dict, capability: bool) -> list[str]:
    """R1-R3: the content rules over the five list fields."""
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
    if capability and not _string_list(doc, "probe_cases"):
        errors.append(
            "probe_cases: empty while deliverables imply a reproducible "
            "capability — derive the fresh-input / no-dependency / "
            "materialized-artifact cases at Phase 0")
    return errors


def _status_errors(doc: dict) -> tuple[list[str], str, bool]:
    """R4: status/seal rules. Returns (errors, effective_status, rescoped)."""
    errors: list[str] = []
    status = doc.get("status")
    effective, rescoped = STATUS_PENDING, False
    if status not in STATUSES:
        errors.append(f"status: must be one of {STATUSES}, got {status!r}")
        return errors, effective, rescoped
    effective = status
    if status == STATUS_CONFIRMED:
        sealed = doc.get("confirmed_sha256") or ""
        if not sealed:
            errors.append(
                "confirmed_sha256: empty on a confirmed file — confirmation "
                "without a content seal is a claim, not a fact")
        elif sealed != content_hash(doc):
            # R4: edit != confirmed — content moved after the seal
            effective, rescoped = STATUS_PENDING, True
    return errors, effective, rescoped


def validate(doc: dict) -> dict:
    """Structural + rule validation. Returns a report dict; raises
    GoalOpError only on the type/schema walls (loud, no fail-open)."""
    if not isinstance(doc, dict):
        raise GoalOpError("goal operationalization must be a YAML mapping")
    if doc.get("schema") != SCHEMA_ID:
        raise GoalOpError(
            f"schema mismatch: expected {SCHEMA_ID!r}, got {doc.get('schema')!r} "
            "— refusing an unknown format (no-backcompat policy)")
    capability = implies_capability(_string_list(doc, "deliverables"))
    status_errors, effective, rescoped = _status_errors(doc)
    errors = _content_errors(doc, capability) + status_errors
    return {"schema": SCHEMA_ID, "errors": errors, "capability": capability,
            "status": doc.get("status"), "effective_status": effective,
            "rescoped": rescoped}


def confirm(doc: dict) -> dict:
    """Seal a VALID pending file: returns a new dict with status confirmed
    and the content hash. Refuses to confirm an invalid file."""
    report = validate(doc)
    if report["errors"]:
        raise GoalOpError(
            "refusing to confirm an unaudited operationalization: "
            + "; ".join(report["errors"]))
    return dict(doc, status=STATUS_CONFIRMED, confirmed_sha256=content_hash(doc))


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
        description="goal-operationalization validator (#128): validate or "
                    "seal a workspace goal-operationalization.yaml")
    parser.add_argument("file", help="path to goal-operationalization.yaml")
    parser.add_argument("--confirm", action="store_true",
                        help="seal a valid pending file (writes status: "
                             "confirmed + confirmed_sha256)")
    args = parser.parse_args(argv)
    try:
        doc = load(args.file)
        if args.confirm:
            doc = confirm(doc)
            dump(args.file, doc)
        report = validate(doc)
    except GoalOpError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
