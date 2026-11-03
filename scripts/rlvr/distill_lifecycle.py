# -*- coding: utf-8 -*-
"""rlvr/distill_lifecycle.py — the 3-strike optimize-then-remove
ladder (the P1 update policy's utility decay, instanced in the
distillation domain).

Up to MAX_OPTIMIZATION_ROUNDS re-scored rounds per item (retrigger
description / recontent / recoverage); a passing round RE-ADMITS (the
strike counter resets); all rounds exhausted still low → the item is
REMOVED from the LIBRARY surfaces: the `distill_removed` stamp on the
pool document makes the scored playbook view (distill_score) skip it —
read-side composition over the P1 faces, CALLED not modified. The
document STAYS on disk and the rollout history stays in the ledger —
the lesson lives in accounts, not on shelves.

Zero telemetry points (Standard 11): refusals raise to the caller.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rlvr import episode_schema as es  # noqa: E402

#: policy constants (documented, not fitted) — the owner ruling's ladder
MAX_OPTIMIZATION_ROUNDS = 3


class LifecycleError(ValueError):
    """The lifecycle face refused: an unknown item, a blockless episode,
    or a round recorded on an already-removed item."""


def _load(ws, claim: str) -> tuple[Path, dict, str]:
    from rlvr import episode_pool as pool  # noqa: PLC0415 — lazy
    path = pool.episode_path(ws, str(claim))
    if not path.is_file():
        raise LifecycleError(f"{claim}: no pool episode — nothing to "
                             "re-score")
    doc, body = es.read_episode_file(path)
    if not (doc.get("distill") or {}).get("schema"):
        raise LifecycleError(f"{claim}: carries no distill block")
    return path, doc, body


def record_round(ws, claim: str, *, admitted: bool, reason: str) -> dict:
    """One optimization round: the re-score verdict recorded on the item.
    A passing round re-admits (strikes reset); a failed round strikes;
    reaching MAX_OPTIMIZATION_ROUNDS removes the item from the library
    surfaces (the removal stamp — never a file deletion). Returns the
    round's outcome {strikes, removed, optimization_rounds}."""
    path, doc, body = _load(ws, claim)
    block = doc["distill"]
    if block.get("removed"):
        raise LifecycleError(
            f"{claim}: already removed — the ladder is exhausted, "
            "history lives in the ledger")
    rounds = list(block.get("rounds") or [])
    rounds.append({"admitted": bool(admitted),
                   "reason": str(reason or ""),
                   "at": _now_z()})
    block["rounds"] = rounds
    block["optimization_rounds"] = \
        int(block.get("optimization_rounds") or 0) + 1
    strikes = 0 if admitted else int(block.get("strikes") or 0) + 1
    if strikes:
        block["strikes"] = strikes
    else:
        block.pop("strikes", None)
    removed = False
    if strikes >= MAX_OPTIMIZATION_ROUNDS:
        block["removed"] = {"at": _now_z(), "reason": str(reason or ""),
                            "strikes": strikes}
        removed = True
    # immutability face: replace the block, never mutate the loaded one
    doc = dict(doc, distill=block)
    es.write_episode_file(path, doc, body=body)
    return {"strikes": strikes, "removed": removed,
            "optimization_rounds": block["optimization_rounds"]}


def is_removed(doc: dict) -> bool:
    """True when the document carries the removal stamp (the library
    surfaces consult this through distill_score._is_removed)."""
    return bool((doc or {}).get("distill", {}).get("removed"))


def _now_z() -> str:
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        return utc_now_z()
    except Exception:  # noqa: BLE001 — the round stamp needs a clock
        import datetime
        return datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
