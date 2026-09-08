# -*- coding: utf-8 -*-
"""tests/test_windowed_stalker_template.py — issue #162 Unit 4:
templates/frida/windowed-stalker.js.tmpl shape contract.

The first adapt-expected template (consume: adapt): windowed follow-on-
enter / unfollow-on-leave instruction tracing with module exclusion,
macro census (onCallSummary hot offsets) BEFORE micro instruction
filtering, and a memory-op filter shape. Its known-variance regions
(module set, offset resolution path, filter predicate) MUST be named in
the header and surface in the ext-index description.

Frida >= 16 API audit is INLINE (binding): the legacy static
Memory.read*/write* accessors were removed in Frida 16 — the template
must use the modern NativePointer instance forms and carry a
legacy->modern mapping comment so the breakage is annotated, not silent
(#356 W5 precedent: comments may mention the old API; code may not).

Contract level: shape only (frozen placeholder set, bracket balance,
no absolute paths / real IPs, API audit) — test_frida_templates.py is
the precedent. All values synthetic (libtarget.so, 0x0001000-style
offsets); no real app/package identifiers anywhere (privacy rule).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRIDA_DIR = ROOT / "templates" / "frida"
TMPL = FRIDA_DIR / "windowed-stalker.js.tmpl"
README = FRIDA_DIR / "README.md"
EXT_INDEX = ROOT / "tools" / "_INDEX.ext.yaml"

PLACEHOLDERS = {"TARGET_MODULE", "EXCLUDE_MODULES", "OUTFILE", "SAMPLE_SHA256"}

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|tmp|opt|var|etc)/)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _strip_js_strings_and_comments(text: str) -> str:
    """Same state machine as test_frida_templates.py (strings + comments
    stripped, not a JS parser)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    j += 1
                    break
                j += 1
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _is_balanced(text: str) -> bool:
    stack: list[str] = []
    pairs = {")": "(", "}": "{", "]": "["}
    for ch in _strip_js_strings_and_comments(text):
        if ch in "({[":
            stack.append(ch)
        elif ch in ")}]":
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def _placeholder_keys(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _code(text: str) -> str:
    return _strip_js_strings_and_comments(text)


# ---------------- (a) frozen placeholder set -------------------------------

def test_placeholders_exactly_frozen_set():
    text = TMPL.read_text(encoding="utf-8")
    assert _placeholder_keys(text) == PLACEHOLDERS


# ---------------- (b) substituted skeleton is balanced ---------------------

def test_substituted_skeleton_balanced_no_residue():
    rendered = _PLACEHOLDER.sub(
        lambda m: {
            "TARGET_MODULE": "libtarget.so",
            "EXCLUDE_MODULES": "libexclude1.so,libexclude2.so",
            "OUTFILE": "stalker-window.jsonl",
            "SAMPLE_SHA256": "bb" * 32,
        }.get(m.group(1), m.group(0)),
        TMPL.read_text(encoding="utf-8"))
    assert "{{" not in rendered, "substitution left placeholder residue"
    assert _is_balanced(rendered), "JS skeleton has unbalanced delimiters"


# ---------------- (c) privacy: synthetic values only -----------------------

def test_no_host_absolute_paths_or_real_ips():
    text = TMPL.read_text(encoding="utf-8")
    assert not _ABS_PATH.search(text), "template contains a host absolute path"
    assert not _IP.search(text), "template contains a real IPv4 address"


# ---------------- (d) Frida >= 16 API audit (inline, binding) --------------

def test_modern_nativepointer_memory_api_in_code():
    code = _code(TMPL.read_text(encoding="utf-8"))
    assert "readByteArray(" in code, \
        "modern NativePointer.readByteArray form missing from code"


def test_legacy_static_memory_accessors_absent_from_code():
    code = _code(TMPL.read_text(encoding="utf-8"))
    assert not re.search(r"\bMemory\.read", code), \
        "legacy static Memory.read* accessor in code (removed in Frida 16)"
    assert not re.search(r"\bMemory\.write", code), \
        "legacy static Memory.write* accessor in code (removed in Frida 16)"


def test_legacy_to_modern_mapping_comment_present():
    """The breakage must be annotated, not silent: the header carries the
    legacy->modern mapping (comments MAY name the legacy API)."""
    text = TMPL.read_text(encoding="utf-8")
    assert "Memory.readByteArray" in text and "Memory.writeByteArray" in text, \
        "legacy->modern mapping comment missing"
    assert "removed in frida 16" in " ".join(text.lower().split()), \
        "in-file audit must state the Frida-16 removal"


def test_header_declares_frida17_requirement():
    text = TMPL.read_text(encoding="utf-8")
    header = text[:text.index("'use strict';")]
    assert re.search(r"Requires:\s*frida\s*>=\s*17", header), \
        "header must declare 'Requires: frida >= 17'"


# ---------------- (e) adapt-expected contract ------------------------------

def test_header_declares_consume_adapt_marker():
    """Criterion 2 self-declaration — ext-scan classifies this template
    consume: adapt from this header line."""
    text = TMPL.read_text(encoding="utf-8")
    header = text[:text.index("'use strict';")]
    assert "consume: adapt" in header


def test_header_names_known_variance_regions():
    text = TMPL.read_text(encoding="utf-8").lower()
    for needle in ("module set", "offset resolution", "filter predicate"):
        assert needle in text, f"known-variance region not named: {needle}"


def test_skeleton_carries_windowed_stalker_shape():
    code = _code(TMPL.read_text(encoding="utf-8"))
    for needle in ("Stalker.follow(", "Stalker.unfollow(",
                   "Stalker.exclude(", "onCallSummary",
                   "Interceptor.attach("):
        assert needle in code, f"windowed-tracing shape missing: {needle}"
    # macro census BEFORE micro filtering: the onCallSummary census
    # recordCensus phase precedes the isMemoryOp micro predicate in the
    # comment-stripped code body
    assert code.index("onCallSummary") < code.index("isMemoryOp"), \
        "macro census must precede the micro instruction filter"


def test_vm_only_artifact_note_present():
    text = TMPL.read_text(encoding="utf-8")
    assert "VM" in text and "1337" in text, \
        "VM-only channel warning must be present (directory convention)"


# ---------------- (f) README row + ext-index integration -------------------

def test_readme_carries_template_row():
    text = README.read_text(encoding="utf-8")
    assert "windowed-stalker.js.tmpl" in text, \
        "templates/frida/README.md missing the new template row"


def test_ext_index_entry_is_typed_adapt_with_contract_desc():
    import yaml
    data = yaml.safe_load(EXT_INDEX.read_text(encoding="utf-8"))
    entries = {e["name"]: e for e in data["ext"]}
    e = entries["windowed-stalker.js"]
    assert e["type"] == "template"
    assert e["consume"] == "adapt"
    assert e["source"] == "templates/frida/windowed-stalker.js.tmpl"
    desc = e["description"].lower()
    for needle in ("module set", "offset resolution", "filter predicate"):
        assert needle in desc, \
            f"ext-index desc must name the known-variance region: {needle}"
    # hit-information minimum contract (#162 addendum): scenario + how +
    # expected outcome — expectation wording, never a guaranteed fact
    assert "scenario:" in desc
    assert "how:" in desc
    assert "expected outcome:" in desc
