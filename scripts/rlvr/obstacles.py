#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""obstacles.py — the obstacle/1 attribution registry (issue 461
Phase 1: attribution-in-state, intervention-based).

A failed act's attribution enters the system as STATE, produced by
intervention, not narration (REFLECT grounding: intervention-supported
attribution outperforms verbal reflection — an attribution is a
controlled experiment, not prose):

  - one JSON file per obstacle, ``runs/obstacles/OBS-<n>.json``;
  - ``kind``      closed enum KINDS (the discriminable cause class)
  - ``cause``     single machine-checkable line (<= 200 chars)
  - ``evidence_path``  the intervention experiment artifact — an
                existing workspace-relative file carrying a
                probe-execution marker (command / exit code /
                observed output; the blocker schema-v2 discipline)
  - ``method_family``  the failed act's declared family, VERBATIM —
                the registry gate owns vocabulary enforcement; this
                producer records, it never rejects on vocabulary
  - ``ts``       ISO-8601 UTC

Registry home: runs/ (beside q-cell-log / posterior-store /
situation-stream — kernel telemetry), NOT under evidence/: the
evidence-index pipeline sweeps evidence/ as raw evidence, and an
obstacle row is a derivation from its probe artifact — an evidence/
placement would invert the raw/derived hierarchy.

Boundary (owner ruling): attribution is an EVIDENCE artifact produced
by intervention — never a verdict (no status field, no dead/terminal
conclusion; an obstacle row is NOT an obstacle claim and licenses no
death declaration under the three-state charter) and never a
mandatory checklist (no gate reads this registry in Phase 1; the
worker protocol is guidance + this producer, a cause-free failure
stays legal output). The state face (rlvr.state) reads the registry
tolerantly into the canonical snapshot + signature (the ob= segment).

Integrity posture: record-time checks are structural + artifact
existence + probe-marker shape; read() re-validates structure only
(attribution is history — scratch cleanup under runs/ must not erase
it from state). Well-formed hand-edited rows enter as training noise
the Phase-2 posterior outvotes.

ZERO DECISION POSTURE: pure reads + fail-open writes; no dispatch,
gate, or settlement face imports this module (396 freeze wall).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):
    # direct-path execution (python scripts/rlvr/obstacles.py — the
    # worker protocol's invocation shape): the package parent
    # (scripts/) is NOT on sys.path (path[0] is scripts/rlvr/) —
    # insert it BEFORE the sibling imports (the q_cells precedent);
    # the guard leaves the import-time path untouched for
    # rlvr.obstacles consumers
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = "obstacle/1"
OBSTACLES_REL = "runs/obstacles"

# The closed cause vocabulary (issue 461 Phase 1): the discriminable
# classes a probe can separate. Bounded on purpose — the signature
# keys on this enum, so the key space stays finite (kind=other is the
# escape hatch; mis-buckets are training noise, not schema churn).
KINDS = (
    "missing_env_entry",
    "detection_trigger",
    "encryption_layer",
    "tool_limit",
    "other",
)

# one machine-checkable line — long enough for the env entry / trigger
# / layer name plus the probe verdict, short enough to stay a one-liner
CAUSE_MAX = 200

_ID_RE = re.compile(r"^OBS-(\d+)$")
_FILE_RE = re.compile(r"^OBS-(\d+)\.json$")


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn  # noqa: E402


# ---------- validation (pure; ws consulted for the artifact) ----------

def _marker_ok(ws: Path, rel: str) -> tuple[bool, str]:
    """The cited artifact must carry a probe-execution marker (a
    command / exit-code / observed-output shape). Reuses the blocker
    schema-v2 PROBE_MARKERS set — one marker discipline, not two —
    via lazy import so this module has no import-time dependency on
    the lint surface."""
    try:
        import blocker_lint  # the workspace-deployed sibling
    except ImportError as exc:  # pragma: no cover — deployed together
        return False, f"probe-marker check unavailable: {exc}"
    try:
        text = (ws / rel).read_text(encoding="utf-8",
                                    errors="replace").lower()
    except OSError as exc:
        return False, f"evidence artifact unreadable: {exc}"
    flat = " ".join(text.split())
    if not any(m in flat for m in blocker_lint.PROBE_MARKERS):
        return False, ("evidence artifact carries no probe-execution "
                       "marker (command/rc/output shape) — error prose "
                       "is not an experiment result")
    return True, ""


def _path_ok(value: str) -> str | None:
    """None when workspace-relative and traversal-free, else the
    reason."""
    if not isinstance(value, str) or not value.strip():
        return "evidence_path: empty"
    if "\\" in value:
        return "evidence_path: backslash is not a POSIX path"
    pure = PurePosixPath(value)
    if pure.is_absolute() or value.startswith("/"):
        return "evidence_path: absolute path"
    if ".." in pure.parts:
        return "evidence_path: parent segment"
    return None


def _field_errors(row: dict) -> list[str]:
    """Scalar-field contract: schema, id, kind, cause, evidence_path
    shape, method_family, ts."""
    errs: list[str] = []
    if row.get("schema") != SCHEMA:
        errs.append(f"schema: {row.get('schema')!r} != {SCHEMA!r}")
    id_ = row.get("id")
    if not isinstance(id_, str) or not _ID_RE.match(id_):
        errs.append(f"id: {id_!r} not OBS-<n>")
    kind = row.get("kind")
    if kind not in KINDS:
        errs.append(f"kind: {kind!r} not in {KINDS}")
    cause = row.get("cause")
    if not isinstance(cause, str) or not cause.strip():
        errs.append("cause: empty")
    elif "\n" in cause or "\r" in cause:
        errs.append("cause: multiline (must be one line)")
    elif len(cause) > CAUSE_MAX:
        errs.append(f"cause: {len(cause)} chars > {CAUSE_MAX}")
    family = row.get("method_family")
    if not isinstance(family, str) or not family.strip():
        errs.append("method_family: empty")
    ts = row.get("ts")
    if not isinstance(ts, str) or not ts.strip():
        errs.append("ts: empty (ISO-8601 required)")
    return errs


def validate_obstacle(row, ws=None) -> list[str]:
    """Structural + (when ws given) artifact validation. Pure — never
    raises; returns the defect list (empty = valid)."""
    if not isinstance(row, dict):
        return ["row: not an object"]
    errs = _field_errors(row)
    path_err = _path_ok(row.get("evidence_path"))
    if path_err:
        errs.append(path_err)
    if errs or ws is None:
        return errs
    rel = str(row.get("evidence_path"))
    if not (Path(ws) / rel).is_file():
        errs.append(f"evidence_path: {rel} does not exist — "
                    "narration without an experiment artifact is "
                    "not an obstacle")
        return errs
    ok, why = _marker_ok(Path(ws), rel)
    if not ok:
        errs.append(why)
    return errs


# ---------- registry files ----------

def _registry(ws) -> Path:
    return Path(ws) / OBSTACLES_REL


def _next_n(ws) -> int:
    """Max parsed id in the registry + 1 (filenames, not row content —
    ids stay monotonic even when a row is structurally invalid)."""
    d = _registry(ws)
    best = 0
    if d.is_dir():
        for p in d.iterdir():
            m = _FILE_RE.match(p.name)
            if m:
                best = max(best, int(m.group(1)))
    return best + 1


def _exclusive_create(path: Path, data: bytes) -> bool:
    """Atomic create-or-refuse (O_EXCL): the mint primitive. False
    when the path exists — concurrent producers never overwrite; the
    loser re-tries at the next id. A hard write error also returns
    False (warn) — never an exception into the producer, and the
    buffered writer flushes the full payload or nothing usable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    except OSError as exc:
        warn("obstacles.mint", f"{type(exc).__name__}: {exc}")
        return False
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
    except OSError as exc:
        warn("obstacles.mint", f"write {path.name}: "
                               f"{type(exc).__name__}: {exc}")
        try:
            path.unlink(missing_ok=True)  # a truncated row is no row
        except OSError as unlink_exc:
            warn("obstacles.mint",
                 f"cleanup {path.name}: {unlink_exc}")
        return False
    return True


def record(ws, *, kind: str, cause: str, evidence_path: str,
           method_family: str, claim: str | None = None,
           dispatch_id: str | None = None,
           ts: str | None = None) -> dict:
    """Record one obstacle row. Loud-result fail-open (the
    posteriors.record idiom): invalid input -> named reason, no file,
    never an exception into the producer."""
    ws = Path(ws)
    row = {
        "schema": SCHEMA,
        "id": "OBS-000",  # minted below; placeholder passes id shape
        "ts": str(ts or _now()),
        "kind": kind,
        "cause": cause,
        "evidence_path": evidence_path,
        "method_family": method_family,
    }
    if claim:
        row["claim"] = str(claim)
    if dispatch_id:
        row["dispatch_id"] = str(dispatch_id)
    errs = validate_obstacle(row, ws)
    if errs:
        return {"appended": False, "errors": errs, "row": None,
                "path": None}
    n = _next_n(ws)
    for _ in range(1000):  # bounded retry: id space far beyond a run
        candidate = f"OBS-{n:03d}"
        row["id"] = candidate
        data = (json.dumps(row, ensure_ascii=False,
                           indent=2) + "\n").encode("utf-8")
        p = _registry(ws) / f"{candidate}.json"
        if _exclusive_create(p, data):
            return {"appended": True, "errors": None, "row": row,
                    "path": str(p.relative_to(ws))}
        n += 1
    return {"appended": False,
            "errors": ["mint: id space exhausted"], "row": None,
            "path": None}


def _structurally_valid(row) -> bool:
    return not validate_obstacle(row, ws=None)


def read(ws) -> list[dict]:
    """Tolerant read: structurally valid rows, sorted by parsed id
    number (rollover-safe); corrupt/invalid rows skipped, never a
    raise. Artifact existence is NOT re-checked — a row is history."""
    d = _registry(ws)
    if not d.is_dir():
        return []
    out: list[tuple[int, dict]] = []
    for p in sorted(d.iterdir()):
        m = _FILE_RE.match(p.name)
        if not m:
            continue
        try:
            row = json.loads(p.read_text(encoding="utf-8",
                                         errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and _structurally_valid(row):
            out.append((int(m.group(1)), row))
    out.sort(key=lambda t: t[0])
    return [row for _, row in out]


def face(ws) -> dict:
    """The state digest: {present, count, kinds} — kinds is the
    sorted ``kind=count`` pattern (the claim_pattern idiom), "" when
    the registry is empty."""
    rows = read(ws)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {
        "present": bool(rows),
        "count": len(rows),
        "kinds": "|".join(f"{k}={counts[k]}" for k in sorted(counts)),
    }


# ---------- CLI (the sanctioned producer face) ----------

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="obstacle/1 attribution registry (record at act "
                    "failure; face = the state digest)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record one obstacle row")
    rec.add_argument("ws", help="workspace root")
    rec.add_argument("--kind", required=True,
                     help=f"obstacle kind (one of {', '.join(KINDS)}; "
                          "validated by the library face — one path)")
    rec.add_argument("--cause", required=True,
                     help="one machine-checkable line")
    rec.add_argument("--evidence-path", required=True,
                     help="workspace-relative probe artifact path")
    rec.add_argument("--method-family", required=True,
                     help="the failed act's declared family")
    rec.add_argument("--claim", default=None)
    rec.add_argument("--dispatch-id", dest="dispatch_id", default=None)
    rec.add_argument("--ts", default=None, help="ISO-8601 override")
    fc = sub.add_parser("face", help="print the state digest")
    fc.add_argument("ws", help="workspace root")
    args = ap.parse_args(argv)
    if args.cmd == "face":
        print(json.dumps(face(args.ws), ensure_ascii=False, indent=2))
        return 0
    out = record(args.ws, kind=args.kind, cause=args.cause,
                 evidence_path=args.evidence_path,
                 method_family=args.method_family, claim=args.claim,
                 dispatch_id=args.dispatch_id, ts=args.ts)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["appended"] else 1


if __name__ == "__main__":  # pragma: no cover — CLI face
    sys.exit(main())
