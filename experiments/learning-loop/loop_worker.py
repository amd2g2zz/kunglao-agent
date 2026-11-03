# -*- coding: utf-8 -*-
"""loop_worker.py — the mock worker seam (#913).

The #887 harness posture, as a face: the loop's worker is FLAT and
deterministic, never a real LLM — the answering family verifies at
the cheap bill, every other family never verifies at the expensive
bill, and a situation outside the truth table is DEAD (nothing
answers). No proficiency drift: the policy learns, the worker
doesn't, so every realized improvement is attributable to the policy
faces.

The worker output MAY carry a ``phase_challenge`` key (the phase
envelope's challenge channel — the loop validates it against the
closed vocab). ``_worker_execute`` is the fault-shape of the seam:
the worker_exception mode raises HERE, so the loop's seam catches
what a real worker crash produces.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parents[1] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: the flat worker's honest bills (the loop_sim_v3 flat worker)
RIGHT_TOKENS = 1000
WRONG_TOKENS = 4000
RIGHT_SECONDS = 10.0
WRONG_SECONDS = 40.0

#: situation -> the family that actually answers it (the worker's
#: truth; reused from the loop_sim_v3 truth table so all the drivers
#: describe one world); a situation outside the map is DEAD
SITUATIONS: dict[str, str] = {
    "offsets": "static-decompile",
    "packer": "dynamic-trace",
    "grammar": "crypto-core-identification",
}

#: the tracked family — the worker world's benchmark family (the
#: loop_sim_v3 constant)
TRACKED = "static-decompile"

#: the worker seam's shape: (situation, family) -> the flat outcome
WorkerFn = Callable[[str, str], dict[str, Any]]


class LoopWorkerError(RuntimeError):
    """The mock worker's crash — the worker_exception fault payload."""


def mock_worker(situation: str, family: str) -> dict[str, Any]:
    """THE MOCK WORKER (#887 harness posture) — flat and
    deterministic, never a real LLM."""
    true = SITUATIONS.get(situation)
    if true is not None and family == true:
        return {"verified": True, "tokens": RIGHT_TOKENS,
                "seconds": RIGHT_SECONDS}
    return {"verified": False, "tokens": WRONG_TOKENS,
            "seconds": WRONG_SECONDS}


def _worker_execute(situation: str, family: str, *,
                    fault: str | None = None) -> dict[str, Any]:
    """The fault-shape of the worker seam: the worker_exception mode
    raises HERE, so the loop's seam catches what a real worker crash
    produces."""
    if fault == "worker_exception":
        raise LoopWorkerError(
            f"loop913: the mock worker crashed on {family}/{situation}")
    return mock_worker(situation, family)
