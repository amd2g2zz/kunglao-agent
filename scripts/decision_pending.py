#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decision_pending.py — shared pending-decision schema (#455; #449/#451 base).

Architecture rule (#455): scripts NEVER read stdin as a user channel —
stdin in Claude Code is not the user and isatty is untrustworthy. When a
flow needs a user decision it CANNOT make itself, it prints a
PendingDecisionList JSON document (stdout, machine channel) and exits with
the caller's pending exit code; the AGENT layer collects the answers via
Claude Code's native question capability and re-runs the CLI with
`--resolve <answers.json>`.

This module owns ONLY the data shape + serialization + answers loading —
no kunglao-init coupling, no I/O policy. Consumers:
  #455 kunglao-init intake step 0 — decision ids: workspace / target /
      target_object / type (this change).
  #449 needs-first intake — appends primary_questions / scope / depth
      decisions with flow="kunglao-init", same --resolve re-entry.
  #451 negotiation menu — install-consent / menu items as kind="choice"
      decisions replacing the remaining headless-refuse paths.

Precedence contract (shared by all consumers): explicit CLI flag >
--resolve answer > persisted state > pending (the pending list is the
floor, never a source of silent values). Answer keys the consumer does not
know are ignored (forward compatibility).

stdlib only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1"

KIND_CHOICE = "choice"
KIND_VALUE = "value"

# The guidance every pending emitter reuses (kept here so all consumers
# phrase the re-entry contract identically).
GUIDANCE_TEMPLATE = (
    "Collect answers for each decision via the Claude Code native "
    "question capability (never script stdin), write them to a JSON file "
    "as {decision_id: value}, and re-run with --resolve <answers.json>."
)


@dataclass(frozen=True)
class PendingDecision:
    """One undecided user decision, phrased for the agent to relay.

    kind: "choice" — options enumerated, answer must be one of them
          "value"  — free-form string answer (e.g. a workspace path)
    default: a suggested-but-NOT-adopted value (informational only; the
             emitter never acts on a default — that is the whole point of
             pending). None when there is nothing safe to suggest.
    context: machine-readable extras the agent uses to ask an informed
             question (bins survey, container contents, sniff suggestion).
    """
    decision_id: str
    question: str
    kind: str
    options: tuple[str, ...] = ()
    default: str | None = None
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PendingDecisionList:
    """The full pending document: what is undecided and how to re-enter."""
    flow: str                      # e.g. "kunglao-init"
    workspace: str | None          # resolved workspace, when one exists
    guidance: str                  # how the agent re-enters (--resolve)
    decisions: list[PendingDecision]  # in interaction order
    resume: dict = field(default_factory=dict)  # re-entry command template

    def to_json(self) -> str:
        return json.dumps({
            "schema_version": SCHEMA_VERSION,
            "flow": self.flow,
            "workspace": self.workspace,
            "guidance": self.guidance,
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "question": d.question,
                    "kind": d.kind,
                    "options": list(d.options),
                    "default": d.default,
                    "context": d.context,
                }
                for d in self.decisions
            ],
            "resume": self.resume,
        }, indent=2, ensure_ascii=False)


def answers_from_json(text: str) -> dict[str, str]:
    """Parse a --resolve answers payload: must be a JSON object of
    {decision_id: string}. Fail-closed ValueError on anything else."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"answers file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("answers payload must be a JSON object "
                         "{decision_id: value}")
    for key, value in data.items():
        if not isinstance(value, str):
            raise ValueError(f"answer for {key!r} must be a string, "
                             f"got {type(value).__name__}")
    return data


def load_answers(path: Path) -> dict[str, str]:
    """Read + parse an answers file; ValueError on missing/unreadable/
    unparseable content (fail-closed — never an empty dict silently)."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"answers file unreadable: {p} ({exc})") from exc
    return answers_from_json(text)
