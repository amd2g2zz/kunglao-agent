#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intake_draft.py — bounded-intelligent intake draft (intake v2, design §3).

The intake dialogue's durable face. The DRAFT distillation
(``primary_questions`` first-class — addendum 1 — plus deliverables /
acceptance / not_done / diff_vs_verbatim) is drafted from the verbatim
task, shown to the user, and CONFIRMED before ``declared_ts`` is
stamped. The intelligence lives in the drafting (the dialogue); the
authority stays with the user (the confirm wall); the structural-seed
constitution is NOT reopened — init seeds stay structural facts, the machine validates,
it never invents analysis.

Surfaces
--------
  runs/intake-draft.yaml  schema ``intake-draft/1``: the draft + the
                          classification consequence echo (lane ->
                          prescan battery / difficulty factor set /
                          capability vocabulary, §3 last bullet) written
                          by init at scaffold time (confirmed: false,
                          declared_ts: ""), never clobbered.
  confirm(ws, answers)    the one stamping path: validates the answers
                          (non-empty primary questions in the canonical
                          parse, non-rubber-stamp diff, non-empty
                          not_done — R2/R1 discipline), records the
                          confirmation, merges primary_questions into
                          task_spec.yaml, fills the DRAFT
                          goal-operationalization lists and stamps its
                          declared_ts. A stamped goal-op (a legacy
                          workspace) is never touched.

Enforcement semantics (addendum 1 decision): the goal-operationalization
scaffold ships UNSTAMPED — the existing declared_ts gate (the convergence
INVALID face, R4 "an unstamped translation is not a record") is what
makes the confirm dialogue un-skippable; obligations that are only
taught, never gated, get skipped under pressure.

stdlib + yaml only.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SCHEMA = "intake-draft/1"
DRAFT_REL = Path("runs") / "intake-draft.yaml"
GOAL_OP_NAME = "goal-operationalization.yaml"

# the fields confirm() copies from the answers into the draft + goal-op.
# probe_cases is copied WHEN PRESENT (R3 still enforces it at the loop
# face for generalization=required) — the issue's draft quartet stays the
# required core.
DRAFT_LIST_FIELDS = ("deliverables", "acceptance", "not_done",
                     "diff_vs_verbatim")
OPTIONAL_LIST_FIELDS = ("probe_cases",)

# the R6 witness block rides the answers verbatim (schema-checked at the
# goal-op validator; confirm copies, never authors)
WITNESS_FIELD = "constraint_witness"


class IntakeDraftError(ValueError):
    """Loud rejection: missing/invalid answers, a second confirm, or a
    conflicting task_spec — the wall is mechanical, never silent."""


def _answers_list(answers: dict, name: str) -> list[str]:
    value = answers.get(name)
    if isinstance(value, str):
        value = [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value
            if isinstance(v, str) and v.strip()]


def _classification_echo(ws: Path) -> dict:
    """The task-type consequence the user confirms AGAINST (§3: the
    classification's consequence is echoed back at confirm time)."""
    import lane_profile
    lane = None
    ptype = None
    spec_path = Path(ws) / "task_spec.yaml"
    try:
        spec = (yaml.safe_load(spec_path.read_text(encoding="utf-8"))
                if spec_path.is_file() else None)
        if isinstance(spec, dict):
            lane = spec.get("lane")
            ptype = spec.get("project_type")
        if not (isinstance(lane, str) and lane.strip()):
            import lane_spec
            declared = lane_spec.declared(Path(ws))
            lane = declared if isinstance(declared, str) else None
    except Exception as exc:  # noqa: BLE001 — degrade to a raw echo, loudly
        print(f"intake-draft: WARN (fail-open) classification probe failed "
              f"({type(exc).__name__}: {exc})", file=sys.stderr)
    exact = True
    try:
        prof, exact = lane_profile.profile_for(lane)
    except Exception:  # noqa: BLE001 — registry unreadable: empty echo
        prof = {}
    return {
        "lane": str(lane) if lane else None,
        "project_type": str(ptype) if ptype else None,
        "prescan_probes": tuple(prof.get("prescan_probes") or ()),
        "difficulty_factor_set": str(prof.get("factor_set") or "binary"),
        "capabilities": tuple(prof.get("capabilities") or ()),
        "registry_matched": exact,
    }


def _goal_verbatim(ws: Path) -> str:
    spec_path = Path(ws) / "task_spec.yaml"
    try:
        spec = (yaml.safe_load(spec_path.read_text(encoding="utf-8"))
                if spec_path.is_file() else None)
        goal = spec.get("goal_verbatim") if isinstance(spec, dict) else None
        return str(goal) if goal else "(goal_verbatim not yet anchored)"
    except Exception:  # noqa: BLE001 — unreadable contract: placeholder
        return "(goal_verbatim not yet anchored)"


def draft_path(ws: Path) -> Path:
    return Path(ws) / DRAFT_REL


def scaffold(ws: Path) -> Path:
    """Write the unconfirmed draft (idempotent: an existing draft is
    never clobbered — it may already carry dialogue edits)."""
    out = draft_path(ws)
    if out.exists():
        return out
    doc = {
        "schema": SCHEMA,
        "confirmed": False,
        "declared_ts": "",
        "goal_verbatim": _goal_verbatim(ws),
        "classification": _classification_echo(ws),
        "primary_questions": [],
        "deliverables": [],
        "acceptance": [],
        "not_done": [],
        "diff_vs_verbatim": [],
        "classification_confirmed": False,
        "note": ("draft the distillation from the verbatim task during "
                 "the intake dialogue, show it to the user, then "
                 "confirm: intake_draft.py <ws> --confirm answers.yaml "
                 "(declared_ts stamps ONLY at confirm)"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    return out


def load(ws: Path) -> dict | None:
    p = draft_path(ws)
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def _validate_pqs(raw) -> list[dict]:
    """primary_questions first-class (addendum 1): the canonical parse is
    THE single shape authority (convergence_check's parser — the same
    function the loop's INVALID face enforces with)."""
    from convergence_check import _parse_primary_questions
    if not raw:
        raise IntakeDraftError(
            "primary_questions: empty — the confirmed draft carries the "
            "questions the whole value function is derived from "
            "(first-class output of the intake draft)")
    questions, err = _parse_primary_questions({"primary_questions": raw})
    if err:
        raise IntakeDraftError(f"primary_questions: {err}")
    return questions


def _confirm_write_draft(ws: Path, draft: dict, fields: dict,
                         answers: dict, ts: str, report: dict) -> Path:
    """Confirm phase 1: write the confirmed draft record (immutable
    after confirm — R5's constitution discipline starts here, at the
    pre-registration)."""
    draft.update({
        "confirmed": True,
        "declared_ts": ts,
        "classification_confirmed": True,
        "primary_questions": list(answers.get("primary_questions") or []),
    })
    for name in DRAFT_LIST_FIELDS + OPTIONAL_LIST_FIELDS:
        draft[name] = fields[name]
    out = draft_path(ws)
    out.write_text(yaml.safe_dump(draft, allow_unicode=True,
                                  sort_keys=False), encoding="utf-8")
    return out


def _confirm_task_spec(ws: Path, answers: dict, report: dict) -> None:
    """Confirm phase 2: primary_questions into task_spec.yaml
    (first-class, addendum 1)."""
    spec_path = Path(ws) / "task_spec.yaml"
    if spec_path.is_file():
        try:
            spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise IntakeDraftError(
                f"task_spec.yaml unparseable: {exc}") from exc
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise IntakeDraftError(
                "task_spec.yaml must be a YAML mapping, got "
                f"{type(spec).__name__}")
        existing = spec.get("primary_questions")
        if existing in (None, [], {}):
            spec["primary_questions"] = list(
                answers.get("primary_questions") or [])
            spec_path.write_text(
                yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            report["task_spec"] = spec_path
        elif [q for q in (existing if isinstance(existing, list) else [])]:
            _validate_pqs(existing)  # conflict = a stale draft; refuse
            spec_path.write_text(
                yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            report["task_spec"] = spec_path


def _confirm_goal_op(ws: Path, fields: dict, answers: dict, ts: str,
                     report: dict) -> None:
    """Confirm phase 3: fill the DRAFT goal-operationalization +
    stamp declared_ts (confirm BEFORE the stamp, per the issue
    ordering)."""
    goal_path = Path(ws) / GOAL_OP_NAME
    if goal_path.is_file():
        try:
            goal = yaml.safe_load(goal_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise IntakeDraftError(
                f"{GOAL_OP_NAME} unparseable: {exc}") from exc
        if isinstance(goal, dict):
            stamped = bool(str(goal.get("first_dispatch_ts") or "").strip())
            declared = bool(str(goal.get("declared_ts") or "").strip())
            if stamped or declared:
                # legacy workspace: its audit record predates the draft
                # face — additive discipline, never rewritten by confirm
                report["goal_op_skipped"] = (
                    "already declared/stamped — legacy audit record "
                    "left untouched")
            else:
                goal.update({name: fields[name] for name in
                             DRAFT_LIST_FIELDS + OPTIONAL_LIST_FIELDS})
                witness = answers.get(WITNESS_FIELD)
                if isinstance(witness, dict):
                    goal[WITNESS_FIELD] = witness
                goal["declared_ts"] = ts
                goal["draft"] = False
                goal_path.write_text(
                    yaml.safe_dump(goal, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
                report["goal_op"] = goal_path


def confirm(ws: Path, answers: dict) -> dict:
    """The confirm wall: validate -> record -> merge -> fill -> stamp.
    Returns a report dict {draft, task_spec, goal_op, goal_op_skipped}."""
    if not isinstance(answers, dict):
        raise IntakeDraftError("answers must be a mapping")
    if answers.get("confirmed") is not True:
        raise IntakeDraftError(
            "confirmed: must be literal true — the authority is the "
            "user's explicit confirm, never an implicit one")
    if answers.get("classification_confirmed") is not True:
        raise IntakeDraftError(
            "classification_confirmed: must be literal true — the lane/"
            "project_type consequence (probe battery / factor set / "
            "capabilities) must be shown and accepted, not inherited")
    draft = load(ws)
    if draft is None:
        raise IntakeDraftError(
            "no intake draft on disk — run scaffold first (the draft is "
            "the dialogue's durable face; confirming against nothing is "
            "how the dialogue gets skipped)")
    if draft.get("confirmed"):
        raise IntakeDraftError(
            "draft already confirmed — the confirm is one-way; post-"
            "confirmation edits go through the goal-operationalization "
            "re-scope records (R5), never a silent re-confirm")

    _validate_pqs(answers.get("primary_questions"))
    fields = {name: _answers_list(answers, name)
              for name in DRAFT_LIST_FIELDS + OPTIONAL_LIST_FIELDS}
    for name in ("deliverables", "acceptance", "not_done"):
        if not fields[name]:
            raise IntakeDraftError(
                f"{name}: empty — the confirmed distillation must name "
                f"it (R1 discipline: a goal without counterexamples is "
                f"unaudited)")
    if not fields["diff_vs_verbatim"]:
        raise IntakeDraftError(
            "diff_vs_verbatim: empty — silent equivalence; declare the "
            "delta vs the verbatim task (R2)")
    from goal_operationalization import RUBBER_STAMPS
    for entry in fields["diff_vs_verbatim"]:
        if entry.strip().lower() in RUBBER_STAMPS:
            raise IntakeDraftError(
                f"diff_vs_verbatim: {entry.strip()!r} is a rubber stamp "
                "— silent equivalence is refused (R2)")

    from harness_common import utc_now_z as _utc_now
    ts = _utc_now()
    report: dict = {"draft": None, "task_spec": None, "goal_op": None,
                    "goal_op_skipped": None}

    report["draft"] = _confirm_write_draft(ws, draft, fields, answers,
                                           ts, report)

    _confirm_task_spec(ws, answers, report)

    _confirm_goal_op(ws, fields, answers, ts, report)

    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(
        description="the bounded-intelligent intake draft face")
    ap.add_argument("workspace", type=Path)
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--scaffold", action="store_true",
                     help="write the unconfirmed draft (idempotent)")
    sub.add_argument("--status", action="store_true",
                     help="print the draft's confirm state as JSON")
    sub.add_argument("--confirm", metavar="ANSWERS_FILE", type=Path,
                     help="confirm the draft with a JSON/YAML answers file")
    args = ap.parse_args(argv)
    ws = args.workspace
    if args.scaffold:
        print(f"intake-draft: scaffolded {scaffold(ws)}")
        return 0
    if args.status:
        doc = load(ws)
        state = ({"exists": False} if doc is None else
                 {"exists": True, "confirmed": bool(doc.get("confirmed")),
                  "declared_ts": str(doc.get("declared_ts") or ""),
                  "classification": doc.get("classification")})
        print(json.dumps(state, ensure_ascii=False))
        return 0
    try:
        raw = args.confirm.read_text(encoding="utf-8")
        answers = json.loads(raw)
        if not isinstance(answers, dict):
            answers = yaml.safe_load(raw)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"intake-draft: ERROR unreadable answers file: {exc}",
              file=sys.stderr)
        return 2
    try:
        report = confirm(ws, answers)
    except IntakeDraftError as exc:
        print(f"intake-draft: ERROR confirm refused: {exc}", file=sys.stderr)
        return 2
    print(f"intake-draft: confirmed {report['draft']} "
          f"(task_spec: {report['task_spec']}, goal-op: "
          f"{report['goal_op'] or report['goal_op_skipped']})")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    import sys
    sys.exit(main())
