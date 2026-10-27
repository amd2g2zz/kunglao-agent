# -*- coding: utf-8 -*-
"""distill_schema.py — the StandardDistillItem schema `distill-item/1`
the distillation domain of the unified RL model.

A distill item is an ADDITIVE `distill` block on an `episode/1` pool
document (episode/1 tolerates additive keys — the envelope-block
precedent): the
pool keeps ONE grain, ONE chain of custody (A2: no parallel store). The
block carries the issue's field table:

    schema             "distill-item/1"
    source_strategy    self | hybrid           (ruling 1: two strategies,
                                               ONE pipeline — only the
                                               collection half differs)
    source_refs        non-empty list of source references
    collection_ts      UTC-Z stamp of the collection act
    content            the methodology skeleton:
                       {branch_table, verdict_algebra, pseudocode_groups}
    scoring            {generality, self_inspiring, methodology, novelty,
                       total, assessor} — 0-1 numbers, per-dimension
                       ALWAYS recorded (never a bare total)
    epistemic_class    evidence-derived | community-claim |
                       external-derived   (the lineage wall's ranking)
    lineage            {supersedes, superseded_by} — the supersedes chain
                       (conflicts are flagged, never silently resolved)
    optimization_rounds  the 3-strike ladder's counter (ruling 5)

The lint is fail-closed: a block failing any field rule raises
DistillSchemaError naming the offending field — an item that can't fill
the schema doesn't exist. Pure module: no IO, no telemetry (Standard 11).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMA = "distill-item/1"

SOURCE_STRATEGIES = ("self", "hybrid")
EPISTEMIC_CLASSES = ("evidence-derived", "community-claim",
                     "external-derived")

REQUIRED_FIELDS = ("schema", "source_strategy", "source_refs",
                   "collection_ts", "content", "scoring",
                   "epistemic_class", "lineage", "optimization_rounds")

SCORING_DIMENSIONS = ("generality", "self_inspiring", "methodology",
                      "novelty")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

#: the supersedes wall: an item of class i may supersede class j only
#: when RANK[i] >= RANK[j] — external-derived never overrides verified
EPISTEMIC_RANK = {"evidence-derived": 2, "community-claim": 1,
                  "external-derived": 0}


class DistillSchemaError(ValueError):
    """A block is not a legal `distill-item/1`. The message names the
    offending field (fail-closed, machine-readable)."""


def _fail(field: str, why: str) -> DistillSchemaError:
    return DistillSchemaError(f"distill.{field}: {why}")


def _req(block: dict, name: str):
    if not isinstance(block, dict) or name not in block:
        raise _fail(name, "missing (schema distill-item/1 requires it)")
    return block[name]


def _lint_scoring(scoring) -> None:
    if not isinstance(scoring, dict):
        raise _fail("scoring", "must be a mapping")
    for dim in SCORING_DIMENSIONS:
        v = scoring.get(dim)
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not (0.0 <= float(v) <= 1.0):
            raise _fail(dim, "must be a number in [0, 1]")
    total = scoring.get("total")
    if not isinstance(total, (int, float)) or isinstance(total, bool) \
            or not (0.0 <= float(total) <= 1.0):
        raise _fail("total", "must be a number in [0, 1]")
    assessor = str(scoring.get("assessor") or "").strip()
    if not assessor:
        raise _fail("assessor",
                    "must name WHO judged (never a bare total)")
    if assessor == "pending":
        # the legal pre-scoring state: dims and total all zero
        if any(float(scoring.get(d) or 0.0) != 0.0
               for d in SCORING_DIMENSIONS) or float(total) != 0.0:
            raise _fail("assessor",
                        '"pending" = the legal pre-scoring state: '
                        "dims and total must all be zero")


def _lint_content(content) -> None:
    if not isinstance(content, dict):
        raise _fail("content", "must be a mapping")
    for part in ("branch_table", "verdict_algebra", "pseudocode_groups"):
        rows = content.get(part)
        if not isinstance(rows, list) \
                or not all(isinstance(r, str) and r.strip()
                           for r in rows):
            raise _fail(f"content.{part}",
                        "must be a list of non-empty strings")
    if not any(content.get(p) for p in
               ("branch_table", "verdict_algebra", "pseudocode_groups")):
        raise _fail("content",
                    "the methodology skeleton needs at least one "
                    "non-empty component")


def _lint_lineage(lineage) -> None:
    if not isinstance(lineage, dict) \
            or not isinstance(lineage.get("supersedes"), str) \
            or not isinstance(lineage.get("superseded_by"), str):
        raise _fail("lineage",
                    "must be {supersedes, superseded_by} id strings")


def lint_block(block) -> dict:
    """Validate one `distill-item/1` block. Returns the block on success;
    raises DistillSchemaError naming the offending field otherwise.
    Pure — no IO, no mutation."""
    if not isinstance(block, dict):
        raise _fail("(root)", "not a mapping")
    if block.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r}")
    for name in REQUIRED_FIELDS:
        _req(block, name)

    if block["source_strategy"] not in SOURCE_STRATEGIES:
        raise _fail("source_strategy",
                    f"must be one of {SOURCE_STRATEGIES}")
    refs = block["source_refs"]
    if not isinstance(refs, list) or not refs \
            or not all(isinstance(r, str) and r.strip() for r in refs):
        raise _fail("source_refs",
                    "must be a non-empty list of reference strings")
    if not isinstance(block["collection_ts"], str) \
            or not _TS_RE.match(block["collection_ts"] or ""):
        raise _fail("collection_ts", "must be a UTC-Z timestamp")

    _lint_content(block["content"])
    _lint_scoring(block["scoring"])

    if block["epistemic_class"] not in EPISTEMIC_CLASSES:
        raise _fail("epistemic_class",
                    f"must be one of {EPISTEMIC_CLASSES}")
    _lint_lineage(block["lineage"])
    rounds = block["optimization_rounds"]
    if not isinstance(rounds, int) or isinstance(rounds, bool) \
            or rounds < 0:
        raise _fail("optimization_rounds", "must be a non-negative int")
    return block


def json_schema() -> dict:
    """The machine-readable JSON-schema face of `distill-item/1`
    (documentation + lint parity; the lint stays the ONE gate)."""
    return {
        "schema": SCHEMA,
        "type": "object",
        "required": list(REQUIRED_FIELDS),
        "properties": {
            "schema": {"const": SCHEMA},
            "source_strategy": {"enum": list(SOURCE_STRATEGIES)},
            "source_refs": {"type": "array",
                            "items": {"type": "string"},
                            "minItems": 1},
            "collection_ts": {"type": "string",
                              "pattern": _TS_RE.pattern},
            "content": {"type": "object", "properties": {
                "branch_table": {"type": "array",
                                 "items": {"type": "string"}},
                "verdict_algebra": {"type": "array",
                                    "items": {"type": "string"}},
                "pseudocode_groups": {"type": "array",
                                      "items": {"type": "string"}}}},
            "scoring": {"type": "object", "properties": {
                **{d: {"type": "number", "minimum": 0, "maximum": 1}
                   for d in SCORING_DIMENSIONS},
                "total": {"type": "number", "minimum": 0, "maximum": 1},
                "assessor": {"type": "string", "minLength": 1}}},
            "epistemic_class": {"enum": list(EPISTEMIC_CLASSES)},
            "lineage": {"type": "object", "properties": {
                "supersedes": {"type": "string"},
                "superseded_by": {"type": "string"}}},
            "optimization_rounds": {"type": "integer", "minimum": 0},
        },
    }


@dataclass(frozen=True)
class StandardDistillItem:
    """The dataclass face: one distilled item = its pool claim id + the
    validated block. Immutable (the pool document is the mutable face)."""
    claim: str
    block: dict = field(repr=False)

    def __post_init__(self) -> None:
        lint_block(self.block)

    @property
    def source_strategy(self) -> str:
        return str(self.block["source_strategy"])

    @property
    def epistemic_class(self) -> str:
        return str(self.block["epistemic_class"])


def item_from_episode(doc: dict) -> StandardDistillItem:
    """Read the distill block off a pool episode document. Raises
    DistillSchemaError when the episode carries no legal block."""
    block = (doc or {}).get("distill")
    if block is None:
        raise _fail("(episode)", "carries no distill block")
    return StandardDistillItem(claim=str(doc.get("claim") or ""),
                               block=lint_block(block))


def lineage_wall_ok(new_class: str, old_class: str) -> bool:
    """The lineage wall: a supersedence may only move UP or level within
    the epistemic ranking — external-derived never overrides verified."""
    return EPISTEMIC_RANK.get(str(new_class), -1) \
        >= EPISTEMIC_RANK.get(str(old_class), -1)
