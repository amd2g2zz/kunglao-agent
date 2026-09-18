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
                    verbatim goal and structurally asks for the answers
                    through the pending-decision channel while they are
                    missing
  kunglao analysis  refuses entry (rc=7) while any answer is missing
  replay_equivalence.declared_reproduction_qids
                    arms the declared-question set from the method answer
                    (reproduction / replay-evidence arm the
                    controlled-comparison face)

stdlib only.
"""
from __future__ import annotations

import re

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


# ------------------------------------------- generation-language ----
# Users speak folk (folk-in lineage): an algorithm-class ask is detected
# from the verbatim goal, never from the user's vocabulary. A generation-
# language goal asks HOW the artifact is produced — a generation-side
# proposition — so the only admissible verification method is the
# reproduction oracle; acceptance-side observational methods (replay-
# evidence, static, manual) are refused for it.
GENERATION_LANGUAGE_MARKERS: tuple[str, ...] = (
    "怎么生成", "怎样生成", "如何生成", "怎么算", "怎样算", "怎么计算",
    "如何计算", "什么原理", "什么算法", "如何构造", "怎么构造", "怎么来的",
    "怎么实现的", "如何实现",
    "how is it computed", "how is it generated", "how is it constructed",
    "how is it derived", "what algorithm", "is computed", "is generated",
    "is constructed",
)

# English interrogative + computation verb need not be adjacent
# ("how is the signature computed") — a word-pattern fallback covers the
# gap the substring markers cannot.
_EN_INTERROGATIVE_RE = r"\b(how|what)\b"
_EN_COMPUTATION_VERB_RE = (
    r"\b(computed|generated|constructed|derived|calculated|signed)\b")


def is_generation_language(goal) -> bool:
    """True when the verbatim goal asks how something is GENERATED
    (an algorithm-class question). Case-insensitive substring match over
    the marker set, plus an interrogative + computation-verb word
    pattern ("how is the signature computed"); non-string input is not
    algorithm-class."""
    if not isinstance(goal, str):
        return False
    text = goal.strip().lower()
    if any(m in text for m in GENERATION_LANGUAGE_MARKERS):
        return True
    return bool(re.search(_EN_INTERROGATIVE_RE, text)
                and re.search(_EN_COMPUTATION_VERB_RE, text))


def derive_verification_method(task_spec: dict) -> str | None:
    """The verification method the SYSTEM derives from the spec.

    A generation-language goal pins ``reproduction`` regardless of what
    was selected; otherwise the spec's own answer (None when absent or
    out of enum — the missing() gate still owns that refusal)."""
    spec = task_spec if isinstance(task_spec, dict) else {}
    if is_generation_language(spec.get("goal_verbatim")):
        return "reproduction"
    method = spec.get("verification_method")
    return method if _valid_method(method) else None


def intake_method_gate(task_spec: dict) -> tuple[bool, str]:
    """(ok, reason) for the intake method selection (piece 1).

    An algorithm-class goal may ONLY carry ``reproduction``: the weak
    observational selection (replay-evidence / static / manual) is
    refused with the reason naming the weak method. A missing method is
    not this gate's refusal (missing() owns it)."""
    spec = task_spec if isinstance(task_spec, dict) else {}
    if not is_generation_language(spec.get("goal_verbatim")):
        return True, ""
    method = spec.get("verification_method")
    if not _valid_method(method):
        return True, ""
    if method == "reproduction":
        return True, ""
    return False, (
        f"algorithm-class goal (generation language in goal_verbatim): "
        f"{method!r} is not selectable — the reproduction oracle is the "
        f"only admissible verification method for a generation-side "
        f"proposition (#248)")


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
    intake asks). Non-mapping files are {} for the same reason.
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
    answer never lands in the contract). A generation-language goal with a
    weak observational method is refused the same way (the
    reproduction oracle is the only admissible verification method for an
    algorithm-class ask — the weak selection never lands)."""
    method = values.get("verification_method")
    if _answerable(method) and not _valid_method(method):
        raise ValueError(
            f"verification_method must be one of "
            f"{' | '.join(METHOD_OPTIONS)}; got {method!r}")
    ok, reason = intake_method_gate(values)
    if not ok:
        raise ValueError(reason)


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
