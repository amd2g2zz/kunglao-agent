#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runtime_facts.py — runtime-state fact frontmatter gate (#341, scope A).

Failure class: runtime-derived values (AES keys, tokens, session ids,
nonces, cookies) were recorded as timeless truths — the fact schema had no
temporal scope, so F(K1 decrypts) and F(K2 decrypts) stood as individually
true, non-contradictory facts and the rotation induction (scope B) never
had a mechanical input. The audit evidence F1 (issue #341): the fact
frontmatter carried created/last_reviewed dates only — no temporal_scope /
subject_slot / value_fingerprint / captured_at.

Contract:

- WHICH facts: source in RUNTIME_SOURCES (both vocabularies — the worker
  doc's `static_re | dynamic_re | mixed` face, agents/kunglao-worker.md,
  and lint_facts' 8-value enum's runtime-observation sources) about a
  VOLATILE subject (title or subject_slot matching VOLATILE_SUBJECT_RE —
  a deliberately small pattern set).
- REQUIRED: temporal_scope=runtime, subject_slot (stable slot id, e.g.
  `config-decrypt-key`), value_fingerprint (sha256 hex of the value),
  captured_at (ISO-8601 timestamp). Missing any -> violation; the write
  side (hooks/write_guard.py adjudicate leg) turns violations into a
  fail-closed REJECT.
- HYGIENE: fingerprints only. fingerprint() is the ONLY sanctioned bridge
  from a raw value to a recordable token, and it returns the digest — the
  raw value is never retained. Events/ledger rows carry fingerprints
  (scope B owns the consumer side; the hygiene test pins the join).

Pure function + constants; stdlib only. The checker reads the post-image
TEXT (the write_guard shadow face) and never touches the filesystem.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

# Runtime-observation sources, BOTH vocabularies:
#   worker-doc face (agents/kunglao-worker.md fact schema): static_re |
#   dynamic_re | mixed — dynamic_re/mixed arm the gate;
#   lint_facts VALID_SOURCE enum faces that observe a running target:
#   dynamic-trace | frida-capture | qiling-emu.
# Static faces (static-decompile, public-osint, inference, analyst-judgment,
# vt-pivot) NEVER require the runtime fields (scope pinned by test).
RUNTIME_SOURCES = frozenset({
    "dynamic_re", "mixed",
    "dynamic-trace", "frida-capture", "qiling-emu",
})

# Volatile subjects — small, tested pattern set (issue: key/token/session/
# nonce/cookie). Word-boundary anchored so `keyword`/`keyboard`/`monkey`
# never hit; hyphens are word boundaries, so `config-decrypt-key` hits.
VOLATILE_SUBJECT_RE = re.compile(
    r"\b(keys?|secrets?|tokens?|sessions?|nonces?|cookies?|credentials?"
    r"|passwords?|passphrases?|tickets?|api[\s_-]?keys?|magic[\s_-]?values?)\b",
    re.IGNORECASE)

# The four additive frontmatter fields (KNOWN_FRONTMATTER_KEYS-declared in
# lint_facts — schema growth is declared, not silenced).
TEMPORAL_SCOPE_FIELD = "temporal_scope"
RUNTIME_TEMPORAL_SCOPE = "runtime"
REQUIRED_RUNTIME_FIELDS = (
    "temporal_scope", "subject_slot", "value_fingerprint", "captured_at",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# lint_facts' tolerant frontmatter parser (PyYAML-first, kv fallback) —
# reuse, never a third parser.
from lint_facts import parse_frontmatter  # noqa: E402


def fingerprint(value: str) -> str:
    """The ONLY sanctioned raw-value -> recordable-token bridge. Returns
    the sha256 hex digest; the raw value is never retained or returned."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _is_iso_ts(value: str) -> bool:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return False
    return True


def check_fact_postimage(text: str) -> list[str]:
    """The #341 scope-A judgment for one fact post-image. [] = allow.

    Violations are human-readable repair directives naming the missing
    field (the write_guard leg prefixes them runtime-fact[N] and fails the
    write closed). Out-of-scope facts (non-runtime source, or runtime
    source about a NON-volatile subject) return [] — the requirement is
    never extended by silence.
    """
    fm, _body, _err = parse_frontmatter(text)
    source = str(fm.get("source") or "").strip()
    if source not in RUNTIME_SOURCES:
        return []
    title = str(fm.get("title") or "")
    slot = str(fm.get("subject_slot") or "")
    if not (VOLATILE_SUBJECT_RE.search(title)
            or (slot and VOLATILE_SUBJECT_RE.search(slot))):
        return []

    violations: list[str] = []
    for field in REQUIRED_RUNTIME_FIELDS:
        if not str(fm.get(field) or "").strip():
            others = ", ".join(
                f for f in REQUIRED_RUNTIME_FIELDS
                if f != field and not str(fm.get(f) or "").strip())
            violations.append(
                f"runtime-source fact (`{source}`) about a volatile subject "
                f"missing required field `{field}` (#341: runtime values are "
                "not timeless truths; required set: "
                + ", ".join(REQUIRED_RUNTIME_FIELDS)
                + (f"; also missing: {others}" if others else "") + ")")

    scope = str(fm.get("temporal_scope") or "").strip()
    if scope and scope != RUNTIME_TEMPORAL_SCOPE:
        violations.append(
            f"`temporal_scope: {scope}` is not a runtime scope — a volatile "
            f"runtime observation must carry `{TEMPORAL_SCOPE_FIELD}: "
            f"{RUNTIME_TEMPORAL_SCOPE}`")
    fp = str(fm.get("value_fingerprint") or "").strip()
    if fp and not _SHA256_RE.match(fp):
        violations.append(
            "`value_fingerprint` must be a sha256 hex digest of the value "
            "(64 lowercase hex chars) — raw value material never enters the "
            "frontmatter, and a non-digest cannot join the rotation "
            "induction")
    captured = str(fm.get("captured_at") or "").strip()
    if captured and not _is_iso_ts(captured):
        violations.append(
            f"`captured_at: {captured}` is not an ISO-8601 timestamp — the "
            "rotation induction orders the fingerprint series by it")
    return violations
