# -*- coding: utf-8 -*-
"""tests/test_uv_mandate_766.py — the uv-only python discipline is written
down and nothing teaches bare pip (issue #766).

Owner ruling 2026-10-18: agents keep hunting for python environments and
reaching for pip. The mandate lives in the three session-facing docs
(root CLAUDE.md, SKILL.md, the base template every workspace CLAUDE.md
renders from), and no product doc or product-emitted message may teach
a bare `pip install` / `pip3 install` — uv-prefixed forms (`uv pip
install`) are the sanctioned ad-hoc face, `uv sync` is the dep face.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# #767: the pinned installable source for the camoufox-reverse dep.
CAMOUFOX_PIN = ("git+https://github.com/WhiteNightShadow/"
                "camoufox-reverse-mcp.git@v1.1.1")

MANDATE_DOCS = (
    ROOT / "CLAUDE.md",
    ROOT / "SKILL.md",
    ROOT / "templates" / "CLAUDE.md.base.tmpl",
)
UV_SCAN_DOCS = MANDATE_DOCS + (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "scripts" / "kunglao-init.py",
    ROOT / "scripts" / "mcp_probe.py",
)

_BARE_PIP = re.compile(r"(?<!uv )(?<![\w-])pip3? install")
_FORBID_MENTION = re.compile(r"\bnever\b|禁止|不要", re.IGNORECASE)


def test_mandate_present_in_the_three_docs():
    for doc in MANDATE_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert "uv run" in text, doc
        assert "uv sync" in text, doc
        assert "uv pip install" in text, doc


def test_no_doc_teaches_bare_pip():
    for doc in UV_SCAN_DOCS:
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(),
                                 1):
            for m in _BARE_PIP.finditer(line):
                assert _FORBID_MENTION.search(line), (
                    f"{doc.name}:{i} teaches a bare pip form "
                    f"(prefix with `uv ` or phrase it as a prohibition): "
                    f"{line.strip()[:120]}")


def test_install_guidance_strings_are_uv_prefixed():
    init = (ROOT / "scripts" / "kunglao-init.py").read_text(encoding="utf-8")
    probe = (ROOT / "scripts" / "mcp_probe.py").read_text(encoding="utf-8")
    # #767 ruling: the camoufox dep is NOT on any public index — guidance
    # names the pinned installable source, resolved by uv itself.
    assert CAMOUFOX_PIN in init
    assert (f"uv run --no-project --with {CAMOUFOX_PIN} "
            "python -m camoufox_reverse_mcp --help") in init
    assert CAMOUFOX_PIN in probe


def test_base_template_carries_the_full_discipline():
    tmpl = (ROOT / "templates" / "CLAUDE.md.base.tmpl").read_text(
        encoding="utf-8")
    assert "uv-only, no exceptions" in tmpl
    assert "never bare pip" in tmpl
    assert "uv run --project {{skill_dir}} python ..." in tmpl
