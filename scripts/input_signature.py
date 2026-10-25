#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""input_signature.py — signature-gated persistence as a shared primitive
(issue 805, task 2: the #750 gate extracted).

The #750 round-close fix (verification_ladder) proved the discipline —
a periodic face whose INPUT signature is unchanged persists and emits
NOTHING (silence is the honest idle) — but kept it site-local. This
module is the extraction: one canonical signature + two suppression
carriers, so every periodic persistence face defaults through the same
primitive instead of re-growing a private one.

Contract:

  signature(shape) -> str
      Canonical sha1 over json.dumps(shape, sort_keys=True) — the SAME
      digest the #750 gate landed (deterministic, order-insensitive via
      sort_keys; callers pass the CONTENT-relevant shape only: time
      projections, render clocks and wall stamps stay OUT).

  stamped(doc, sig) -> dict
      The persisted form: a NEW doc carrying ``sig`` (immutable — the
      builder's doc is never mutated).

  unchanged_doc(path, sig) -> bool
      Doc-carrier suppression: the file at ``path`` parses to a mapping
      whose ``sig`` equals ``sig``. Absent/corrupt/differing -> False
      (fail-open: an unreadable state REBUILDS, never suppresses).

  unchanged_state(state_path, face, sig) -> bool  /  record_state(...)
      State-carrier suppression for faces whose persisted artifact is
      not a JSON doc (markdown digests): one state file, faces keyed
      independently. Same fail-open posture.

The system-wide pin (#805): snapshot/rank/digest/T2-class faces persist
nothing on an unchanged input signature. Adjudicated exceptions live at
their faces, declared not silent: the statusline snapshot FILE stays
fresh-by-design (#801 display truth; only its ledger event is
value-gated) and rank_feeds stays per-run (#801 R2b replay spine).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

#: the schema of the state-carrier sidecar (one file, faces keyed)
STATE_SCHEMA = "input-signature-state/1"


def signature(shape) -> str:
    """Canonical sha1 over the sort_keys JSON of ``shape`` — the #750
    digest, single-sourced. ``shape`` must carry ONLY content-relevant
    data (clocks and projections belong at the render layer)."""
    payload = json.dumps(shape, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def stamped(doc: dict, sig: str) -> dict:
    """A NEW doc carrying ``sig`` — the immutable stamp (never mutate the
    caller's builder doc)."""
    return {**doc, "sig": str(sig)}


def _read_doc(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def unchanged_doc(path, sig: str) -> bool:
    """True iff the persisted doc at ``path`` carries exactly ``sig``.
    Fail-open: absent/unreadable/non-mapping/differing -> False."""
    try:
        doc = _read_doc(Path(path))
    except OSError:
        return False
    if doc is None:
        return False
    return doc.get("sig") == str(sig)


def _read_state(state_path: Path) -> dict:
    doc = _read_doc(state_path)
    if doc is None or doc.get("schema") != STATE_SCHEMA:
        return {}
    faces = doc.get("faces")
    return faces if isinstance(faces, dict) else {}


def unchanged_state(state_path, face: str, sig: str) -> bool:
    """State-carrier suppression: ``face``'s recorded digest == ``sig``.
    Fail-open: absent/corrupt/differing -> False (rebuild)."""
    try:
        face_state = _read_state(Path(state_path)).get(face) or {}
    except OSError:
        return False
    return isinstance(face_state, dict) \
        and face_state.get("sig") == str(sig)


def record_state(state_path, face: str, sig: str) -> None:
    """Record ``face``'s persisted digest in the sidecar (immutable
    update; tmp+replace write; best-effort — a failed record only means
    the next run rebuilds)."""
    path = Path(state_path)
    faces = dict(_read_state(path))
    faces[face] = {"sig": str(sig)}
    doc = {"schema": STATE_SCHEMA, "faces": faces}
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:  # fail-open: the record is advisory...
        warn("input_signature.record_state",
             f"{type(exc).__name__}: {exc} — the suppression record is "
             "advisory; the next run rebuilds")  # ...but never silent
