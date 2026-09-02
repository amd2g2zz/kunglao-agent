#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness_common.py — the ONE utc_now time-stamp source (#863 Family F).

Fifty-three utc_now-style definition copies (issue recount: 4 output shapes
across scripts/, hooks/ and tools/static/) collapsed into three functions:

  * ``utc_now()``     — tz-aware UTC datetime (``datetime.now(tz=utc)``);
                        the stamping primitive, former shape A.
  * ``utc_now_z()``   — second-precision ISO-8601 UTC with a ``Z`` suffix
                        (``"YYYY-MM-DDTHH:MM:SSZ"``); former shapes B
                        (``strftime("%Y-%m-%dT%H:%M:%SZ")``) and C
                        (``isoformat(timespec="seconds").replace("+00:00",
                        "Z")``) are byte-equivalent for the same instant and
                        therefore collapse into this one function (pinned by
                        tests/test_harness_common_863g.py).
  * ``utc_now_iso()`` — second-precision ISO-8601 UTC with a ``+00:00``
                        offset suffix; the one true textual variant
                        (failure_analysis_gate / outcome_capture schema
                        stamps), former shape D.

Consumers alias the util function under their former local name so call
sites stay byte-identical::

    from harness_common import utc_now_z as _utc_now   # scripts/ sibling
    from harness_common import utc_now                 # scripts/ sibling

hooks/ side goes through the #671 path-hygiene authority (see
hooks/heartbeat_touch.py); tools/static side adds scripts/ to sys.path
beside its existing _lib bridge. Never redefine a utc_now-style helper —
the confinement test fails the build on any new copy.
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utc_now", "utc_now_z", "utc_now_iso"]


def utc_now() -> datetime:
    """Timezone-aware UTC now (former shape A: 8 copies)."""
    return datetime.now(tz=timezone.utc)


def utc_now_z() -> str:
    """ISO-8601 UTC, second precision, Z suffix — "YYYY-MM-DDTHH:MM:SSZ"
    (former shapes B+C: 43 copies, byte-equivalent spellings)."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    """ISO-8601 UTC, second precision, +00:00 offset suffix
    (former shape D: 2 copies — the kept true variant)."""
    return utc_now().isoformat(timespec="seconds")
