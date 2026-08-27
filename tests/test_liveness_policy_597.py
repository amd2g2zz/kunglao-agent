#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_liveness_policy_597.py — issue #597 drift guard.

Root cause (v0.1.3 root-cause survey, verified against dev c81c797):
liveness/staleness thresholds were hardcoded in 10+ places across hooks/
and scripts/ with ZERO shared source — at least 4 duplicated value-pairs
drifted independently (a comment in event_taxonomy.py even recorded a
hard "20" that silently rots when the value changes).

Adjudicated decision (v0.1.3 plan §D row #597 + §三):
  - The VALUES stay as-is (20/30/35 each deliberate) — this is a
    single-sourcing refactor, NOT a threshold unification.
  - scripts/liveness_policy.py is THE single source; every former
    definition site imports from it (local NAME kept where renaming
    the symbol would ripple, e.g. ``from liveness_policy import
    STUCK_MINUTES`` replaces the assignment line).

This file is the regression guard (tests/test_coverage_policy_564.py
drift-guard pattern): if a future change re-introduces a bare
``_MINUTES = <int>`` assignment in a consumer file, this test fails
loudly with the exact location.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# (a) policy module exports every surveyed constant with its surveyed value.
#     Values are the ADJUDICATED ones — unchanged from pre-#597 code.
# ---------------------------------------------------------------------------

SURVEYED_CONSTANTS: dict[str, int] = {
    # worker-status staleness — hooks/lib_kunglao.py:229 STUCK_MINUTES = 20
    # (scripts/lib_kunglao.py:44 WORKER_PROGRESS_MINUTES = 20 sibling,
    #  external_kicker.py:92 FRESH_WORKER_MINUTES = 20 mirror,
    #  kunglao_resume.py:79 WORKER_FRESH_MINUTES alias)
    "STUCK_MINUTES": 20,
    "WORKER_PROGRESS_MINUTES": 20,
    "FRESH_WORKER_MINUTES": 20,
    # heartbeat staleness — heartbeat.py:17 STALE_MINUTES = 35
    # (kunglao_resume.py:76 HEARTBEAT_STALE_MINUTES = 35 duplicate)
    "STALE_MINUTES": 35,
    "HEARTBEAT_STALE_MINUTES": 35,
    # hook-activation TTL — hook_activation.py:92 DEFAULT_TTL_MINUTES = 30
    # (external_kicker.py:84 ACTIVATION_TTL_MINUTES = 30 duplicate)
    "DEFAULT_TTL_MINUTES": 30,
    "ACTIVATION_TTL_MINUTES": 30,
    # env-state freshness — worker_budget_core.py:26 ENV_STATE_TTL_MINUTES = 30
    # (kunglao-monitor.py:40 ENV_STATE_TTL_MINUTES = 30 duplicate)
    "ENV_STATE_TTL_MINUTES": 30,
    # renewal-margin early warning — heartbeat_tick.py:69
    "RENEW_MARGIN_LOW_MINUTES": 10,
    # kicker dead-session default — external_kicker.py:89
    "DEFAULT_STALE_MINUTES": 10,
}


def test_liveness_policy_exports_all_surveyed_constants() -> None:
    """Every surveyed constant exists in liveness_policy with its adjudicated value."""
    import liveness_policy  # noqa: E402  (pytest.ini pythonpath = scripts)

    missing = [name for name in SURVEYED_CONSTANTS if not hasattr(liveness_policy, name)]
    assert missing == [], (
        f"scripts/liveness_policy.py is missing constants: {missing}. "
        f"Per #597 it must export every former local definition."
    )
    for name, expected in SURVEYED_CONSTANTS.items():
        got = getattr(liveness_policy, name)
        assert got == expected, (
            f"liveness_policy.{name} = {got}, expected {expected} — the "
            f"#597 adjudication froze the VALUES (20/30/35 each deliberate); "
            f"only the SOURCE was unified. Changing a value needs its own "
            f"adjudication, not a silent edit here."
        )


def test_liveness_policy_documents_each_rationale() -> None:
    """Every exported constant carries a per-value rationale (the point of
    single-sourcing: rationale lives WITH the number, not scattered in
    consumer comments that rot)."""
    import liveness_policy

    src = Path(liveness_policy.__file__).read_text(encoding="utf-8")
    for name in SURVEYED_CONSTANTS:
        m = re.search(rf"^{name}\s*=", src, re.MULTILINE)
        assert m, f"{name} should be a module-level assignment in liveness_policy"
        # rationale: at least one comment/docstring line above the assignment
        window = src[: m.start()].splitlines()[-6:]
        assert any("#" in ln or '"""' in ln for ln in window), (
            f"{name} has no rationale comment near its definition — "
            f"#597 requires the per-value rationale to live in the policy module."
        )


# ---------------------------------------------------------------------------
# (b) every former definition site now imports from the policy module.
# ---------------------------------------------------------------------------

# file -> symbols that must NO LONGER be assigned a bare literal there
# (they may appear only as import-bound names).
CONSUMER_EXPECTED_IMPORTS: dict[str, tuple[str, ...]] = {
    "hooks/lib_kunglao.py": ("STUCK_MINUTES",),
    "scripts/lib_kunglao.py": ("WORKER_PROGRESS_MINUTES",),
    "scripts/heartbeat.py": ("STALE_MINUTES",),
    "scripts/hook_activation.py": ("DEFAULT_TTL_MINUTES",),
    "scripts/external_kicker.py": ("ACTIVATION_TTL_MINUTES", "FRESH_WORKER_MINUTES", "DEFAULT_STALE_MINUTES"),
    "scripts/kunglao_resume.py": ("HEARTBEAT_STALE_MINUTES", "WORKER_FRESH_MINUTES"),
    "hooks/worker_budget_core.py": ("ENV_STATE_TTL_MINUTES",),
    "scripts/kunglao-monitor.py": ("ENV_STATE_TTL_MINUTES",),
    "scripts/heartbeat_tick.py": ("RENEW_MARGIN_LOW_MINUTES",),
}


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel,symbols", sorted(CONSUMER_EXPECTED_IMPORTS.items()))
def test_consumers_import_from_policy(rel: str, symbols: tuple[str, ...]) -> None:
    """Each consumer file must carry a liveness_policy import line."""
    src = _source(rel)
    assert re.search(r"from\s+liveness_policy\s+import|import\s+liveness_policy", src), (
        f"{rel} does not import liveness_policy — per #597 all former "
        f"definition sites import from the single source."
    )


@pytest.mark.parametrize("rel,symbols", sorted(CONSUMER_EXPECTED_IMPORTS.items()))
def test_no_local_assignment_of_sourced_symbols(rel: str, symbols: tuple[str, ...]) -> None:
    """The old bare assignment lines must be gone (import-bound instead)."""
    src = _source(rel)
    offenders = [s for s in symbols if re.search(rf"^{s}\s*=", src, re.MULTILINE)]
    assert offenders == [], (
        f"{rel} still assigns {offenders} locally — per #597 replace the "
        f"assignment with an import from liveness_policy."
    )


# ---------------------------------------------------------------------------
# (c) drift guard: NO consumer file may reintroduce a bare
#     ``<NAME>_MINUTES = <int>`` assignment (aliases to other modules are
#     fine — e.g. ``WORKER_FRESH_MINUTES = kicker.FRESH_WORKER_MINUTES``
#     would still be an indirection, but #597 rewires those too).
# ---------------------------------------------------------------------------

GUARDED_CONSUMER_FILES = tuple(sorted(CONSUMER_EXPECTED_IMPORTS))

# a bare minutes-threshold assignment: NAME_MINUTES = <integer literal>
BARE_MINUTES_ASSIGNMENT = re.compile(
    r"^\s*[A-Z][A-Z0-9_]*_MINUTES\s*=\s*-?\d+\s*(?:#.*)?$",
    re.MULTILINE,
)


@pytest.mark.parametrize("rel", GUARDED_CONSUMER_FILES)
def test_drift_guard_no_bare_minutes_assignment(rel: str) -> None:
    """No bare ``X_MINUTES = <int>`` in consumer files — the value must
    come from liveness_policy (single source)."""
    hits = [
        f"line {i}: {ln.strip()}"
        for i, ln in enumerate(_source(rel).splitlines(), start=1)
        if BARE_MINUTES_ASSIGNMENT.search(ln)
    ]
    assert hits == [], (
        f"{rel} carries bare minutes assignments (issue #597 regression):\n  "
        + "\n  ".join(hits)
        + "\nMove the value into scripts/liveness_policy.py and import it here."
    )


def test_event_taxonomy_comment_references_policy_not_hard_number() -> None:
    """event_taxonomy.py:81 used to hardcode "STUCK_MINUTES = 20" in a COMMENT
    (silent rot when the value changes). #597: the comment must point at
    liveness_policy, not restate the number."""
    src = _source("scripts/event_taxonomy.py")
    # the rotten pattern: a comment asserting the VALUE alongside the number
    assert not re.search(r"#.*STUCK_MINUTES\s*=\s*20", src), (
        "scripts/event_taxonomy.py still hardcodes 'STUCK_MINUTES = 20' in a "
        "comment — reference liveness_policy (single source) instead so the "
        "comment cannot rot when the value changes."
    )
    # and the derived STUCK_SECONDS must come from the policy, not 20 * 60
    assert "STUCK_SECONDS" in src, "event_taxonomy.STUCK_SECONDS must stay exported"
    assert not re.search(r"^STUCK_SECONDS\s*=\s*20\s*\*\s*60", src, re.MULTILINE), (
        "event_taxonomy.STUCK_SECONDS must derive from liveness_policy "
        "(e.g. STUCK_MINUTES * 60), not a hardcoded 20 * 60."
    )
