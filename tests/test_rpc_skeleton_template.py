# -*- coding: utf-8 -*-
"""#165 — templates/frida/rpc-skeleton.js.tmpl shape contract (adapt tier).

RED-first shape tests for the Frida RPC export-surface skeleton:

  (a) placeholder set is exactly the 5 frozen keys, no other {{...}};
  (b) fully-substituted skeleton leaves no placeholder residue and is a
      bracket-balanced JS skeleton (string/comment stripping, not a parser);
  (c) no host absolute paths and no real IPv4 addresses (synthetic values
      only, same bar as the cfg-hook template tests);
  (d) Frida >= 16 API audit: code uses NativePointer instance methods;
      the legacy static Memory.read*/write* surface may appear only in
      comments explaining the migration — never in code;
  (e) header declares "Requires: frida >= 16";
  (f) known-variance regions documented: exported surface, message
      protocol, error channel — each carries a KNOWN-VARIANCE marker;
  (g) the rpc.exports surface and the host-side send/error message
      contract are present.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMPL = ROOT / "templates" / "frida" / "rpc-skeleton.js.tmpl"

PLACEHOLDERS = {"TARGET_PROCESS", "JAVA_CLASS", "JAVA_METHOD", "NATIVE_LIB", "NATIVE_SYMBOL"}

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|tmp|opt|var|etc)/)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _render(text: str, **params: str) -> str:
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), text)


def _strip_js_strings_and_comments(text: str) -> str:
    """Strip strings and comments (simple state machine — not a JS parser)."""
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


# ---------- (a) placeholder contract ----------

def test_placeholders_exactly_frozen_keys():
    text = TMPL.read_text(encoding="utf-8")
    assert set(_PLACEHOLDER.findall(text)) == PLACEHOLDERS


# ---------- (b) substitution sanity ----------

def test_substituted_skeleton_balanced_and_no_leftover():
    rendered = _render(
        TMPL.read_text(encoding="utf-8"),
        TARGET_PROCESS="com.example.target",
        JAVA_CLASS="com/example/target/Sign",
        JAVA_METHOD="signPayload",
        NATIVE_LIB="libtarget.so",
        NATIVE_SYMBOL="nativeSign",
    )
    assert "{{" not in rendered, "substitution left placeholder residue"
    assert _is_balanced(rendered), "skeleton has unbalanced delimiters"


# ---------- (c) synthetic values ----------

def test_no_host_absolute_paths_or_real_ips():
    text = TMPL.read_text(encoding="utf-8")
    assert not _ABS_PATH.search(text), "template contains a host absolute path"
    assert not _IP.search(text), "template contains a real IPv4 address"


# ---------- (d) Frida >= 16 API audit ----------

def test_code_uses_no_legacy_memory_statics():
    text = TMPL.read_text(encoding="utf-8")
    code = _strip_js_strings_and_comments(text)
    assert not re.search(r"Memory\.(read|write)", code), (
        "legacy Memory.read*/write* statics must not appear in code (removed in "
        "the modern Frida surface); use NativePointer instance methods"
    )


def test_code_uses_nativepointer_instance_methods():
    text = TMPL.read_text(encoding="utf-8")
    code = _strip_js_strings_and_comments(text)
    assert re.search(r"\.(readCString|readByteArray|readPointer)\(", code), (
        "skeleton must demonstrate the modern NativePointer instance-method surface"
    )


def test_migration_annotation_present():
    """The audit is inline: a comment maps legacy statics -> instance methods."""
    text = TMPL.read_text(encoding="utf-8")
    assert re.search(r"Memory\.read\w*\s*\(|Memory\.readCString", text), (
        "expected a comment annotating the legacy Memory.read* static form"
    )
    assert "instance method" in text or "instance-method" in text


# ---------- (e) declared requirement ----------

def test_header_declares_frida_requirement():
    text = TMPL.read_text(encoding="utf-8")
    header = text[: text.index("'use strict';")] if "'use strict';" in text else text[:2000]
    assert re.search(r"Requires:\s*frida\s*>=\s*16", header), (
        "header must declare 'Requires: frida >= 16'"
    )


# ---------- (f) known-variance regions ----------

def test_known_variance_regions_documented():
    text = TMPL.read_text(encoding="utf-8")
    header = text[: text.index("*/")]
    assert "KNOWN-VARIANCE REGIONS" in header, "known-variance region block required"
    for region in ("exported surface", "message protocol", "error channel"):
        assert re.search(region.replace(" ", r"\s+"), header, re.IGNORECASE), (
            f"known-variance region not documented: {region}"
        )


# ---------- (g) export surface + host contract ----------

def test_rpc_exports_surface_present():
    code = _strip_js_strings_and_comments(TMPL.read_text(encoding="utf-8"))
    assert "rpc.exports" in code, "skeleton must define the rpc.exports surface"


def test_host_message_contract_documented():
    text = TMPL.read_text(encoding="utf-8")
    assert "send" in text and "error" in text, (
        "host-side contract comment must cover the send/error message types"
    )
    assert re.search(r"\bspawn\b", text) and re.search(r"\bresume\b", text), (
        "host-side contract comment must cover the attach/spawn+resume choice"
    )
