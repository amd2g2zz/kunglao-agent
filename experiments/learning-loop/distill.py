# -*- coding: utf-8 -*-
"""distill.py — DISTILL as an action: the deep-research round driver
(#938).

Owner framing: distillation is an ACTION in the action space, not a
side subsystem — one DISTILL action = an internal multi-round
deep-research loop (the mal-recon conditional-recursion pattern): each
round retrieves from the configured sources, extracts, and the PRIOR
round's cognition state {findings, open_questions, conflicts} drives
the next round's queries; terminate at max_depth or cognitive
convergence (no NEW open questions AND no unresolved conflicts).

Faces and their honesty:
  DRIVER      production, deterministic, mock-free: query generation,
              cognition merge, termination, ledger landing.
  REFERENCES  production face over the REAL recall library —
              ``scripts/references_recall.py``'s recall face is
              IMPORTED (the scenario-mapped local library is a
              first-class source; the integration IS the import), hits
              are read from disk, provenance = repo-relative path.
  WEB         a SEAM (injected Callable) — the real fetcher plugs in
              later; a "web" source without an injected fetcher
              refuses fail-closed. NO network calls in production
              faces.
  EXTRACT     an injected Callable (the R3 extraction contract's
              producer — where a model face will plug in). The DRIVER
              validates the extraction FAIL-CLOSED: the six R3 fields
              are structure guidance; approach/planning_pattern/
              success_markers/failure_markers are REQUIRED (named
              refusal); motives/constraints are IDENTIFIED when the
              source states them — their absence is honest knowledge
              gap (a focused query next round), never a penalty:
              there is NO copying_risk, no suspicion machinery, no
              special settlement treatment. DISTILL settles through
              the STANDARD gates like any action.

EXECUTOR INDEPENDENCE (#938 owner correction): the distillation
execution never involves the worker (the party whose behavior is being
distilled) — this module does not know the loop's worker seam; the
loop's trigger hands the research face (ws, formulation, clock) only,
never a worker Callable. The double-emission collapse is structurally
impossible.

Ledger discipline: the cognition state + extraction records land as
q_cells observation rows under the distillation family — digest-keyed
identity, credit-free (the row observes; the standard gates price the
action), stamped by the DRIVER CLOCK ONLY (the caller's injected
clock).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parents[1] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from kunglao_log import warn  # noqa: E402 — the bootstrap lands first
from rlvr import q_cells  # noqa: E402

__all__ = [
    "DistillError", "DISTILL_FAMILY", "SOURCE", "REASON_EXTRACT",
    "REASON_COGNITION", "SOURCES", "MAX_DEPTH_CAP",
    "MAX_DOCS_PER_QUERY", "RESEARCH_SCHEMA", "COGNITION_SCHEMA",
    "distill_digest", "distill_signature", "generate_queries",
    "research",
]

#: the observation family the distillation rows land under
DISTILL_FAMILY = "deep-research-distill"
#: the observation row's source tag
SOURCE = "distill"
#: the rows' reason tags (the audit column)
REASON_EXTRACT = "distill-extract"
REASON_COGNITION = "distill-cognition"

#: the allowed source names (the spec wall admits exactly these)
SOURCES = ("references", "web")
#: the driver-side depth rail (mirrors the spec validator's 1..5)
MAX_DEPTH_CAP = 5
#: the per-query read cap of the references face (budget_scale scales it)
MAX_DOCS_PER_QUERY = 3
RESEARCH_SCHEMA = "distill-research/1"
COGNITION_SCHEMA = "distill-cognition/1"


class DistillError(ValueError):
    """A distillation input or extraction record violates the driver's
    contract. Fail-closed; the message names the offending field."""


# ------------------------------------------------------------- digests

def distill_signature(formulation: str) -> str:
    """The formulation's 12-hex fold key — SAME formulation, SAME
    signature (the cell the distillation banks into)."""
    digest = hashlib.sha256(
        f"loop938-distill/{formulation}".encode("utf-8"))
    return digest.hexdigest()[:12]


def distill_digest(payload: Mapping) -> str:
    """A payload's 12-hex content digest (the rows' identity column —
    the record/cognition content rides the receipt, the rows key it)."""
    payload_json = json.dumps(payload, sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(
        f"loop938/{payload_json}".encode("utf-8")).hexdigest()[:12]


# -------------------------------------------- the cognition machinery

def generate_queries(cognition: Mapping) -> list[str]:
    """The PINNED pure function: a cognition trio -> the next round's
    queries. Open questions -> targeted (as-is); conflicts ->
    counter-queries (``counter: ``-prefixed). The SAME state generates
    the SAME queries (determinism pin); order = the state's own order
    (open questions first, then conflicts)."""
    queries = [str(q) for q in cognition.get("open_questions") or ()]
    queries.extend(f"counter: {c}"
                   for c in cognition.get("conflicts") or ())
    return queries


def _record_id(record: Mapping) -> str:
    """The record's stable id: origin + provenance key (path for
    references, url for web, sorted-mapping fallback)."""
    origin = record.get("origin")
    prov = record.get("provenance")
    key = ""
    if isinstance(prov, Mapping):
        for k in ("path", "url"):
            if prov.get(k):
                key = str(prov[k])
                break
        else:
            key = json.dumps(prov, sort_keys=True, ensure_ascii=False)
    return f"{origin}/{key}"


def _dedup(items: Sequence[str]) -> list[str]:
    """Order-stable dedup."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _cognition_of(records: Sequence[Mapping]) -> dict:
    """One round's cognition trio, rebuilt from the round's records
    (pure, deterministic): findings = the approaches; open questions =
    the extractor-declared gaps PLUS the focused motive/constraint
    gaps (a source that cannot state WHY / UNDER-WHAT-CONSTRAINTS is a
    knowledge gap the next round targets — honest absence, not a
    penalty); conflicts = the extractor-declared contradictions."""
    findings = [str(r["approach"]) for r in records]
    open_questions: list[str] = []
    conflicts = [c for r in records
                 for c in (r.get("conflicts") or ())]
    for r in records:
        open_questions.extend(r.get("open_questions") or ())
        rid = r.get("id") or _record_id(r)
        if not r.get("motives"):
            open_questions.append(f"motives: {rid}")
        if not r.get("constraints"):
            open_questions.append(f"constraints: {rid}")
    return {"findings": findings,
            "open_questions": _dedup(open_questions),
            "conflicts": _dedup(conflicts)}


# ------------------------------------------------- the extraction wall

def _validated_record(extract_fn: Callable, doc: Mapping) -> dict:
    """The R3 completeness wall: the extractor's raw output must carry
    the required four (nonempty string / nonempty string-lists) — the
    refusal NAMES the field; motives/constraints/open_questions/
    conflicts validate as string-lists when present, defaulting to the
    honest empty list. Returns the driver-normalized record (immutable
    in spirit: every list is a fresh copy)."""
    raw = extract_fn(doc)
    if not isinstance(raw, Mapping):
        raise DistillError(
            "distill.extract: the extractor must return a mapping")
    rec: dict[str, Any] = {"id": doc["id"], "origin": doc["origin"],
                           "provenance": doc["provenance"],
                           "query": doc.get("query")}
    for field in ("approach", "planning_pattern"):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DistillError(
                f"distill.extract.{field}: must be a non-empty string "
                "(the R3 contract)")
        rec[field] = value
    for field in ("success_markers", "failure_markers"):
        value = raw.get(field)
        if not isinstance(value, (list, tuple)) or not value \
                or not all(isinstance(m, str) and m.strip()
                           for m in value):
            raise DistillError(
                f"distill.extract.{field}: must be a non-empty list of "
                "marker strings (the R3 contract)")
        rec[field] = list(value)
    for field in ("motives", "constraints", "open_questions", "conflicts"):
        value = raw.get(field)
        if value is None:
            rec[field] = []
        elif isinstance(value, (list, tuple)) \
                and all(isinstance(m, str) and m.strip() for m in value):
            rec[field] = list(value)
        else:
            raise DistillError(
                f"distill.extract.{field}: must be a list of strings "
                "when present")
    return rec


# ------------------------------------------------ the retrieval faces

def _validated_doc(doc: Any, source: str,
                   query: str | None) -> dict:
    """The retrieval wall: a source face returns mappings carrying a
    nonempty mapping provenance (references: path; web: url+date) and
    string text; the driver supplies origin/query/id. Fail-closed,
    named."""
    if not isinstance(doc, Mapping):
        raise DistillError(
            f"distill.source.{source}: each doc must be a mapping")
    prov = doc.get("provenance")
    if not isinstance(prov, Mapping) or not prov:
        raise DistillError(
            f"distill.source.{source}: doc provenance must be a "
            "non-empty mapping (references: path; web: url+date)")
    if not isinstance(doc.get("text"), str):
        raise DistillError(
            f"distill.source.{source}: doc text must be a string")
    shell = {"origin": source, "text": doc["text"],
             "provenance": dict(prov),
             "query": doc.get("query", query)}
    shell["id"] = _record_id(shell)
    return shell


def _references_fetch(queries: Sequence[str],
                      width: int) -> list[dict]:
    """The PRODUCTION references face: references_recall's recall face
    runs per query (the import IS the integration — the scenario-mapped
    local library is a first-class source), hit files are READ (the
    catalog paths resolve under references/), each hit lands as a doc
    whose provenance is the catalog path. Deterministic; no network;
    per-query width cap applied AFTER missing-file skips (a stale index
    row is one warn, never a killed round)."""
    import references_recall as rr  # noqa: PLC0415 — the cited face
    index_path = rr.default_index_path()
    index = rr.build_index(index_path)
    root = index_path.parent
    docs: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        result = rr.recall(index.entries, index.scenes, query)
        taken = 0
        for rel in result.files:
            if taken >= width:
                break
            if rel in seen:
                continue
            seen.add(rel)
            hit = (root / rel).resolve()
            if not hit.is_relative_to(root.resolve()):
                # a catalog path with ../ must not escape references/
                warn("distill.references", f"{rel}: escapes references/ — skipped")
                continue
            try:
                text = hit.read_text(encoding="utf-8")
            except OSError as exc:
                warn("distill.references",
                     f"{rel}: {type(exc).__name__}: {exc} — skipped")
                continue
            taken += 1
            docs.append({"origin": "references",
                         "provenance": {"path": rel}, "text": text,
                         "query": query})
    return docs


def _retrieve(fetchers: Mapping, queries: Sequence[str]) -> list[dict]:
    """One round's retrieval, in the caller's source order, deduped
    within the round by record id (origin + provenance key)."""
    docs: list[dict] = []
    seen: set[str] = set()
    for source, fetch in fetchers.items():
        for doc in fetch(queries):
            shell = _validated_doc(doc, source,
                                   str(queries[0]) if queries else None)
            if shell["id"] in seen:
                continue
            seen.add(shell["id"])
            docs.append(shell)
    return docs


def _build_fetchers(sources: Sequence[str], web_fetch: Callable | None,
                    width: int) -> dict:
    """The source-name -> fetch face map. references binds the
    production face (per-query read width = ``width``); web binds the
    INJECTED seam (its presence is checked upstream)."""
    fetchers: dict[str, Callable] = {}
    for source in sources:
        if source == "references":
            fetchers["references"] = (
                lambda queries, _w=width: _references_fetch(queries, _w))
        else:
            fetchers[source] = web_fetch
    return fetchers


# ------------------------------------------------------ the landing

def _land_round_rows(ws: Path, sig: str, round_no: int,
                     records: Sequence[Mapping],
                     cognition: Mapping, queries: Sequence[str],
                     converged: bool, clock: Any) -> None:
    """The ledger landing: one observation row per extraction record +
    one cognition row per round — credit-free (standard settlement),
    digest-keyed, stamped by the DRIVER clock only."""
    for rec in records:
        q_cells.append_observation(
            ws, distill_digest(rec), DISTILL_FAMILY, credit=None,
            source=SOURCE,
            claim=f"round {round_no} extract {rec['id']}",
            reason=REASON_EXTRACT, ts=clock.tick())
    view = {"schema": COGNITION_SCHEMA, "round": round_no,
            "queries": list(queries),
            "cognition": {k: list(v) for k, v in cognition.items()},
            "converged": converged}
    q_cells.append_observation(
        ws, distill_digest(view), DISTILL_FAMILY, credit=None,
        source=SOURCE, claim=f"round {round_no} cognition",
        reason=REASON_COGNITION, ts=clock.tick())


def _check_inputs(formulation: Any, max_depth: Any, sources: Any,
                  budget_scale: Any, clock: Any, web_fetch: Any,
                  extract_fn: Any) -> str:
    """The driver's fail-closed input wall (the spec wall already
    governs the ACTION row; the driver re-checks its OWN face inputs —
    the driver is callable outside the loop)."""
    if not isinstance(formulation, str) or not formulation.strip():
        raise DistillError(
            "distill.formulation: must be a non-empty string (the "
            "capability gap's problem formulation)")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) \
            or not 1 <= max_depth <= MAX_DEPTH_CAP:
        raise DistillError(
            f"distill.max_depth: must be an integer in [1, "
            f"{MAX_DEPTH_CAP}]")
    if not isinstance(sources, (list, tuple)) or not sources:
        raise DistillError(
            "distill.sources: must be a non-empty sequence of source "
            f"names (allowed: {list(SOURCES)})")
    for source in sources:
        if source not in SOURCES:
            raise DistillError(
                f"distill.sources: {source!r} is not an allowed source "
                f"(allowed: {list(SOURCES)})")
    if isinstance(budget_scale, bool) \
            or not isinstance(budget_scale, (int, float)) \
            or not math.isfinite(budget_scale) or budget_scale <= 0:
        raise DistillError(
            "distill.budget_scale: must be a positive finite number")
    if not hasattr(clock, "tick"):
        raise DistillError(
            "distill.clock: must provide a tick() driver clock")
    if extract_fn is None:
        raise DistillError(
            "distill.extract_fn: the extraction face is required (the "
            "R3 contract is the action's evidence contract)")
    if "web" in sources and web_fetch is None:
        raise DistillError(
            "distill.web_fetch: the 'web' source requires an injected "
            "fetch seam (no network in the production faces)")
    return formulation.strip()


def research(ws: Path, formulation: str, *, max_depth: int = 3,
             sources: Sequence[str] = SOURCES, budget_scale: float = 1.0,
             clock: Any, web_fetch: Callable | None = None,
             extract_fn: Callable | None = None) -> dict:
    """The deep-research round driver — ONE DISTILL action's execution.

    Round 1 queries = [formulation]. Round k queries = the PRIOR
    round's cognition trio run through the pinned ``generate_queries``
    (targeted / counter-queries / focused motive-constraint gaps).
    Terminate at ``max_depth`` or convergence (no NEW open questions
    AND no unresolved conflicts). Each round lands its extraction +
    cognition rows (credit-free, driver clock). Returns a
    deterministic Path-free receipt.

    ``extract_fn`` maps a retrieved doc -> the R3 record fields
    (validated fail-closed). ``web_fetch`` is the injected web seam —
    required iff "web" is in ``sources``. ``budget_scale`` scales the
    references face's per-query read width.
    """
    formulation = _check_inputs(formulation, max_depth, sources,
                                budget_scale, clock, web_fetch,
                                extract_fn)
    seen_findings: list[str] = []
    seen_questions: set[str] = set()
    seen_conflicts: set[str] = set()
    rounds: list[dict] = []
    queries: list[str] = [formulation]
    converged = False
    sig = distill_signature(formulation)
    width = max(1, round(MAX_DOCS_PER_QUERY * float(budget_scale)))
    while len(rounds) < max_depth and not converged:
        round_no = len(rounds) + 1
        docs = _retrieve(_build_fetchers(sources, web_fetch, width),
                         queries)
        records = [_validated_record(extract_fn, doc) for doc in docs]
        cognition = _cognition_of(records)
        new_questions = [q for q in cognition["open_questions"]
                         if q not in seen_questions]
        new_conflicts = [c for c in cognition["conflicts"]
                         if c not in seen_conflicts]
        seen_questions.update(new_questions)
        seen_conflicts.update(new_conflicts)
        for finding in cognition["findings"]:
            if finding not in seen_findings:
                seen_findings.append(finding)
        # convergence: nothing NEW to ask AND no unresolved conflicts
        converged = not new_questions and not cognition["conflicts"]
        _land_round_rows(ws, sig, round_no, records, cognition,
                         queries, converged, clock)
        rounds.append({"round": round_no, "queries": list(queries),
                       "records": records, "cognition": cognition,
                       "new_questions": new_questions,
                       "new_conflicts": new_conflicts,
                       "converged": converged})
        queries = generate_queries(cognition)
    # #944: the research completion milestone rides the #915 telemetry
    # face (operator INFO selection) — the completion is a fact about
    # the run's progress, deterministically encoded in the receipt.
    try:
        from state import telemetry as _telemetry  # noqa: PLC0415 — lazy
        _telemetry.emit(ws, "distill", "DISTILL_COMPLETE",
                        detail={"rounds_run": len(rounds),
                                "converged": bool(converged)})
    except Exception as exc:  # noqa: BLE001 — telemetry never blocks research
        warn("distill.research",
             f"completion milestone failed: {type(exc).__name__}: {exc}")
    return {"schema": RESEARCH_SCHEMA, "formulation": formulation,
            "max_depth": max_depth, "sources": list(sources),
            "budget_scale": float(budget_scale), "rounds": rounds,
            "rounds_run": len(rounds), "converged": converged,
            "findings": seen_findings}
