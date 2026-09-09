#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_anchors.py — the three REQUIRED intake answers in task_spec.yaml.

The init interview collects, after the existing needs-first questions, the
three oracle-grade elements the whole loop steers by:

    goal_verbatim        the user's goal, restated verbatim (never
                         paraphrased — the verbatim form is what the
                         completion oracle judges)
    success_criterion    what counts as done (the completion anchor)
    verification_method  how the result is verified — reproduction |
                         replay-evidence | static | manual

Every field is required: a blank field, a non-string value, or a method
outside the enum is a MISSING answer. Missing answers refuse analysis
entry (the `kunglao analysis` gate chain) — the loop never starts on a
guessed anchor, and the script layer never invents one.

Consumers:
  kunglao-init      pre-fills the completion-oracle task_text from the
                    verbatim goal and prints a reminder while answers are
                    missing
  kunglao analysis  refuses entry (rc=7) while any answer is missing
  replay_equivalence.declared_reproduction_qids
                    arms the declared-question set from the method answer
                    (reproduction / replay-evidence arm the
                    controlled-comparison face)

stdlib only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

FIELDS: tuple[str, ...] = (
    "goal_verbatim",
    "success_criterion",
    "verification_method",
)

# The method enum mirrors the declared-bit vocabulary of the controlled-
# comparison oracle: reproduction / replay-evidence arm its face; static
# and manual are different verification modes and arm nothing there.
METHOD_OPTIONS: tuple[str, ...] = (
    "reproduction",
    "replay-evidence",
    "static",
    "manual",
)

REPLAY_ORACLE_METHODS: tuple[str, ...] = ("reproduction", "replay-evidence")

TASK_SPEC_FILENAME = "task_spec.yaml"


def _valid_method(value) -> bool:
    return isinstance(value, str) and value in METHOD_OPTIONS


def _answerable(value) -> bool:
    """A non-blank string answer; anything else is not an answer."""
    return isinstance(value, str) and bool(value.strip())


def missing(task_spec: dict) -> list[str]:
    """Ordered names of the required answers the spec fails to give.

    Fail-closed: a blank value, a non-string, or an out-of-enum method is
    reported missing — callers must never adopt a default for any of them.
    """
    spec = task_spec if isinstance(task_spec, dict) else {}
    out: list[str] = []
    if not _answerable(spec.get("goal_verbatim")):
        out.append("goal_verbatim")
    if not _answerable(spec.get("success_criterion")):
        out.append("success_criterion")
    if not _valid_method(spec.get("verification_method")):
        out.append("verification_method")
    return out


def load(ws) -> dict:
    """The anchor view of <ws>/task_spec.yaml.

    {} when the file is absent or unparseable — callers treat an unreadable
    contract as unanswered (the analysis-entry gate refuses; the init
    reminder prints). Non-mapping files are {} for the same reason.
    """
    path = Path(ws) / TASK_SPEC_FILENAME
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: data.get(name) for name in FIELDS}


def check_ws(ws) -> tuple[bool, list[str]]:
    """(ok, missing) for the analysis-entry gate."""
    return _check(missing(load(ws)))


# ------------------------------------------- state-aware inspection (gate)

STATE_ABSENT = "absent"          # no task_spec.yaml — intake never landed
STATE_CORRUPT = "corrupt"        # unreadable / non-mapping — not repairable
STATE_INCOMPLETE = "incomplete"  # parseable but answers missing
STATE_COMPLETE = "complete"

_CORRUPT_HINT = (
    "task_spec.yaml unreadable - not repairable in place: full re-init "
    "required (kunglao-init <ws> --force --type <type>; the register is "
    "backed up first), analysis entry stays refused until then")

_INCOMPLETE_HINT = (
    "workspace anchors incomplete (%s) - engineering damage or incomplete "
    "init; repair in place, analysis state preserved: "
    "kunglao-init <ws> --resolve <answers.json> (the answers carry the "
    "three anchors; ONLY missing fields are filled, existing answers and "
    "all analysis state untouched)")


def read_state(ws) -> tuple[dict, str]:
    """(anchor view, state) — the state-aware contract read.

    state: STATE_ABSENT (no file) / STATE_CORRUPT (unreadable or a
    non-mapping document) / else the parseable view plus whether the
    required answers are present (STATE_COMPLETE / STATE_INCOMPLETE).
    """
    path = Path(ws) / TASK_SPEC_FILENAME
    if not path.exists():
        return {}, STATE_ABSENT
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}, STATE_CORRUPT
    if not isinstance(data, dict):
        return {}, STATE_CORRUPT
    view = {name: data.get(name) for name in FIELDS}
    return view, (STATE_COMPLETE if not missing(view)
                  else STATE_INCOMPLETE)


def inspect(ws) -> tuple[bool, list[str], str]:
    """(ok, missing, state) — the boundary-gate face."""
    view, state = read_state(ws)
    return (state == STATE_COMPLETE, missing(view), state)


def refusal_hint(gaps: list[str], state: str) -> str:
    """Remediation text: repair-in-place for missing answers, full re-init
    for an unreadable contract. Never a guessed default."""
    if state == STATE_CORRUPT:
        return _CORRUPT_HINT
    return _INCOMPLETE_HINT % ", ".join(gaps)


def validate_values(values: dict) -> None:
    """Fail-closed pre-write validation for repair values: a non-blank
    ``verification_method`` outside the enum raises ValueError (a bad
    answer never lands in the contract)."""
    method = values.get("verification_method")
    if _answerable(method) and not _valid_method(method):
        raise ValueError(
            f"verification_method must be one of "
            f"{' | '.join(METHOD_OPTIONS)}; got {method!r}")


def _check(gaps: list[str]) -> tuple[bool, list[str]]:
    return (not gaps, gaps)


def apply(ws, values: dict) -> Path:
    """Merge the anchor answers into <ws>/task_spec.yaml.

    Creates the file when absent; existing user keys survive untouched and
    an existing non-blank answer is never clobbered (the interview only
    fills blanks). Values must be pre-validated by missing()/the caller.
    """
    path = Path(ws) / TASK_SPEC_FILENAME
    doc: dict = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            loaded = None
        if isinstance(loaded, dict):
            doc = loaded
    for name in FIELDS:
        value = values.get(name)
        if _answerable(value) and not _answerable(doc.get(name)):
            doc[name] = value
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def reminder(ws) -> str:
    """The init stdout line while answers are missing; "" when complete."""
    ok, gaps, state = inspect(ws)
    if ok:
        return ""
    return "kunglao-init: NOTE " + refusal_hint(gaps, state)
