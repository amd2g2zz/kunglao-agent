# -*- coding: utf-8 -*-
"""rlvr/authorization.py — the engagement authorization scope.

The disposition object's second gate asks one question: was the episode's
target inside the declared authorization? This module is the single answer
— a pure, exact-match read over the `task_spec` `authorization` block that
the orchestrator copies verbatim into the dispatch envelope.

    authorization:
      targets: ["target.example.com", "bins/<sha256>"]
      excluded: ["target.example.com/admin"]
      authorization_ref: "ticket-42"

Rules (fail closed; the anti-spoof posture of the red-team glob lesson):

- an absent or malformed block authorizes NOTHING — a dispatch without an
  authorization context is not authorized;
- an empty `targets` list authorizes nothing (no declared scope, no work);
- a target is authorized iff it exactly equals a declared target and no
  declared exclusion (whitespace-stripped, case-sensitive);
- matching is exact — no globs, prefixes, or substrings: a wildcard would
  let one typo silently widen the engagement scope;
- every entry must be a non-empty string; one bad entry invalidates the
  whole block (a typo must never leave a partial scope standing).

No I/O, no clock, no model call.
"""
from __future__ import annotations

import copy


def _clean_entries(values) -> list[str] | None:
    """The stripped entries of a declared list, or None when the value is
    not a list of non-empty strings (the whole block then fails closed)."""
    if not isinstance(values, list):
        return None
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            return None
        token = value.strip()
        if not token:
            return None
        cleaned.append(token)
    return cleaned


def _scope(authorization) -> tuple[list[str], list[str]] | None:
    """(targets, excluded) when the block declares a usable scope."""
    if not isinstance(authorization, dict):
        return None
    targets = _clean_entries(authorization.get("targets"))
    if not targets:
        return None
    excluded = _clean_entries(authorization.get("excluded", []))
    if excluded is None:
        return None
    return targets, excluded


def authorized_target(authorization, target) -> bool:
    """True iff `target` is inside the declared engagement scope."""
    scope = _scope(authorization)
    if scope is None:
        return False
    if not isinstance(target, str):
        return False
    needle = target.strip()
    if not needle:
        return False
    targets, excluded = scope
    return needle in targets and needle not in excluded


def authorization_ref(authorization) -> str | None:
    """The declared provenance string (`authorization_ref`), or None."""
    if not isinstance(authorization, dict):
        return None
    ref = authorization.get("authorization_ref")
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    return ref or None


def authorization_from_task_spec(task_spec) -> dict | None:
    """A COPY of the `task_spec.authorization` block, or None when
    absent/malformed (the dispatch copies this block verbatim). The copy
    keeps the caller's task_spec immutable if the consumer mutates."""
    if not isinstance(task_spec, dict):
        return None
    block = task_spec.get("authorization")
    return copy.deepcopy(block) if isinstance(block, dict) else None
