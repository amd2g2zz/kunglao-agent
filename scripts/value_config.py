#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""value_config.py — AB-VALUE experiment flag (#823, KUNGLAO_VALUE_ALGO).

Gates the N-arm mechanisms of the #823 value algorithm behind a single
environment switch so O-arm and N-arm run the SAME binary/hooks/skill and
differ only in the algorithm (AB-EXPERIMENT-DESIGN.md §3).

This module is deliberately FAIL-LOUD — the opposite of the production
fail-open posture (mirror: scripts/priority_ratio.py load_value_weights,
where corrupt input degrades to weight 1.0). Reason: the flag IS the
experiment's arm assignment. A silent fallback to off would run N-arm
configurations as O-arm and corrupt the comparison; an unrecognized value
must abort loudly, never guess.

Off (env unset or falsy) is byte-identical to pre-#823 behavior: every
consumer must short-circuit on is_enabled() before touching any new code
path.
"""
import os

ENV_NAME = "KUNGLAO_VALUE_ALGO"

_TRUTHY = {"1", "true", "yes", "on", "n"}
_FALSY = {"0", "false", "no", "off", ""}


class FlagError(RuntimeError):
    """Raised on an unrecognized flag value — experiment control must not guess."""


def raw() -> str | None:
    return os.environ.get(ENV_NAME)


def is_enabled() -> bool:
    """True = N-arm (#823 P1-P3 active). Unset/empty = off (O-arm)."""
    v = raw()
    if v is None:
        return False
    v = v.strip().lower()
    if v in _TRUTHY:
        return True
    if v in _FALSY:
        return False
    raise FlagError(
        f"{ENV_NAME}={v!r} is not a recognized value "
        f"(on: {sorted(_TRUTHY)} / off: {sorted(_FALSY)} / unset=off)"
    )


def arm() -> str:
    """Experiment arm label: 'N' when enabled, 'O' otherwise (bench receipts)."""
    return "N" if is_enabled() else "O"
