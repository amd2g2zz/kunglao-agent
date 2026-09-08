# -*- coding: utf-8 -*-
"""#165 — templates/unidbg/harness.java.tmpl shape contract (adapt tier).

Shape-level tests for the minimal unidbg harness skeleton:

  (a) placeholder set is exactly the 5 frozen keys, no other {{...}};
  (b) fully-substituted skeleton leaves no residue and is brace-balanced
      (Java string/comment stripping, not a parser — same discipline as
      the Frida template tests);
  (c) synthetic values: no host absolute paths and no real IPv4s;
  (d) the corpus-validated harness shape is present: builder -> file
      resolver -> VM + JNI provider -> resolver-before-load ordering ->
      JNI_OnLoad -> module-scoped trace -> dispatch;
  (e) header carries the asset-tier contract: consume: adapt marker,
      Scenario/How/Expected lines, KNOWN-VARIANCE regions;
  (f) deployment-preconditions pointer present.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMPL = ROOT / "templates" / "unidbg" / "harness.java.tmpl"

PLACEHOLDERS = {"LIB_PATH", "PACKAGE_NAME", "TARGET_CLASS", "TARGET_METHOD", "TARGET_SIGNATURE"}
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|tmp|opt|var|etc)/)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _render(text: str, **params: str) -> str:
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), text)


def _strip_java_strings_and_comments(text: str) -> str:
    """Strip strings/comments (state machine, not a parser). Handles plain
    "..." strings and // + /* */ comments; the template avoids char literals
    and text blocks by design."""
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
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _brace_balanced(code: str) -> bool:
    stack: list[str] = []
    pairs = {")": "(", "}": "{", "]": "["}
    for ch in code:
        if ch in "({[":
            stack.append(ch)
        elif ch in ")}]":
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


# ---------- (a) placeholder contract ----------

def test_placeholders_exactly_frozen_keys():
    assert set(_PLACEHOLDER.findall(TMPL.read_text(encoding="utf-8"))) == PLACEHOLDERS


# ---------- (b) substitution + balance ----------

def test_substituted_skeleton_balanced_no_leftover():
    rendered = _render(
        TMPL.read_text(encoding="utf-8"),
        LIB_PATH="vendor/target.apk.so",
        PACKAGE_NAME="com.example.target",
        TARGET_CLASS="com/example/target/Sign",
        TARGET_METHOD="sign",
        TARGET_SIGNATURE="(Ljava/lang/String;)",
    )
    assert "{{" not in rendered, "substitution left placeholder residue"
    assert _brace_balanced(_strip_java_strings_and_comments(rendered)), (
        "skeleton braces unbalanced after string/comment strip"
    )


# ---------- (c) synthetic hygiene ----------

def test_no_host_absolute_paths_or_real_ips():
    text = TMPL.read_text(encoding="utf-8")
    assert not _ABS_PATH.search(text), "template contains a host absolute path"
    assert not _IP.search(text), "template contains a real IPv4 address"


# ---------- (d) corpus-validated harness shape ----------

def test_harness_shape_order_present():
    text = TMPL.read_text(encoding="utf-8")
    code = _strip_java_strings_and_comments(text)
    marks = [
        ("AndroidEmulatorBuilder", "emulator build"),
        ("addIOResolver", "file resolver"),
        ("createDalvikVM", "Dalvik VM"),
        ("setJni", "JNI provider"),
        ("setVerbose", "verbose boundary logging"),
        ("loadLibrary", "library load"),
        ("traceCode", "module-scoped trace (armed before JNI_OnLoad so early code lands in the window)"),
        ("callJNI_OnLoad", "JNI_OnLoad"),
        ("callStaticJniMethodObject", "dispatch"),
    ]
    pos = -1
    for token, label in marks:
        found = code.find(token)
        assert found != -1, f"harness shape missing: {label}"
        assert found > pos, f"harness shape out of order at: {label}"
        pos = found
    # resolver-before-load discipline: addIOResolver precedes loadLibrary
    assert code.find("addIOResolver") < code.find("loadLibrary"), (
        "file resolver must be registered BEFORE loadLibrary (chain order)"
    )


# ---------- (e) asset-tier header contract ----------

def test_header_carries_adapt_contract():
    text = TMPL.read_text(encoding="utf-8")
    header = text[: text.index("*/")]
    assert "consume: adapt" in header, "adapt marker must be in the header"
    for token in ("Scenario:", "How:", "Expected outcome:"):
        assert token in header, f"header missing {token} line"
    assert "KNOWN-VARIANCE REGIONS" in header, "known-variance region block required"


# ---------- (f) deployment pointer ----------

def test_deployment_preconditions_pointer():
    text = TMPL.read_text(encoding="utf-8")
    assert "install_unidbg.sh" in text and "JDK + Maven" in text, (
        "template must point at the deployment preconditions installer"
    )
