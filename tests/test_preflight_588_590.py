# -*- coding: utf-8 -*-
"""tests/test_preflight_588_590.py — #588+#590: host state probed in seconds
(at intake, before the conversation), preconditions asked with probe context.

#588 (adjudicated Phase "-1"): a PRESENCE-tier-only quick probe runs BEFORE
step-0 intake — the machinery exists (toolchain check, #474 tiers), it was
merely sequenced after the conversation. New `quick_presence(ws)` returns a
host-health banner in O(seconds); NEVER adopts values or downgrades anything
(#449 needs-first precedence intact).

#590 (adjudicated): a `preconditions` decision group rides the SAME native
question round; probe findings attach as decision `context` only (pending is
the floor — the probe never auto-fills an answer).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import toolchain  # noqa: E402


# ---------- #588: quick presence preflight ----------

def test_quick_presence_returns_banner(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    banner = toolchain.quick_presence(ws)
    assert isinstance(banner, str) and banner, "a banner string always returns"
    assert "host" in banner.lower()


def test_quick_presence_never_raises(tmp_path):
    ws = tmp_path / "nonexistent"
    banner = toolchain.quick_presence(ws)
    assert isinstance(banner, str)


# ---------- #590: preconditions decision group ----------

