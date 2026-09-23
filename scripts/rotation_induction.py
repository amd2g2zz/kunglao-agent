#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rotation_induction.py — same-slot value-join rotation induction (#341, scope B+D).

WHY (issue #341, evidence F2): F(K1 decrypts) and F(K2 decrypts) are
individually true, non-contradictory facts. The rotation is MECHANICALLY
derivable — same claim, same subject slot, distinct value fingerprints —
but nothing derived it: convergence's "zero contradictions" requires an
EXPLICIT contradiction fact nobody files on key-refresh, the churn
detectors key on signatures an always-succeeding-with-fresh-key loop never
produces (F3), and the hypothesis machinery was model-initiated only (F5).
Each re-hook cycle was locally successful; the meta-fact was invisible.

The induction is a dumb script's job, zero model judgment:

    group runtime facts by (claim_id, subject_slot)
    >= 2 DISTINCT value_fingerprints under one slot
        -> emit `runtime_value_rotation` (EMIT_ACTIONS word)
        -> auto-file the hypothesis "<slot> rotates (observed N distinct
           values: fp1@t1, fp2@t2 …)" as the COMPETITOR of the implicit
           static premise
        -> write a synthesis note (verify_status: pending) recording the
           fingerprint series with timestamps
        -> append one operator_action row to the convergence ledger (D:
           convergence_health renders it on the verdict face)
    same fingerprint set again -> no re-emit (idempotent)

The model's only job is the characterization experiment, and the dispatch
gate (hooks/worker_budget_gates.check_rotation_experiment) guarantees the
experiment template rides along. Externalized recognition.

State: runs/.rotation-induction.json — per (claim|slot) key, the fired
fingerprint set + artifact pointers. Fingerprints only, never raw values.

Usage (tick mechanism, registry entry `rotation_induction`):
  python scripts/rotation_induction.py <workspace> [--json]
Exit 0 always (advisory mechanism — never fails the tick).
"""
from __future__ import annotations



# issue 275 batch-3: fail-open handlers keep their liveness posture (never
# raise, never change the return shape) but must leave ONE trace - a stderr
# WARN naming the operation + reason, rate-limited to once per op until the
# reason changes (the _zof_warn pattern of issue 276; one ws per process,
# so op is the key).
import sys
_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] rotation_induction WARN (fail-open): "
          f"{op}: {reason}",
          file=sys.stderr)
import argparse
import json
import re
from pathlib import Path

from harness_common import utc_now_iso  # noqa: E402  (#863 Family F)
from kunglao_log import emit  # noqa: E402
from hypothesis_store import Hypothesis, HypothesisStore  # noqa: E402
from lint_facts import parse_frontmatter  # noqa: E402

ROTATION_ACTION = "runtime_value_rotation"
STATE_REL = Path("runs") / ".rotation-induction.json"
STATE_SCHEMA = 1
LEDGER_NAME = ".convergence_ledger.jsonl"
LEDGER_FORMAT = "convergence-ledger/2"  # status_defs contract (import-light copy)
MIN_DISTINCT = 2  # >=2 distinct fingerprints under one slot = rotation
COMPETITOR_GROUP_FMT = "rotation-{claim}-{slot}"
REFERENCE_CARD = ("references/re-library/dynamic/"
                  "rotation-characterization.md")
DISPATCH_MARKER = "rotation-experiment:"

_NOTE_ID_RE = re.compile(r"^id:\s*N-(\d+)\s*$", re.MULTILINE)
_HYP_ID_RE = re.compile(r"^H-(\d+)$")
# Raw-line read for captured_at: the PyYAML path in parse_frontmatter
# coerces an unquoted ISO ts to a datetime and lint_facts' scalar coercion
# folds it to the DATE ("2026-09-22") — the series ordering needs the full
# timestamp, so it is read from the raw frontmatter (the
# verify_status_watch regex-read pattern).
_CAPTURED_AT_RE = re.compile(r"^captured_at:\s*\"?'?([^\"'\n]+)", re.MULTILINE)


# ---------------------------------------------------------------------------
# scan + detect (pure read faces)
# ---------------------------------------------------------------------------

def scan_runtime_facts(ws: Path) -> list[dict]:
    """Facts carrying the runtime quartet (temporal_scope=runtime +
    subject_slot + value_fingerprint). The write gate (#341 scope A)
    guarantees the quartet on live facts; anything else is skipped, never
    half-read."""
    ws = Path(ws)
    facts = ws / "facts"
    if not facts.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(facts.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, _body, _err = parse_frontmatter(text)
        if str(fm.get("temporal_scope") or "").strip() != "runtime":
            continue
        slot = str(fm.get("subject_slot") or "").strip()
        fp = str(fm.get("value_fingerprint") or "").strip()
        if not slot or not fp:
            continue
        raw_fm = text.split("---", 2)[1] if text.startswith("---") else text
        cm = _CAPTURED_AT_RE.search(raw_fm)
        captured = (cm.group(1).strip() if cm
                    else str(fm.get("captured_at") or "").strip())
        out.append({
            "fid": str(fm.get("id") or p.stem),
            "claim_id": str(fm.get("claim_id") or "").strip(),
            "subject_slot": slot,
            "value_fingerprint": fp,
            "captured_at": captured,
        })
    return out


def detect_rotations(ws: Path) -> dict[tuple[str, str], dict]:
    """The mechanical join: (claim_id, subject_slot) -> {"fingerprints":
    sorted distinct fps, "series": timestamp-ordered {fp, captured_at,
    fact}}. Only groups with >= MIN_DISTINCT distinct fingerprints appear."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for rec in scan_runtime_facts(ws):
        groups.setdefault((rec["claim_id"], rec["subject_slot"]),
                          []).append(rec)
    out: dict[tuple[str, str], dict] = {}
    for key, recs in groups.items():
        series = sorted(
            recs,
            key=lambda r: (r["captured_at"], r["fid"]))  # ts-ordered
        fps = sorted({r["value_fingerprint"] for r in series})
        if len(fps) >= MIN_DISTINCT:
            out[key] = {
                "fingerprints": fps,
                "series": [
                    {"fp": r["value_fingerprint"],
                     "captured_at": r["captured_at"],
                     "fact": r["fid"]}
                    for r in series
                ],
            }
    return out


# ---------------------------------------------------------------------------
# state (fingerprints only — hygiene holds in the state file too)
# ---------------------------------------------------------------------------

def state_path(ws: Path) -> Path:
    return Path(ws) / STATE_REL


def load_state(ws: Path) -> dict:
    try:
        data = json.loads(state_path(ws).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": STATE_SCHEMA, "rotations": {}}
    if not isinstance(data, dict) or not isinstance(
            data.get("rotations"), dict):
        return {"schema": STATE_SCHEMA, "rotations": {}}
    data.setdefault("schema", STATE_SCHEMA)
    return data


def save_state(ws: Path, state: dict) -> None:
    p = state_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        warn("save_state", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# writers: hypothesis / synthesis note / convergence-ledger row
# ---------------------------------------------------------------------------

def _next_hypothesis_id(store: HypothesisStore) -> str:
    ids = [0]
    for h in store.list_all():
        m = _HYP_ID_RE.match(str(h.id or ""))
        if m:
            ids.append(int(m.group(1)))
    return f"H-{max(ids) + 1:03d}"


def _next_note_id(ws: Path) -> str:
    nums = [0]
    notes = ws / "notes"
    if notes.is_dir():
        for p in notes.glob("*.md"):
            try:
                m = _NOTE_ID_RE.search(
                    p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if m:
                nums.append(int(m.group(1)))
    return f"N-{max(nums) + 1:03d}"


def _series_text(series: list[dict]) -> str:
    return ", ".join(
        f"{s['fp']}@{s['captured_at'] or 'unknown-ts'} ({s['fact']})"
        for s in series)


def file_hypothesis(ws: Path, key: tuple[str, str], det: dict) -> str:
    """The rotation competitor: an OPEN hypothesis naming the observed
    fingerprint series, filed AGAINST the implicit static premise."""
    claim_id, slot = key
    store = HypothesisStore(ws / "hypotheses")
    body = (
        f"# rotation hypothesis — {slot} (claim {claim_id})\n\n"
        "Mechanical induction (issue #341): >= 2 distinct value fingerprints "
        "observed under one subject slot, same claim.\n\n"
        "Competing premises:\n"
        f"- STATIC (implicit premise so far): `{slot}` is stable — every "
        "successful use reconfirmed it, and no explicit contradiction fact "
        "was ever filed on refresh.\n"
        f"- ROTATION (this hypothesis): `{slot}` rotates. Observed "
        f"{len(det['fingerprints'])} distinct values: "
        f"{_series_text(det['series'])}.\n\n"
        "Discriminating experiment (REQUIRED on the next dispatch of this "
        f"claim — the dispatch gate rejects a re-hook-only retry without the "
        f"marker `{DISPATCH_MARKER} rotation-characterization`, template "
        f"{REFERENCE_CARD}).\n")
    h = Hypothesis(
        id=_next_hypothesis_id(store),
        claim_id=claim_id,
        competitor_group=COMPETITOR_GROUP_FMT.format(claim=claim_id, slot=slot),
        candidates=["runtime-rotation", "static-premise"],
        status="open",
        predicted_observation=(
            "in-session double capture T / T+delta shows distinct value "
            "fingerprints within one session when the slot rotates "
            "per-request/per-timer; a per-process/per-session trigger shows "
            "stable fps inside one process/session instead"),
        body=body,
    )
    store.create(h)
    return h.id


def write_synthesis_note(ws: Path, key: tuple[str, str], det: dict,
                         hypothesis_id: str,
                         supersedes: str | None = None) -> tuple[str, str]:
    """The pending synthesis note: the observed series + the required next
    step, awaiting independent verification. A fingerprint-set GROWTH writes
    a superseding note (the result layer never overwrites)."""
    claim_id, slot = key
    notes = ws / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    note_id = _next_note_id(ws)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{claim_id}-{slot}").strip("-").lower()
    fname = f"{note_id}-rotation-{slug}.md"
    fm_lines = [
        "---",
        f"id: {note_id}",
        "type: note",
        f"claim_id: {claim_id}",
        "verify_status: pending",
        f"subject_slot: {slot}",
        f"hypothesis: {hypothesis_id}",
        "mechanism: rotation_induction",
    ]
    if supersedes:
        fm_lines.append(f"supersedes: {supersedes}")
    fm_lines += [
        "---",
        "",
        f"# {note_id} rotation synthesis — {claim_id} / {slot}",
        "",
        f"`{slot}` rotates (observed {len(det['fingerprints'])} distinct "
        "values; issue #341 mechanical join, zero model judgment):",
        "",
        f"- fingerprint series: {_series_text(det['series'])}",
        f"- competing hypothesis: {hypothesis_id} (open; competitor of the "
        "implicit static premise)",
        "",
        "Next sanctioned step — the discriminating experiment "
        f"(`{DISPATCH_MARKER} rotation-characterization` on every dispatch "
        f"of this claim; template: {REFERENCE_CARD}): derivation-point hook, "
        "T / T+delta double capture, trigger-isolation matrix "
        "(per-process / per-session / per-request / timer), rotation-input "
        "source trace.",
        "",
        "verify_status: pending — an independent verifier must weigh in "
        "(#236 maker-checker; the note-gate holds this open until then).",
        "",
    ]
    (notes / fname).write_text("\n".join(fm_lines), encoding="utf-8")
    return fname, note_id


def _append_conv_row(ws: Path, key: tuple[str, str], det: dict) -> None:
    """The D wiring: one operator_action row in the convergence ledger, the
    same path record_operator_action / rollup use. convergence_health's
    verdict face renders it (rotation_events); fingerprints only."""
    claim_id, slot = key
    entry = {
        "type": "operator_action",
        "action": ROTATION_ACTION,
        "actor": "rotation_induction",
        "claim_id": claim_id,
        "reason": (f"{slot}: {len(det['fingerprints'])} distinct "
                   f"value fingerprints "
                   f"({', '.join(det['fingerprints'])})"),
        "ts": utc_now_iso(),
        "schema": LEDGER_FORMAT,
    }
    try:
        with open(Path(ws) / LEDGER_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        warn("_append_conv_row", f"{type(exc).__name__}: {exc}")


def _emit_event(ws: Path, key: tuple[str, str], det: dict,
                hypothesis_id: str, note_name: str) -> None:
    claim_id, slot = key
    emit(ws, "rotation_induction", ROTATION_ACTION,
         claim=claim_id,
         artifact=note_name,
         hypothesis_ref=hypothesis_id,
         detail=json.dumps({
             "claim_id": claim_id,
             "subject_slot": slot,
             "distinct": len(det["fingerprints"]),
             "series": det["series"],
             "hypothesis_id": hypothesis_id,
             "note": note_name,
             "reference": REFERENCE_CARD,
             "dispatch_marker": DISPATCH_MARKER,
         }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# the mechanism pass
# ---------------------------------------------------------------------------

def run(ws: Path) -> dict:
    """One induction pass. Fires on every (claim, slot) whose distinct
    fingerprint set is new (>=2); idempotent on an unchanged set."""
    ws = Path(ws)
    state = load_state(ws)
    rotations = state["rotations"]
    report: dict = {"scanned": 0, "fired": [], "skipped": []}
    recs = scan_runtime_facts(ws)
    report["scanned"] = len(recs)

    for key, det in sorted(detect_rotations(ws).items()):
        claim_id, slot = key
        state_key = f"{claim_id}|{slot}"
        fp_set = det["fingerprints"]
        prev = rotations.get(state_key)
        if isinstance(prev, dict) and prev.get("fingerprints") == fp_set:
            report["skipped"].append({"claim_id": claim_id,
                                      "subject_slot": slot,
                                      "distinct": len(fp_set)})
            continue

        fired_ts = utc_now_iso()
        if isinstance(prev, dict) and prev.get("hypothesis_id"):
            hypothesis_id = prev["hypothesis_id"]  # never duplicated
        else:
            hypothesis_id = file_hypothesis(ws, key, det)

        note_name, note_id = write_synthesis_note(
            ws, key, det, hypothesis_id,
            supersedes=(prev.get("note_id") if isinstance(prev, dict) else None))

        _emit_event(ws, key, det, hypothesis_id, note_name)
        _append_conv_row(ws, key, det)

        rotations[state_key] = {
            "fingerprints": fp_set,
            "fired": True,
            "hypothesis_id": hypothesis_id,
            "note": note_name,
            "note_id": note_id,
            "first_fired_ts": (prev or {}).get("first_fired_ts") or fired_ts,
            "ts": fired_ts,
        }
        report["fired"].append({
            "claim_id": claim_id,
            "subject_slot": slot,
            "distinct": len(fp_set),
            "hypothesis_id": hypothesis_id,
            "note": note_name,
        })

    save_state(ws, state)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="kunglao-agent rotation induction (#341): same-slot "
                    "value-join over runtime facts")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="workspace root")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report on stdout")
    args = parser.parse_args(argv)
    ws = Path(args.workspace) if args.workspace else Path.cwd()
    try:
        report = run(ws)
    except Exception as exc:  # noqa: BLE001 — advisory mechanism never fails the tick
        report = {"scanned": 0, "fired": [], "skipped": [],
                  "error": f"{type(exc).__name__}: {exc}"}
        warn("run", report["error"])
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for f in report["fired"]:
            print(f"fired: {f['claim_id']} / {f['subject_slot']} "
                  f"({f['distinct']} distinct fps) -> {f['hypothesis_id']} "
                  f"+ {f['note']}")
        for s in report["skipped"]:
            print(f"idempotent skip: {s['claim_id']} / {s['subject_slot']} "
                  f"({s['distinct']} fps unchanged)")
        if not report["fired"] and not report["skipped"]:
            print(f"no rotation candidates ({report['scanned']} runtime "
                  "facts scanned)")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
