# -*- coding: utf-8 -*-
"""state/belief.py — the belief aggregation face, P(s)'s g_i read (903).

The structured ``belief-snapshot/1`` document over the SIX cognition
elements — confirmed facts, hypotheses + evidence, excluded
hypotheses, analyzed areas, open questions, current exploration goal.
Every element is SOURCED from an existing face; nothing is invented:

  - confirmed facts: ``<ws>/facts/F*.md`` frontmatter, folded onto the
    step-credit ladder by step_credit's OWN classification
    (``classify_verification``) — a cross-validated anchor (status in
    CROSS_VALIDATED_STATUSES behind a green verifier gate) banks as
    confirmed; the refuted class and the floor stay data. A reproduced
    rule-out (NEGATIVE + green) banks at full ladder strength.
  - hypotheses + evidence: the Φ ledger's resolution rows
    (``rlvr.phi_tree.read_resolutions``), banked only through
    ``rlvr.phi_tree.decisive`` — the same machine-witness /
    referee-confirm gate that flips the store node to confirmed.
  - excluded hypotheses: the elimination rows
    (``rlvr.phi_tree.read_eliminations``), same decisive gate,
    deduplicated on (hypothesis, candidate) — the belief state, not
    the event log.
  - analyzed areas / current goal: the ledger's own v2 action rows —
    targets of select_task/assign_step moves; the LATEST select_task
    target IS the current exploration goal.
  - open questions: task_spec primary_questions, verbatim — their file
    order is the priority order.

The single-authority wall: LLM-proposed content has NO input channel —
there is no proposals parameter, and a known-but-undecisive evidence
kind (worker assertion) is recorded history that never banks. Only
evidence-class-backed content enters the snapshot.

V wiring (documented, no code): the snapshot is what P(s) reads;
``state/progress.P`` prices the goal tree it describes, and the P
series feeds ``credit/advantage.py`` through ``progress.values_from``
(the V baseline of A = R − V). This face itself writes no P, no
reward, no credit: a snapshot lands as TELEMETRY (``credit=None``,
source "state"), exactly like its sibling state faces.

Deterministic by construction: sorted elements, no clock read, no
sampling — the same ledgers build an identical snapshot. This is the
input side of the delta_P noise-isolation pin: the credit signal is a
pure function of subgoal statuses, so the observation face it reads
must add zero noise of its own.

Fail-closed at the boundary (the state-face posture — garbage would
fabricate belief, and fabricated belief would fabricate progress):
malformed sources raise ValueError. The DISK readers are tolerant at
the unreadable-file edge only (a file with no parseable frontmatter is
not evidence — the lint face owns the loudness); everything that IS
read passes through the fail-closed walls.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import phi_tree  # noqa: E402 — the path bootstrap lands first
from rlvr import q_cells  # noqa: E402
from rlvr.step_credit import CROSS_VALIDATED, classify_verification  # noqa: E402

from . import progress as _progress  # noqa: E402

SCHEMA = "belief-snapshot/1"

#: the six cognition elements (the content keys; ``schema`` rides
#: alongside as the receipt stamp)
ELEMENTS = ("confirmed_facts", "hypotheses", "excluded_hypotheses",
            "analyzed_areas", "open_questions", "current_goal")

#: the closed confidence-band vocabulary (authority: the fact
#: frontmatter contract lint_facts VALID_CONFIDENCE enforces)
BANDS = frozenset({"high", "medium", "low"})

#: the action kinds whose targets are analysis moves; the goal kind is
#: the one that re-points the current exploration goal
GOAL_KIND = "select_task"
AREA_KINDS = frozenset({GOAL_KIND, "assign_step"})

#: the fact glob — the same base the step-credit window reads
_FACT_GLOB = "F*.md"

SOURCE = _progress.SOURCE
METHOD_FAMILY_BELIEF = "state-belief"
REASON_BELIEF = "belief-snapshot-read"


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.belief.{field}: {why}")


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _mapping_rows(name: str, rows: Any) -> list[Mapping]:
    if not isinstance(rows, (list, tuple)):
        raise _fail(name, "must be a sequence of rows")
    for row in rows:
        if not isinstance(row, Mapping):
            raise _fail(name, f"not a mapping: {row!r}")
    return list(rows)


# ------------------------------------------------------------- the folds

def _fact_entry(meta: Mapping) -> dict | None:
    """One fact frontmatter -> its confirmed-facts entry, or None when
    the ladder's own classification declines to confirm it."""
    fid = _nonempty(meta.get("id"), "facts.id")
    status = meta.get("status")
    if not isinstance(status, str) or not status.strip():
        raise _fail("facts.status",
                    f"{fid}: must be a non-empty string, got {status!r}")
    band = meta.get("confidence")
    if band is not None and (not isinstance(band, str) or band not in BANDS):
        raise _fail("facts.confidence",
                    f"{fid}: must be one of {sorted(BANDS)}, got {band!r}")
    klass = classify_verification(status, meta.get("verify_status"))
    if klass != CROSS_VALIDATED:
        return None
    return {"id": fid, "status": status, "confidence": band, "class": klass}


def _confirmed_facts(rows: Any) -> list[dict]:
    banked: dict[str, dict] = {}
    for meta in _mapping_rows("facts", rows):
        entry = _fact_entry(meta)
        if entry is None:
            continue
        if entry["id"] in banked:
            raise _fail("facts",
                        f"duplicate fact id {entry['id']!r} (a duplicate "
                        "would double-count the belief it carries)")
        banked[entry["id"]] = entry
    return [banked[k] for k in sorted(banked)]


def _hypotheses(rows: Any) -> list[dict]:
    """Confirmed hypotheses with their decisive evidence; the LATEST
    decisive resolution per hypothesis wins (append order)."""
    latest: dict[str, dict] = {}
    for row in _mapping_rows("resolutions", rows):
        hid = _nonempty(row.get("hypothesis"), "resolutions.hypothesis")
        kind = _nonempty(row.get("evidence_kind"),
                         "resolutions.evidence_kind")
        ref = _nonempty(row.get("evidence_ref"), "resolutions.evidence_ref")
        if not phi_tree.decisive(kind, ref):
            # the single-authority wall: a worker assertion is recorded
            # history — the ledger keeps it, the belief never banks it
            continue
        latest[hid] = {"id": hid, "evidence_kind": kind, "evidence_ref": ref}
    return [latest[k] for k in sorted(latest)]


def _excluded(rows: Any) -> list[dict]:
    """Excluded candidates; the FIRST elimination settles a pair, later
    repeats are the same belief."""
    first: dict[tuple[str, str], dict] = {}
    for row in _mapping_rows("eliminations", rows):
        hid = _nonempty(row.get("hypothesis"), "eliminations.hypothesis")
        cand = _nonempty(row.get("candidate"), "eliminations.candidate")
        kind = _nonempty(row.get("evidence_kind"),
                         "eliminations.evidence_kind")
        ref = _nonempty(row.get("evidence_ref"), "eliminations.evidence_ref")
        if not phi_tree.decisive(kind, ref):
            continue
        first.setdefault((hid, cand),
                         {"hypothesis": hid, "candidate": cand,
                          "evidence_kind": kind, "evidence_ref": ref})
    return [first[k] for k in sorted(first)]


def _areas_and_goal(rows: Any) -> tuple[list[str], str | None]:
    """Analysis moves from the ledger's own action rows. Only the v2
    action schema is accepted (the face never half-reads obs/result
    rows); other action kinds are other decision families' rows and are
    skipped, never folded in."""
    areas: set[str] = set()
    goal: str | None = None
    for row in _mapping_rows("actions", rows):
        if row.get("schema") != q_cells.SCHEMA_ACTION_V2:
            raise _fail("actions",
                        f"{row.get('schema')!r} outside the action "
                        f"schema {q_cells.SCHEMA_ACTION_V2!r}")
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in AREA_KINDS:
            continue
        target = _nonempty(row.get("target"), "actions.target")
        areas.add(target)
        if kind == GOAL_KIND:
            goal = target
    return sorted(areas), goal


def _questions(rows: Any) -> list[dict]:
    """Open questions, task_spec priority order preserved (no sort —
    the spec's order IS the priority)."""
    out: list[dict] = []
    for i, row in enumerate(_mapping_rows("open_questions", rows)):
        qid = _nonempty(row.get("id"), f"open_questions[{i}].id")
        text = row.get("question", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise _fail(f"open_questions[{i}].question",
                        "must be a string")
        out.append({"id": qid, "question": text})
    return out


# ------------------------------------------------------------ the faces

def snapshot(facts: Sequence[Mapping], resolutions: Sequence[Mapping],
             eliminations: Sequence[Mapping], actions: Sequence[Mapping],
             open_questions: Sequence[Mapping]) -> dict:
    """Aggregate the six elements from their existing faces. Pure and
    deterministic — same inputs, identical document; no clock, no
    sampling."""
    areas, goal = _areas_and_goal(actions)
    return {
        "schema": SCHEMA,
        "confirmed_facts": _confirmed_facts(facts),
        "hypotheses": _hypotheses(resolutions),
        "excluded_hypotheses": _excluded(eliminations),
        "analyzed_areas": areas,
        "open_questions": _questions(open_questions),
        "current_goal": goal,
    }


def _read_frontmatter(path: Path) -> dict | None:
    """One fact file's frontmatter dict — the step-credit read posture:
    an unreadable / unparseable file is not evidence (skip; the lint
    face owns the loudness), never a fabricated entry."""
    import yaml  # noqa: PLC0415 — the lazy step_credit precedent
    try:
        parts = path.read_text(
            encoding="utf-8", errors="replace").split("---", 2)
        meta = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
    except (OSError, yaml.YAMLError):
        return None
    return meta if isinstance(meta, dict) else None


def _read_facts(ws: Path) -> list[dict]:
    """The fact base as data; the file stem is the fallback id (the
    step-credit read precedent)."""
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(facts_dir.glob(_FACT_GLOB)):
        meta = _read_frontmatter(path)
        if meta is None:
            continue
        out.append(dict(meta, id=str(meta.get("id") or path.stem)))
    return out


def _read_questions(ws: Path) -> list[dict]:
    """task_spec primary_questions — a missing spec / key renders the
    honest empty element; non-mapping junk rows are dropped at the YAML
    edge (the evidence_dag read posture), the surviving rows then pass
    the fail-closed wall in ``snapshot``."""
    import yaml  # noqa: PLC0415 — the lazy read precedent
    path = Path(ws) / "task_spec.yaml"
    if not path.is_file():
        return []
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(spec, dict):
        return []          # a non-mapping top level is the honest empty
    raw = spec.get("primary_questions") or []
    if not isinstance(raw, list):
        return []
    return [q for q in raw if isinstance(q, dict)]


def build_snapshot(ws) -> dict:
    """The IO face: read the four existing sources from one workspace
    and aggregate. Tolerant ONLY at the absent-layer edge (no facts
    dir / no task spec -> an honest empty element); the ledger rows and
    the fact frontmatter that ARE read go through the fail-closed
    walls."""
    ws = Path(ws)
    actions = [row for row in q_cells.trajectory_rows(ws)
               if row.get("schema") == q_cells.SCHEMA_ACTION_V2]
    return snapshot(_read_facts(ws), phi_tree.read_resolutions(ws),
                    phi_tree.read_eliminations(ws), actions,
                    _read_questions(ws))


def belief_digest(doc: Mapping) -> str:
    """Content digest of a belief snapshot — never clock-derived."""
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                         default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_belief(ws, doc: Mapping, *, claim: str | None = None,
                  dispatch_id: str | None = None,
                  ts: str | None = None) -> dict:
    """Append ONE telemetry row for a built snapshot — ``credit=None``
    by construction (no credit column -> the fold banks no posterior
    mass; the snapshot observes, settlement credits). ``ts`` rides the
    caller's deterministic clock (the fault-harness driver, #909);
    default None = the face's own self-stamp (byte-identical legacy)."""
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        raise _fail("schema", f"must be a {SCHEMA!r} document")
    return q_cells.append_observation(
        ws, belief_digest(doc), METHOD_FAMILY_BELIEF,
        credit=None, source=SOURCE, claim=claim, dispatch_id=dispatch_id,
        reason=REASON_BELIEF, ts=ts)
