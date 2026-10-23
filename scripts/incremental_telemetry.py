#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""incremental_telemetry.py — the #801 R2b value-change gate for telemetry.

The rc1 production shape: rho stuck at 0.0 still emitted a detector_eval
row per checkpoint (76 dead rows while analysis progress moved 6-9%);
telemetry was ~57-63% of event volume while the analysis output ~6-9%.
The value-change gate: a face emits ONLY when its emitted VALUE changed
since that face's last emission — an unchanged value is SILENT (silence
is the honest idle, the same principle as the #801 wake gate) and the
suppression streak is counted for observability (runs/.telemetry-last.json,
ONE durable per-face digest + suppressed counter).

Contract:
  should_emit(ws, face, value_digest) -> bool
    - first sight or changed value  -> True  (digest refreshed)
    - identical repeat              -> False (suppressed += 1)

Fail-open: any state trouble emits (never suppresses) — losing telemetry
rows is worse than repeating one.

Faces wired (production evidence per face):
  rho_verifier.sample_and_pair  detector_eval  (dead rho=0.0 x76)
  statusline_snapshot.write_snapshot  statusline_snapshot event (the
      snapshot FILE stays fresh — display truth; only the ledger EVENT is
      value-gated)

rank_feeds is deliberately NOT wired: the #157 replay spine (the ranking
is exactly replayable from the event tail) and the #218 last-attempt
health bit pin the per-run emit attempt itself.
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_REL = Path("runs") / ".telemetry-last.json"


def should_emit(ws: str | Path, face: str, value_digest: str) -> bool:
    """True iff value_digest differs from `face`'s last EMITTED value."""
    try:
        path = Path(ws) / STATE_REL
        state = {}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        face_state = dict(state.get(face) or {})
        if face_state.get("digest") == str(value_digest):
            state[face] = {**face_state, "suppressed": int(
                face_state.get("suppressed", 0)) + 1}
            path.write_text(json.dumps(state, ensure_ascii=False,
                                       sort_keys=True), encoding="utf-8")
            return False
        state[face] = {**face_state, "digest": str(value_digest)}
        path.write_text(json.dumps(state, ensure_ascii=False,
                                   sort_keys=True), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 — fail-open: emit rather than suppress
        return True
