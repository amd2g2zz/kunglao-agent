#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane_spec.py — the task-lane vocabulary of task_spec.yaml (issue 208).

task_spec.yaml was parameterized while the rest of the runtime baked ONE
lane into the substrate: a malware binary under bins/<sha> (RC_NO_SAMPLE
when absent) and the RE toolchain (IDA / Ghidra / frida / unidbg / pefile)
as the only gate. A task whose material is a codec, a protocol capture or
a dataset hit the malware scaffolding on init.

The lane is a DECLARED intake answer — the third axis next to project_type
(environment contract) and the oracle anchors (completion contract):

    lane: malware | algorithm | protocol | web | data | app

Resolution precedence (the shared pending-decision contract: explicit > --resolve
answer > persisted value > pending; a sniff is never a source):

    --lane <lane>  >  --resolve {"lane": ...}  >  task_spec.yaml lane:

An undeclared lane is NOT guessed: a workspace with a task contract (or a
mounted sample) keeps the pre-lane malware default byte-for-byte, and a
workspace that declares nothing at all is ASKED through the exit-8
pending-decision channel (no default). An out-of-enum value fails closed.

Consumers:
    kunglao-init     lane intake (ask / resolve / persist) + render + seeds
    toolchain        per-lane required-check set selection
    hooks/dispatch_gate
                     malware-lane-only agents are refused on a workspace
                     whose declared lane is not malware (the enforcement
                     point — agent markdown cannot refuse to load)

stdlib + yaml only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

# The enum, in ask order. `malware` is first because it is the historical
# contract (a lane-less workspace behaves as malware; see DEFAULT_LEGACY).
LANES: tuple[str, ...] = ("malware", "algorithm", "protocol", "web", "data", "app")

# The pre-lane behavior: a workspace that has a task contract but no lane
# field (or a mounted sample) is the malware lane — never re-interviewed.
DEFAULT_LEGACY = "malware"

# Agent-frontmatter marker: agents whose methodology hard-binds the malware
# binary lane declare `lane: malware` and are refused on other lanes.
MALWARE_ONLY = "malware"

TASK_SPEC_FILENAME = "task_spec.yaml"
LANE_FIELD = "lane"

# The lanes whose routing is IMPLEMENTED end to end. `algorithm` is the
# one that is: no sample required, lane check set, lane render, lane seeds.
IMPLEMENTED_LANES: tuple[str, ...] = ("malware", "algorithm")

# The remaining lanes are documented STUBS (issue 208 scope): init routes
# them, the render states their material and the toolchain gate probes the
# lane's material dir with a WARN — but no lane-specific analysis toolchain
# is claimed. They exist so a protocol/web/data/app task is not forced
# through the malware scaffolding while the deep lanes are built out.
STUB_LANES: tuple[str, ...] = ("protocol", "web", "data", "app")

# What each lane analyzes — the material contract, rendered into the
# workspace handbook and carried in the pending-decision context so the
# agent asks an informed question. The stub lanes say so in their line.
MATERIALS: dict[str, str] = {
    "malware": "binary sample under bins/<sha> (sha256-anchored, VM-only dynamics)",
    "algorithm": "reference corpora + trace dumps (no binary sample; "
                 "run the recovered algorithm against recorded pairs)",
    "protocol": "source dump or live capture (pcaps / frame samples) — "
                "documented stub lane",
    "web": "target URL + auth model — documented stub lane",
    "data": "dataset path + format — documented stub lane",
    "app": "package file with a declared contract surface — documented "
           "stub lane",
}

# Per-lane toolchain item names — the single source toolchain._check_lane
# consumes. `malware` is ABSENT on purpose: the malware lane keeps the
# per-type CHECK_SETS dispatch untouched (byte-identical gate).
REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "algorithm": ("uv", "python", "corpora"),
    "protocol": ("uv", "python", "protocol_material"),
    "web": ("uv", "python", "web_material"),
    "data": ("uv", "python", "data_material"),
    "app": ("uv", "python", "app_material"),
}

# --------------------------------------------- state-aware inspection

STATE_ABSENT = "absent"          # no task_spec.yaml — nothing declared
STATE_CORRUPT = "corrupt"        # unreadable / non-mapping document
STATE_UNDECLARED = "undeclared"  # parseable contract without the lane field
STATE_DECLARED = "declared"      # a lane in the enum
STATE_INVALID = "invalid"        # a lane value outside the enum

_HINT = ("lane must be one of " + " | ".join(LANES)
         + " (or absent: a lane-less contract keeps the malware lane's "
           "current behavior)")


def normalize(value) -> str | None:
    """The enum member for a value, or None when it is not a lane.

    Blank / non-string values are NOT lanes (they are undeclared)."""
    if not isinstance(value, str):
        return None
    lane = value.strip().lower()
    return lane if lane in LANES else None


def material(lane: str) -> str:
    """The lane's material line (empty string for an unknown lane)."""
    return MATERIALS.get(normalize(lane) or "", "")


def validate(value) -> str:
    """Fail-closed validation of a lane answer: ValueError outside the
    enum (a typo never lands in the contract, never silently runs the
    malware lane)."""
    lane = normalize(value)
    if lane is None:
        raise ValueError(f"lane {value!r} is not a lane; {_HINT}")
    return lane


def _read_spec(ws) -> tuple[dict, str]:
    """(document, state) — the raw contract read ({} on absent/corrupt)."""
    path = Path(ws) / TASK_SPEC_FILENAME
    if not path.exists():
        return {}, STATE_ABSENT
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}, STATE_CORRUPT
    if not isinstance(data, dict):
        return {}, STATE_CORRUPT
    return data, STATE_UNDECLARED


def read_state(ws) -> tuple[str | None, str]:
    """(declared lane, state) — the state-aware contract read.

    A blank or missing field is STATE_UNDECLARED (the legacy shape); a
    non-enum value is STATE_INVALID (the caller refuses, never defaults).
    """
    doc, state = _read_spec(ws)
    if state != STATE_UNDECLARED:
        return None, state
    raw = doc.get(LANE_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, STATE_UNDECLARED
    lane = normalize(raw)
    if lane is None:
        return str(raw).strip(), STATE_INVALID
    return lane, STATE_DECLARED


def declared(ws) -> str | None:
    """The valid declared lane, or None (absent / undeclared / corrupt —
    an invalid value is NOT returned; callers use read_state to refuse)."""
    lane, state = read_state(ws)
    return lane if state == STATE_DECLARED else None


def persist(ws, lane: str) -> Path:
    """Record the lane in <ws>/task_spec.yaml (merge, other keys survive).

    Creates the file when absent. The value must be pre-validated by the
    caller — a bad lane never lands here. A file that exists but cannot be
    read as a mapping is REFUSED (ValueError): rewriting it would silently
    replace a damaged contract with a lane-only document."""
    value = validate(lane)
    path = Path(ws) / TASK_SPEC_FILENAME
    doc: dict = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            raise ValueError(
                f"task_spec.yaml unreadable — lane not written: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(
                "task_spec.yaml is not a YAML mapping — lane not written; "
                "repair the contract (full re-init) first")
        doc = loaded
    doc[LANE_FIELD] = value
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def resolve(ws, explicit=None, answers=None,
            ) -> tuple[str | None, str, str | None]:
    """Resolve the lane: (lane, source, error).

    source: "explicit" (--lane) | "answer" (--resolve) | "declared"
            (task_spec.yaml) | "absent" | "corrupt" | "legacy" (a contract
            without the field).
    error: the refusal text when a supplied/declared value is not a lane.

    lane is None for the undeclared states — the CALLER decides between
    the legacy malware default and the exit-8 ask; this module never
    picks one silently.
    """
    answers = answers or {}
    value = explicit
    source = "explicit"
    if value is None:
        answered = answers.get(LANE_FIELD)
        if answered is not None and str(answered).strip():
            value = str(answered)
            source = "answer"
    if value is not None:
        try:
            return validate(value), source, None
        except ValueError as exc:
            return None, source, str(exc)
    lane, state = read_state(ws)
    if state == STATE_DECLARED:
        return lane, "declared", None
    if state == STATE_INVALID:
        return None, "declared", f"task_spec.yaml lane {lane!r} is not a lane; {_HINT}"
    return None, state, None
