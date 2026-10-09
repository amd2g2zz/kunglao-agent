#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timeline_face.py — the structured progress projection (runs/timeline.jsonl)
and the plan face rendered from it (global_plan.txt).

The structured progress face replaces the unstructured worker echo as THE
progress view: one entry per loop step, every field mechanically PROJECTED
from ledgers that already exist (the decide/settle/dispatch event stream, the
settled fact ids, the decided next act) — never hand-written. Field sources:

  ts                  the step's outcome row ts (a real ledger instant)
  role                the outcome row's action word (role = action_type)
  stage               the nearest checkpoint row's step (else the tick axis)
  action              the commanded act (the dispatch of the claim)
  command_or_ref      the dispatch record (argv or the prompt-file pointer)
  result_summary      the settle outcome / the act's rc (failures carry
                      their bounded gap evidence — the dead-ends rule)
  artifacts           the act's artifacts (dispatch record + settlement)
  evidence_ids        the settled fact ids citing the claim
  decision_delta      the decide event's verdict nearest the step
  carry_forward_refs  obstacle children + verify/red-team run files
  next                the decided next act (the plan thread)

A step = one dispatch attempt paired with its outcome (result / settlement /
still in flight). Failures and timeouts produce entries too: the execution
chain includes what did not work, each dead end citing its gap evidence
(the information-vs-assumption separation at the narrative layer).

The projection is deterministic: the ledger stream is the append-only face,
timeline.jsonl is its recomputed step view (write-on-diff, self-healing —
the same posture as the rendered progress timeline). global_plan.txt renders
FROM the projection at the resume face (open thread = latest `next` per
claim line) — no independent maintenance; the init stub dissolves because
the loop now owns a mechanical writer, and the stub diagnostic re-arms
against the rendered marker.

Fail-open by contract: an unreadable ledger performs NO write and the skip
reason is returned (and warned) — a broken measurement never manufactures
progress.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kunglao_log import iter_jsonl  # (kunglao_log Family-K single source)
from kunglao_log import warn  # canonical warn: ONE implementation

TIMELINE_REL = Path("runs") / "timeline.jsonl"
PLAN_REL = Path("global_plan.txt")
AUDIT_NAME = "e2e-audit.jsonl"

#: the reference field shape, in order
FIELDS = ("ts", "role", "stage", "action", "command_or_ref",
          "result_summary", "artifacts", "evidence_ids",
          "decision_delta", "carry_forward_refs", "next")

#: first line of a rendered global_plan.txt (the plan face marker)
PLAN_RENDER_MARK = ("# global_plan — rendered from runs/timeline.jsonl"
                    " (mechanical projection; do not hand-edit)")
_PLAN_RENDER_PREFIX = PLAN_RENDER_MARK.split(" (")[0]

_ROW_CAP = 200
_GAP_CAP = 160

#: the decide events (the verdict source for decision_delta / next)
_DECISION_ACTIONS = frozenset({"convergence_decision"})
#: the outcome events that close a step
_RESULT_ACTIONS = frozenset({"dispatch_result"})
_SETTLE_ACTION = "claim_settled"
_ATTEMPT_ACTION = "dispatch_attempt"
_CHECKPOINT_PREFIX = "checkpoint_"

#: the decided next act per decision word (the plan-thread lookup; mirrors
#: the convergence decision table's semantics in lookup form)
NEXT_ACT_BY_DECISION = {
    "DISPATCH": "dispatch top-ranked claim",
    "DISPATCH_VERIFIER": "dispatch the verifier",
    "CONVERGED": "none — run converged",
    "SATURATED": "none — saturated",
    "BLOCKED": "manual step (blocked)",
    "INVALID": "manual step (invalid state)",
    "PARK": "park the run",
    "DRAIN": "drain the run",
}


# ----------------------------------------------------------------- reads ----

def _read_jsonl_file(path: Path) -> list[dict] | None:
    """Tolerant rows of one jsonl file; None when it exists but cannot be
    read (the honest unreadable signal)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return [r for r in iter_jsonl(text.splitlines()) if isinstance(r, dict)]


def read_rows(ws) -> list[dict] | None:
    """The unified event stream: the kunglao day files (name order = day
    order) plus the run-audit stream, stream order preserved. None when a
    present day file cannot be read."""
    ws = Path(ws)
    rows: list[dict] = []
    logs = ws / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            part = _read_jsonl_file(p)
            if part is None:
                return None
            rows.extend(part)
    audit = logs / AUDIT_NAME
    if audit.is_file():
        part = _read_jsonl_file(audit)
        if part is None:
            return None
        rows.extend(part)
    return rows


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _sorted_rows(rows: list[dict]) -> list[dict]:
    """Chronological stream order (ts, then original order — the tick axis
    is monotonic with wall clock, so ts order is tick order)."""
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda p: (_parse_ts(p[1].get("ts"))
                                or datetime.max.replace(tzinfo=timezone.utc),
                                p[0]))
    return [r for _, r in indexed]


def _detail_dict(row: dict) -> dict:
    raw = row.get("detail")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            doc = json.loads(raw)
            return doc if isinstance(doc, dict) else {}
        except ValueError:
            return {}
    return {}


def _decision_word(row: dict) -> str | None:
    word = _detail_dict(row).get("decision")
    return str(word).strip().upper() if word else None


# ------------------------------------------------------------- fact index ----

def fact_index_by_claim(ws) -> dict[str, list[str]]:
    """claim id -> citing fact ids (the evidence-DAG edges). Single-parser
    rule: the fact lint owns the frontmatter dialect; unreadable facts are
    skipped — a broken fact never blocks the projection."""
    out: dict[str, list[str]] = {}
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return out
    try:
        from lint_facts import _load_fact
    except ImportError:
        return out
    from register_proven_gate import _fact_claim_refs
    for p in sorted(facts_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            fm = _load_fact(p)
        except Exception:  # noqa: BLE001 — a broken fact never blocks
            continue
        if not isinstance(fm, dict):
            continue
        fid = str(fm.get("id") or p.stem)
        for ref in _fact_claim_refs(fm):
            out.setdefault(ref, []).append(fid)
    return {k: sorted(v) for k, v in out.items()}


def _run_refs(ws, claim_id: str) -> list[str]:
    """Verify/red-team run file names for one claim (bounded recency face)."""
    try:
        from outcome_capture import _parse_run
    except ImportError:
        return []
    runs = Path(ws) / "runs"
    if not runs.is_dir():
        return []
    out: list[str] = []
    for p in sorted(runs.glob("*.md")):
        name = p.name
        if "-verify-" not in name and "verify-redteam" not in name:
            continue
        try:
            row = _parse_run(p)
        except Exception:  # noqa: BLE001 — a broken run never blocks
            continue
        if isinstance(row, dict) and \
                str(row.get("claim_id") or "").strip() == claim_id:
            out.append(name)
    return out[-4:]


def _carry_forward(ws, claim_id: str, claims_by_id: dict) -> list[str]:
    """Obstacle children + verify/red-team run files (all mechanical)."""
    refs = [str(c.get("id")) for c in claims_by_id.values()
            if str(c.get("obstacle_for") or "") == claim_id and c.get("id")]
    return refs + _run_refs(ws, claim_id)


# ------------------------------------------------------------ projection ----

def _cap(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= _ROW_CAP else text[:_ROW_CAP - 1] + "…"


def _stage_of(row: dict, last_stage: str | None) -> str | None:
    if last_stage:
        return last_stage
    tick = row.get("epoch")
    return f"tick={tick}" if isinstance(tick, int) else None


def _attempt_ref(attempt: dict) -> str | None:
    """The dispatch record's command face: the argv when the act ran a real
    subprocess, else the prompt-file pointer."""
    adetail = _detail_dict(attempt)
    cmd = adetail.get("command")
    if isinstance(cmd, list) and cmd:
        return _cap(" ".join(str(c) for c in cmd))
    if attempt.get("artifact"):
        return str(attempt["artifact"])
    return None


def _result_summary(outcome: dict) -> str | None:
    """The act's outcome face: ok / failed rc / timed out / in flight — a
    dead end carries its bounded gap evidence (the stderr head)."""
    rc = outcome.get("exit")
    detail = _detail_dict(outcome)
    if bool(detail.get("timed_out")):
        summary = "timed out"
        gap = detail.get("stderr") or detail.get("stderr_tail")
        if gap:
            summary += f" gap: {_cap(str(gap)[:_GAP_CAP])}"
        return summary
    if isinstance(rc, int) and rc != 0:
        gap = detail.get("stderr_tail") or detail.get("stderr")
        return _cap(f"failed rc={rc} gap: "
                    f"{str(gap or '')[:_GAP_CAP]}".rstrip())
    if rc == 0:
        return "ok"
    return "in flight (no result yet)"


def _step(outcome: dict, attempt: dict | None, *, last_stage: str | None,
          last_decision: str | None, evidence: list[str],
          carry: list[str], claims_by_id: dict) -> dict:
    """One loop-step entry from its outcome row (+ its dispatch record)."""
    action = outcome.get("action")
    claim = str(outcome.get("claim") or "") or None
    detail = _detail_dict(outcome)
    command_or_ref = _attempt_ref(attempt) if attempt is not None else None
    result_summary = None
    artifacts: list[str] = []
    next_act: str | None = None

    if action == _SETTLE_ACTION:
        to = str(detail.get("to") or "")
        frm = str(detail.get("from") or "")
        result_summary = _cap(f"{frm} -> {to}".strip(" ->") or None)
        if outcome.get("artifact"):
            artifacts.append(str(outcome["artifact"]))
        next_act = f"none ({to})" if to else None
    else:  # a dispatch result (or an in-flight attempt below)
        result_summary = _result_summary(outcome)
        for a in (detail.get("artifacts") or []):
            artifacts.append(str(a))

    if next_act is None:
        if result_summary == "in flight (no result yet)":
            next_act = "await result"
        elif last_decision:
            next_act = NEXT_ACT_BY_DECISION.get(last_decision,
                                                last_decision.lower())
    act_word = (f"dispatch {claim}" if attempt is not None
                else str(action))
    return {
        "ts": outcome.get("ts"),
        "role": str(action),
        "stage": _stage_of(outcome, last_stage),
        "action": _cap(act_word),
        "command_or_ref": command_or_ref,
        "result_summary": result_summary,
        "artifacts": artifacts,
        "evidence_ids": list(evidence),
        "decision_delta": last_decision,
        "carry_forward_refs": list(carry),
        "next": next_act,
    }


def _claims_by_id(ws) -> dict[str, dict]:
    """The register's claim rows by id (absent register = cold start; an
    unreadable one leaves one canonical trace and degrades to {})."""
    out: dict[str, dict] = {}
    path = Path(ws) / "claim-register.yaml"
    if not path.is_file():
        return out
    try:
        reg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for c in (reg.get("claims") or []):
            if isinstance(c, dict) and c.get("id"):
                out[str(c["id"])] = c
    except (OSError, yaml.YAMLError) as exc:
        warn("timeline_face", f"register unreadable: {exc}")
    return out


def project(ws) -> list[dict] | None:
    """The loop steps projected from the unified stream (+ register, facts,
    deps). None = genuinely unreadable ledger (the honest skip face)."""
    rows = read_rows(ws)
    if rows is None:
        return None
    ws = Path(ws)
    claims_by_id = _claims_by_id(ws)
    evidence = fact_index_by_claim(ws)

    def _close(row: dict, attempt: dict | None) -> None:
        claim = str(row.get("claim") or "")
        steps.append(_step(
            row, attempt, last_stage=last_stage,
            last_decision=last_decision,
            evidence=evidence.get(claim, []),
            carry=_carry_forward(ws, claim, claims_by_id),
            claims_by_id=claims_by_id))

    steps: list[dict] = []
    pending: dict[str, dict] = {}
    last_attempt: dict[str, dict] = {}
    last_stage: str | None = None
    last_decision: str | None = None
    for row in _sorted_rows(rows):
        action = str(row.get("action") or "")
        claim = str(row.get("claim") or "")
        if action in _DECISION_ACTIONS or action.startswith(
                _CHECKPOINT_PREFIX):
            word = _decision_word(row) if action in _DECISION_ACTIONS else None
            if word:
                last_decision = word
            step_word = _detail_dict(row).get("step")
            if step_word:
                last_stage = str(step_word)
            continue
        if action == _ATTEMPT_ACTION and claim:
            pending[claim] = row
            last_attempt[claim] = row
            continue
        if action in _RESULT_ACTIONS and claim:
            _close(row, pending.pop(claim, None))
            continue
        if action == _SETTLE_ACTION and claim:
            _close(row, pending.pop(claim, None) or last_attempt.get(claim))
            continue
    for claim, attempt in pending.items():  # still-in-flight attempts
        steps.append(_step(
            attempt, attempt, last_stage=last_stage,
            last_decision=last_decision,
            evidence=evidence.get(claim, []),
            carry=_carry_forward(ws, claim, claims_by_id),
            claims_by_id=claims_by_id))
    return steps


# ------------------------------------------------------------ plan face ----

def _active_claims(ws) -> list[dict]:
    try:
        from status_defs import TERMINAL
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8")) or {}
        return [c for c in (reg.get("claims") or [])
                if isinstance(c, dict) and c.get("id")
                and str(c.get("status") or "").upper() not in TERMINAL]
    except (ImportError, OSError, yaml.YAMLError):
        return []


def render_plan(steps: list[dict], active_claims: list[dict]) -> str:
    """global_plan.txt from the projection: open thread = latest `next` per
    claim line; register claims the projection has not met yet render their
    awaiting line (the drift detector's claim mapping stays complete)."""
    latest: dict[str, str] = {}
    for s in steps:
        claim = None
        m = re.match(r"dispatch (\S+)$", str(s.get("action") or ""))
        if m:
            claim = m.group(1)
        if claim and s.get("next"):
            latest[claim] = str(s["next"])
    awaiting = "awaiting first dispatch (no timeline steps yet)"
    lines = [PLAN_RENDER_MARK,
             "# open thread = latest next per claim line; source:"
             " the projection + the register (never hand-written)"]
    for c in active_claims:
        cid = str(c["id"])
        lines.append(f"{cid}: {latest.get(cid, awaiting)}")
    return "\n".join(lines) + "\n"


def plan_is_rendered(ws) -> bool:
    """True when global_plan.txt is the rendered projection face."""
    try:
        head = (Path(ws) / PLAN_REL).read_text(
            encoding="utf-8", errors="replace").splitlines()[:1]
    except OSError:
        return False
    return bool(head) and head[0].startswith(_PLAN_RENDER_PREFIX)


# --------------------------------------------------- render + write face ----

def render_and_write(ws) -> dict:
    """Project -> write-on-diff (timeline + plan). Fail-open: an unreadable
    ledger performs no write, warns once, and reports the skip. Returns
    {"status", "wrote", "plan_wrote", "reason", "steps"}."""
    from _common import atomic_write_text
    ws = Path(ws)
    steps = project(ws)
    if steps is None:
        reason = "ledger unreadable — the projection is left untouched"
        warn("timeline_face", reason)
        return {"status": "skipped", "wrote": False, "plan_wrote": False,
                "reason": reason, "steps": None}
    text = "".join(json.dumps(s, sort_keys=True, ensure_ascii=False) + "\n"
                   for s in steps)
    wrote = False
    reason = None
    rel = ws / TIMELINE_REL
    try:
        old = rel.read_text(encoding="utf-8") if rel.is_file() else None
    except OSError:
        old = None
    if old != text:
        try:
            atomic_write_text(rel, text)
            wrote = True
        except OSError as exc:
            reason = f"projection unwritable: {exc}"
            warn("timeline_face", reason)
    plan_wrote = False
    active = _active_claims(ws)
    if active or (ws / "claim-register.yaml").is_file():
        plan_text = render_plan(steps, active)
        plan_rel = ws / PLAN_REL
        try:
            old_plan = (plan_rel.read_text(encoding="utf-8")
                        if plan_rel.is_file() else None)
        except OSError:
            old_plan = None
        if old_plan != plan_text:
            try:
                atomic_write_text(plan_rel, plan_text)
                plan_wrote = True
            except OSError as exc:
                reason = reason or f"plan face unwritable: {exc}"
                warn("timeline_face", reason)
    return {"status": "rendered", "wrote": wrote, "plan_wrote": plan_wrote,
            "reason": reason, "steps": len(steps)}
