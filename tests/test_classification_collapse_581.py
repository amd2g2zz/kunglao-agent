# -*- coding: utf-8 -*-
"""tests/test_classification_collapse_581.py — #581: the 1-module-use
Classification dataclass collapses to a NamedTuple view.

Ponytail (yagni): Classification had internal-only construction + tests
asserting its properties. Keep the PUBLIC behavior (the classifier returns
something with .response/.charter_state/.rationale — the tests and prose
contract) but drop the class for a NamedTuple view (cheaper, immutable, same
attribute surface). No behavior change.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import error_response as er  # noqa: E402


def test_classify_returns_view_with_properties():
    c = er.classify_vmrun("vmrun start vmx")
    assert c.response is not None
    assert c.charter_state
    assert c.rationale


def test_class_is_gone_namedtuple_view():
    src = (ROOT / "scripts" / "error_response.py").read_text(encoding="utf-8")
    assert "@dataclass" not in src.split("class Classification")[0][-60:], \
        "the dataclass decorator is gone — NamedTuple view (#581)"
    for attr in ("response", "charter_state", "rationale"):
        assert attr in src, f"view keeps .{attr}"


def test_public_surface_survives():
    assert hasattr(er, "classify_vmrun")
