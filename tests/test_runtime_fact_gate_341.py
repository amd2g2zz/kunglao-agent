# -*- coding: utf-8 -*-
"""Issue #341 — runtime-state fact frontmatter + write-side enforcement (A).

Failure class: runtime-derived values (keys/tokens/sessions/nonces/cookies)
are recorded as timeless truths — the fact schema has no temporal scope, so
F(K1 decrypts) and F(K2 decrypts) are individually true, non-contradictory
facts and the rotation induction never fires (issue #341 F1/F2).

Contract under test (scripts/runtime_facts.py, write-side leg in
hooks/write_guard.py adjudicate):

- a fact whose source is a runtime-observation source (the worker-doc
  vocabulary `dynamic_re`/`mixed` AND lint_facts' dynamic enum
  `dynamic-trace`/`frida-capture`/`qiling-emu`) about a VOLATILE subject
  (key/token/session/nonce/cookie — small pattern set) MUST carry
  temporal_scope: runtime, subject_slot, value_fingerprint (sha256 hex),
  captured_at (ISO ts); missing any -> violation (write_guard REJECT rc=2);
- static-source facts NEVER require the runtime fields (scope pinned);
- lint_facts.KNOWN_FRONTMATTER_KEYS admits the four additive fields (L-3
  warns on unknown keys — schema growth must be declared, not silenced).

Fixture note: facts mirror the REAL #336 ICD-203 shape (same GOOD_FACT
convention as tests/test_write_guard_532.py) so allow-paths pass every
pre-existing leg for the right reason.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))

import lint_facts  # noqa: E402
from runtime_facts import (  # noqa: E402
    REQUIRED_RUNTIME_FIELDS,
    RUNTIME_SOURCES,
    VOLATILE_SUBJECT_RE,
    check_fact_postimage,
    fingerprint,
)

RC_ALLOW = 0
RC_BLOCK = 2

_SHA = "a" * 64
_FP1 = "b" * 64
_FP2 = "c" * 64
_RAW_KEY = "supersecretkeymaterial-0011223344556677"


def _mk_ws(tmp_path: Path) -> Path:
    """Minimal but schema-legal workspace (register + facts/ + notes/ + runs/)."""
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: sample decrypts the config blob\n",
        encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n", encoding="utf-8")
    return ws


def _fact(source: str = "dynamic-trace",
          title: str = "Config decrypt AES key recovered",
          runtime: dict | None = None,
          fid: str = "F001-config-decrypt-key") -> str:
    """A schema-legal fact. `runtime` overrides the four runtime fields;
    a None value OMITS that field (e.g. runtime={"captured_at": None}).
    runtime=None (default) = all four present (compliant)."""
    overrides = {
        "temporal_scope": "runtime",
        "subject_slot": "config-decrypt-key",
        "value_fingerprint": _FP1,
        "captured_at": "2026-09-22T10:00:00Z",
    }
    overrides.update(runtime or {})
    fields = {k: v for k, v in overrides.items() if v is not None}
    lines = [
        "---",
        f"id: {fid}",
        "type: fact",
        f"title: {title}",
        "status: INFERRED",
        "created: 2026-09-22",
        "last_reviewed: 2026-09-22",
        "claim_id: C-001",
        "claim: sample decrypts the config blob",
        "boundary_type: observation",
        "promotion_gate: characterize the key derivation point under a debugger",
        f"source: {source}",
        "confidence: medium",
        "verify_status: pending",
        *[
            f"{k}: {v}" for k, v in fields.items() if v is not None
        ],
        "verified: pending",
        "provenance:",
        "  - {role: capture_log, path: runs/frida-001.log, "
        "content_sha256: " + _SHA + ", credibility: B2}",
        "reproduce: |",
        "  frida -l hook_derive.js -- attach and dump key buffer",
        "expected: |",
        "  key buffer dump matches the derivation-point breakpoint",
        "---",
        "",
        "## Code excerpt",
        "",
        "```c",
        "BCryptDeriveKey(hSecret, BCRYPT_KDF_HASH, ...)",
        "```",
        "",
        "## Status",
        "",
        "INFERRED",
        "",
    ]
    return "\n".join(lines)


# =====================================================================
# volatile-subject pattern set (small, tested)
# =====================================================================

@pytest.mark.parametrize("word", [
    "key", "AES key", "session token", "auth token", "session id",
    "nonce", "cookie", "API key", "api-key", "credentials",
])
def test_volatile_pattern_hits_subject_words(word):
    assert VOLATILE_SUBJECT_RE.search(f"Config decrypt {word} recovered")


@pytest.mark.parametrize("title", [
    "Import table resolves dynamically",
    "Config blob is AES-256-CBC encrypted",
    "Main window class name observed",
])
def test_volatile_pattern_ignores_non_subject_titles(title):
    assert not VOLATILE_SUBJECT_RE.search(title)


def test_fingerprint_is_sha256_hex_of_value():
    fp = fingerprint(_RAW_KEY)
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)


# =====================================================================
# gate scope: who is required to carry the four fields
# =====================================================================

def test_static_source_fact_never_requires_runtime_fields():
    """Acceptance: static-source facts never require runtime fields."""
    text = _fact(source="static-decompile")
    assert check_fact_postimage(text) == []


def test_runtime_source_enum_covers_both_vocabularies():
    """The worker doc vocabulary (`dynamic_re`/`mixed`, agents/kunglao-worker.md
    fact schema) AND the lint enum's runtime-observation sources both arm the
    gate; static sources never do."""
    assert {"dynamic_re", "mixed"} <= set(RUNTIME_SOURCES)
    assert {"dynamic-trace", "frida-capture", "qiling-emu"} <= set(RUNTIME_SOURCES)
    assert not ({"static-decompile", "public-osint", "inference",
                 "analyst-judgment", "vt-pivot"} & set(RUNTIME_SOURCES))


def test_non_volatile_dynamic_fact_is_exempt():
    """Dynamic evidence about a NON-volatile subject stays ungated — the
    requirement is scoped to volatile subjects, not to all dynamic facts."""
    text = _fact(title="Decryption happens via BCryptDecrypt call")
    assert check_fact_postimage(text) == []


def test_volatile_dynamic_fact_missing_all_four_fields():
    text = _fact(runtime=dict.fromkeys(REQUIRED_RUNTIME_FIELDS))
    msgs = check_fact_postimage(text)
    for field in REQUIRED_RUNTIME_FIELDS:
        assert any(field in m for m in msgs), (field, msgs)


@pytest.mark.parametrize("missing", [
    "temporal_scope", "subject_slot", "value_fingerprint", "captured_at",
])
def test_each_missing_field_is_named_individually(missing):
    msgs = check_fact_postimage(_fact(runtime={missing: None}))
    assert len(msgs) == 1, msgs
    assert missing in msgs[0]


def test_compliant_runtime_fact_passes_clean():
    text = _fact(source="dynamic_re", runtime={})
    assert check_fact_postimage(text) == []


def test_mixed_source_arms_the_gate():
    text = _fact(source="mixed",
                 runtime=dict.fromkeys(REQUIRED_RUNTIME_FIELDS))
    msgs = check_fact_postimage(text)
    assert len(msgs) == len(REQUIRED_RUNTIME_FIELDS)


# =====================================================================
# field VALUE validation (present-but-wrong is a violation, not a pass)
# =====================================================================

def test_non_runtime_temporal_scope_value_rejected():
    msgs = check_fact_postimage(_fact(runtime={"temporal_scope": "static"}))
    assert any("temporal_scope" in m and "runtime" in m for m in msgs)


def test_non_sha256_fingerprint_rejected():
    msgs = check_fact_postimage(
        _fact(runtime={"value_fingerprint": "deadbeef"}))
    assert any("value_fingerprint" in m for m in msgs)


def test_unparseable_captured_at_rejected():
    msgs = check_fact_postimage(
        _fact(runtime={"captured_at": "sometime yesterday"}))
    assert any("captured_at" in m for m in msgs)


def test_slot_carrying_volatile_word_arms_gate_even_with_plain_title():
    """subject_slot names the stable slot — a volatile slot id with a plain
    title is still a volatile-subject fact."""
    text = _fact(title="Credential buffer captured",
                 runtime={"subject_slot": "license-nonce"})
    assert check_fact_postimage(text) == []  # all four present -> clean
    msgs = check_fact_postimage(
        _fact(title="Credential buffer captured", runtime={
            "subject_slot": "license-nonce", "temporal_scope": None,
            "value_fingerprint": None, "captured_at": None}))
    assert len(msgs) == 3


# =====================================================================
# lint_facts L-3: the four fields are DECLARED schema (no unknown-key warn)
# =====================================================================

@pytest.mark.parametrize("field", [
    "temporal_scope", "subject_slot", "value_fingerprint", "captured_at",
])
def test_known_frontmatter_keys_declare_runtime_fields(field):
    assert field in lint_facts.KNOWN_FRONTMATTER_KEYS


def test_runtime_fact_produces_no_unknown_key_warning(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-config-decrypt-key.md").write_text(
        _fact(source="dynamic-trace"), encoding="utf-8")
    errors, warnings = lint_facts.lint_workspace(ws)
    mine_e = [e for e in errors
              if e[2].split(":", 1)[0] == "F001-config-decrypt-key.md"]
    mine_w = [w for w in warnings
              if str(w[2]).split(":", 1)[0] == "F001-config-decrypt-key.md"]
    assert not mine_e, mine_e
    assert not any("unknown" in str(m).lower() for _s, _c, m in mine_w), mine_w


# =====================================================================
# write_guard end-to-end: the write-side REJECT actually fires
# =====================================================================

def _run_guard(ws: Path, payload: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    return subprocess.run(
        [sys.executable, str(HOOKS / "write_guard.py")],
        input=payload, capture_output=True, text=True, timeout=120,
        env=env, errors="replace")


def _write_payload(ws: Path, rel: str, content: str) -> str:
    return json.dumps({
        "tool_name": "Write",
        "cwd": str(ws),
        "tool_input": {"file_path": str(ws / rel), "content": content},
    }, ensure_ascii=False)


def test_write_guard_rejects_volatile_runtime_fact_missing_fields(tmp_path):
    ws = _mk_ws(tmp_path)
    proc = _run_guard(ws, _write_payload(
        ws, "facts/F001-config-decrypt-key.md", _fact(runtime=dict.fromkeys(REQUIRED_RUNTIME_FIELDS))))
    assert proc.returncode == RC_BLOCK, proc.stderr
    assert "runtime-fact" in proc.stderr


def test_write_guard_allows_compliant_runtime_fact(tmp_path):
    ws = _mk_ws(tmp_path)
    # lint-legal runtime-observation source: `dynamic_re` (the worker-doc
    # vocabulary) is blocked upstream by lint_facts BAD_SOURCE_ENUM today —
    # the compliant allow-path is proven on the enum's dynamic face.
    proc = _run_guard(ws, _write_payload(
        ws, "facts/F001-config-decrypt-key.md", _fact(source="dynamic-trace")))
    assert proc.returncode == RC_ALLOW, proc.stderr


def test_write_guard_allows_static_fact_without_runtime_fields(tmp_path):
    ws = _mk_ws(tmp_path)
    proc = _run_guard(ws, _write_payload(
        ws, "facts/F002-import-table.md",
        _fact(source="static-decompile",
              title="Import table resolves dynamically",
              fid="F002-import-table")))
    assert proc.returncode == RC_ALLOW, proc.stderr


def test_write_guard_runtime_fact_violations_are_never_waived(tmp_path):
    """The runtime-fact leg is stamp-class: an active write-guard waiver
    (runs/write-guard-waivers.yaml) waives lint[] violations only — a
    missing runtime field still blocks."""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "write-guard-waivers.yaml").write_text(
        "F001-config-decrypt-key.md:\n"
        "  reason: migration-mode rewrite\n", encoding="utf-8")
    proc = _run_guard(ws, _write_payload(
        ws, "facts/F001-config-decrypt-key.md", _fact(runtime=dict.fromkeys(REQUIRED_RUNTIME_FIELDS))))
    assert proc.returncode == RC_BLOCK, proc.stderr
    assert "runtime-fact" in proc.stderr
