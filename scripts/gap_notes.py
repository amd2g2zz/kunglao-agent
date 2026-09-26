# -*- coding: utf-8 -*-
"""gap_notes.py — settlement-event retry gap-notes (issue 391).

A minimal reflective loop between attempts of the SAME unit, riding the
settlement events of #379/#388 — context-only, advisory. Measured problem:
attempts within a unit do not inherit evidence (pass@3 data: a unit burned
2x3600s before attempt 3 passed); attempt N re-derives what attempt N-1
already falsified.

WRITE FACE — ``emit_gap_notes``: when a FAIL settlement event lands for a
task-kind rollout (negative polarity band, or tier RED), emit ONE
structured gap-note file (XML, English) under
``<ws>/runs/gap-notes/<unit>/`` derived ONLY from the machine-recorded
signals of that rollout: the oracle verdict + checker sub-scores (static
X/Y, replay N/M, chain dense layers), decoy / misleading-declaration
markers, the evidence_class of produced artifacts, cost vs the unit-class
reference. Never a model opinion at write time — every field cites a
ledger/settlement row value (the settlement's own evidence_refs are
carried verbatim so "why did this fail" has an audit trail).

READ FACE — ``read_notes``: the prior gap-notes of one unit, in stable
ascending file order (digest-named files; ordinal by write sequence, not
wall-clock age). ``hooks/recall_inject.py`` injects them on same-unit
retry dispatches through the existing dispatch-scoped channel (per-worker
content dedup applies — gap-note files are digest-named and immutable, so
a new attempt's note is a new set member and re-injects). Different units
are unaffected.

ANTI-POLLUTION (hard invariant): gap-notes are advisory context supply,
never a reward kind. The files live OUTSIDE the unified ledger (emission
leaves the ledger byte-prefix invariant), and any advisory carrier in the
signal set is excluded from rule matching by the settlement engines —
pinned by test (the repo axiom: model/derived context never enters reward
matching).

Idempotency: the filename is ``<unit>--<signals-digest12>.xml``; a
re-run over an unchanged settlement skips (same digest -> same file), a
retry attempt whose signals grew re-settles under a NEW digest -> a second
note. PASS settlements emit nothing — only failures reflect.
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import rollout_ledger as rl
import reward_settlement as rs
import scalar_settlement as ss

SCHEMA = "gap-note/1"
NOTES_REL = Path("runs") / "gap-notes"

# FAIL = a settled negative: the v1 polarity bands that pay 0 for a real
# verdict (SETTLED_RED) or the adverse fold (ADVERSE), or the v2 tier RED.
FAIL_BANDS = frozenset({"SETTLED_RED", "ADVERSE"})
TIER_RED = "RED"

# decoy / misleading-declaration marker signal types (machine-recorded;
# any type containing "decoy" joins them).
DECOY_MARKER_TYPES = frozenset(
    {"misleading_declaration", "zero_recall", "no_citation"})

# artifact statuses that make a fact file citable in a gap-note: the
# falsified/failed artifacts are exactly what the next attempt must not
# re-derive.
REFUTED_ARTIFACT_STATUSES = frozenset({"NEGATIVE", "REFUTED"})

# context budget: the read face returns the most recent notes only.
MAX_NOTES_PER_DISPATCH = 4
_DIGEST_LEN = 12

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] gap_notes WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


def sanitize_unit(unit: str) -> str:
    """Filesystem-safe unit directory/file name (no traversal: ``..``
    collapses to the ``unit`` placeholder)."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(unit or "")).strip("_")
    return cleaned or "unit"


def _last(signals: list[dict], type_: str):
    """Last machine signal value of a type (fold order = append order)."""
    val = None
    for s in signals:
        if str(s.get("type") or "") == type_:
            val = s.get("value")
    return val


def is_fail_row(row: dict) -> bool:
    """True when a folded, settled task row is a FAIL settlement (negative
    polarity band, or the v2 tier RED amendment). Kind filtering is the
    caller's (task-kind rollouts only reflect)."""
    st = row.get("settlement") or {}
    band = str(row.get("band") or st.get("band") or "")
    if band in FAIL_BANDS:
        return True
    return str(st.get("tier") or "") == TIER_RED


def _probe_face(signals: list[dict], type_: str) -> str | None:
    """One checker sub-score face as ``done/total`` (static_probes /
    replay_probes carry {passed,total}; dense_layers carries
    {completed,total}). None when the face is absent or malformed."""
    v = _last(signals, type_)
    if not isinstance(v, dict):
        return None
    done = v.get("passed", v.get("completed"))
    total = v.get("total")
    if not isinstance(done, (int, float)) \
            or not isinstance(total, (int, float)):
        return None
    return f"{int(done)}/{int(total)}"


def _val_str(value) -> str:
    """Stable string form of a recorded signal value (mappings via
    canonical json; scalars via str)."""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _oracle_element(root: ET.Element, st: dict, signals: list[dict]) -> None:
    """D1 outcome: the oracle verdict + the settled rule (audit trail)."""
    attrs = {"band": str(st.get("band") or ""),
             "rule_id": str(st.get("rule_id") or ""),
             "reward": str(st.get("reward"))}
    verdict = _last(signals, "oracle_verdict")
    if verdict is not None:
        attrs["verdict"] = str(verdict)
    if st.get("tier"):
        attrs["tier"] = str(st.get("tier"))
    ET.SubElement(root, "oracle", attrs)


def _probe_element(root: ET.Element, signals: list[dict],
                   dims: dict) -> None:
    """Checker sub-scores per face + the mechanical progress they sum to."""
    attrs: dict[str, str] = {}
    for type_, key in (("static_probes", "static"),
                       ("replay_probes", "replay"),
                       ("dense_layers", "dense_layers")):
        face = _probe_face(signals, type_)
        if face:
            attrs[key] = face
    if dims.get("probes"):
        done, total, _ = dims["probes"]
        attrs["progress"] = f"{int(done)}/{int(total)}"
    if attrs:
        ET.SubElement(root, "probes", attrs)


def _decoy_element(root: ET.Element, signals: list[dict]) -> None:
    """Decoy / misleading-declaration walls hit (recorded markers only)."""
    markers = [s for s in signals
               if str(s.get("type") or "") in DECOY_MARKER_TYPES
               or "decoy" in str(s.get("type") or "").lower()]
    if not markers:
        return
    el = ET.SubElement(root, "decoys")
    for s in markers:
        ET.SubElement(el, "marker", {
            "type": str(s.get("type")),
            "source": str(s.get("source")),
            "value": _val_str(s.get("value"))})


def _evidence_element(root: ET.Element, signals: list[dict]) -> None:
    """Evidence class of the produced artifacts (the recorded grade)."""
    ev = [s for s in signals
          if str(s.get("type") or "") == "evidence_class"]
    if not ev:
        return
    el = ET.SubElement(root, "evidence")
    for s in ev:
        ET.SubElement(el, "signal", {
            "type": str(s.get("type")),
            "source": str(s.get("source")),
            "value": _val_str(s.get("value"))})


def _artifact_element(root: ET.Element, facts: list[dict]) -> None:
    """Concrete falsified artifacts (fact files), by path."""
    if not facts:
        return
    el = ET.SubElement(root, "artifacts")
    for f in facts:
        ET.SubElement(el, "artifact", {
            "path": str(f.get("path") or ""),
            "status": str(f.get("status") or "")})


def _cost_element(root: ET.Element, signals: list[dict],
                  dims: dict) -> None:
    """D3 cost vs the unit-class reference (class median + k)."""
    cost = dims.get("cost")
    if not cost:
        return
    ET.SubElement(root, "cost", {
        "session_cost": str(cost["cost"]),
        "unit_class": str(_last(signals, "unit_class") or ""),
        "class_median": str(cost["median"]),
        "ratio": str(cost["ratio"]),
        "expensive": "true" if cost["expensive"] else "false"})


def _refs_element(root: ET.Element, st: dict) -> None:
    """The settlement's own per-signal citations, verbatim."""
    refs = [str(r) for r in (st.get("evidence_refs") or [])]
    if not refs:
        return
    el = ET.SubElement(root, "refs")
    for r in refs:
        child = ET.SubElement(el, "ref")
        child.text = r


def build_gap_note(row: dict, cost_reference: dict,
                   facts: list[dict] | None = None) -> str:
    """One gap-note XML document from a folded settled row. PURE: every
    attribute and element text is derived from the row's machine signals
    and its settlement document (advisory signals excluded — the note
    quotes only what the engines themselves may read)."""
    st = dict(row.get("settlement") or {})
    signals = [dict(s) for s in (row.get("signals") or [])
               if isinstance(s, dict) and not s.get("advisory")]
    digest = str(st.get("signals_digest") or "")[:_DIGEST_LEN]
    root = ET.Element("gap-note", {
        "schema": SCHEMA,
        "advisory": "true",
        "unit": str(row.get("anchor") or ""),
        "rollout_id": str(row.get("rollout_id") or ""),
        "kind": str(row.get("kind") or ""),
        "signals_digest": digest,
        "settled_ts": str(st.get("tier_settled_ts")
                          or st.get("settled_ts") or row.get("ts") or ""),
    })
    _oracle_element(root, st, signals)
    dims = ss.extract_dimensions(signals, cost_reference)
    _probe_element(root, signals, dims)
    _decoy_element(root, signals)
    _evidence_element(root, signals)
    _artifact_element(root, list(facts or []))
    _cost_element(root, signals, dims)
    _refs_element(root, st)
    return ET.tostring(root, encoding="unicode")


def _refuted_facts(ws: Path) -> list[dict]:
    """Concrete falsified artifacts (facts face) cited by path in the
    note. Tolerant: the facts face degrades to [] on any problem."""
    try:
        rows = ss.fact_artifacts(ws)
    except Exception as exc:  # noqa: BLE001 — citation face degrades only
        warn("refuted_facts", f"{type(exc).__name__}: {exc}")
        return []
    out = []
    for r in rows:
        status = str(r.get("status") or "").strip().upper()
        if status in REFUTED_ARTIFACT_STATUSES and r.get("id"):
            out.append({"path": f"facts/{r['id']}.md", "status": status})
    return out


def emit_gap_notes(ws, rules_path=None) -> dict:
    """Tick face: write one gap-note per settled task-kind FAIL rollout
    that does not have its note yet (digest-named file -> idempotent at
    any wall-clock distance). Fail-open: a problem degrades to a reason
    string, never a raise into the rollup tick. Returns
    {"seen", "emitted", "skipped_existing", "reason"}."""
    ws = Path(ws)
    out = {"seen": 0, "emitted": 0, "skipped_existing": 0, "reason": None}
    try:
        rows = [r for r in rl.settled(ws, kind="task") if is_fail_row(r)]
    except Exception as exc:  # noqa: BLE001
        out["reason"] = f"read: {type(exc).__name__}: {exc}"
        warn("emit_gap_notes", out["reason"])
        return out
    if not rows:
        return out
    try:
        doc = rs.load_rules(rules_path) if rules_path else rs.load_rules()
        cost_reference = doc.get("cost_reference") or {}
    except Exception as exc:  # noqa: BLE001 — loud upstream, degraded here
        out["reason"] = f"rules: {type(exc).__name__}: {exc}"
        warn("emit_gap_notes", out["reason"])
        return out
    facts = _refuted_facts(ws)
    for row in rows:
        out["seen"] += 1
        try:
            out = _emit_one(ws, row, cost_reference, facts, out)
        except Exception as exc:  # noqa: BLE001 — one bad row blocks none
            out["reason"] = (f"emit {row.get('rollout_id')}: "
                             f"{type(exc).__name__}: {exc}")
            warn("emit_gap_notes", out["reason"])
    return out


def _emit_one(ws: Path, row: dict, cost_reference: dict,
              facts: list[dict], out: dict) -> dict:
    """Write (or skip) the note for one settled FAIL row."""
    st = row.get("settlement") or {}
    unit = sanitize_unit(str(row.get("anchor")
                             or row.get("rollout_id") or ""))
    ident = (str(st.get("signals_digest") or "")[:_DIGEST_LEN]
             or sanitize_unit(str(st.get("tier_settled_ts")
                                  or st.get("settled_ts")
                                  or _now())))
    path = ws / NOTES_REL / unit / f"{unit}--{ident}.xml"
    if path.exists():
        out["skipped_existing"] += 1
        return out
    xml = build_gap_note(row, cost_reference, facts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    out["emitted"] += 1
    return out


def read_notes(ws, unit, limit: int = MAX_NOTES_PER_DISPATCH
               ) -> list[tuple[str, str]]:
    """READ FACE: the prior gap-notes of one unit as (workspace-relative
    label, xml text), stable ascending file order (digest-named files:
    ordinal by write sequence, not wall-clock age), bounded to the most
    recent ``limit``. Different units are unaffected (per-unit
    directories). Fail-open: unreadable notes are skipped."""
    ws = Path(ws)
    directory = ws / NOTES_REL / sanitize_unit(str(unit or ""))
    if not directory.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(directory.glob("*.xml"))[-limit:]:
        try:
            out.append((path.relative_to(ws).as_posix(),
                        path.read_text(encoding="utf-8",
                                       errors="replace")))
        except OSError as exc:  # noqa: BLE001 — reflection never blocks
            warn("read_notes", f"{type(exc).__name__}: {exc}")
    return out


if __name__ == "__main__":  # pragma: no cover — library module; tick via rollup
    print(__doc__)
