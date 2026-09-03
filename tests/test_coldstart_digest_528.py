# -*- coding: utf-8 -*-
"""tests/test_coldstart_digest_528.py — digest as the 9th cold-start file
(#528) + hypotheses carrier handoff from #538.

Work items covered:
  - cold-start-contract.md names runs/digest.md as file 9 (read via the
    kunglao_resume read-only face — resume never writes, so the digest a
    fresh session reads is a computed artifact, and a build failure
    degrades to 8 files, never blocks).
  - the digest's open-hypotheses section is the only hypothesis
    re-hydration surface at cold start.
  - #538's hypotheses/ README stub said "#528 owns the real writer" —
    with #528 landing, the stub text now names the real writer
    (hypothesis_store) and the state machine, not a future issue.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

COLD_START = REPO / "references" / "cold-start-contract.md"
MANIFEST = REPO / "docs" / "workspace-manifest.md"


def _load_init():
    name = "kunglao_init_528"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- 1. cold-start contract: digest is the 9th file ----------

def test_cold_start_names_nine_files() -> None:
    text = COLD_START.read_text(encoding="utf-8")
    assert "9 files" in text or "nine files" in text, (
        "cold-start-contract.md must move from the 8-file read to 9 "
        "with runs/digest.md as file 9 (#528)")


def test_cold_start_digest_is_ninth() -> None:
    text = COLD_START.read_text(encoding="utf-8")
    assert "runs/digest.md" in text
    # and it must say WHY: open hypotheses re-hydrate through it
    assert "hypothes" in text


def test_cold_start_digest_read_via_resume_face() -> None:
    """The doc must name the read-only face: digest is computed/read, the
    cold-start session never writes it (resume #466 read-only contract)."""
    text = COLD_START.read_text(encoding="utf-8")
    assert "resume" in text or "read-only" in text or "read only" in text


# ---------- 2. hypotheses/ stub text (the #538 -> #528 handoff) ----------

def test_hypotheses_stub_names_the_real_writer() -> None:
    """#538 shipped '#528 owns the real writer' placeholder language — with
    #528 landing, the stub names hypothesis_store + the state machine."""
    mod = _load_init()
    stub = mod.CARRIER_READMES["hypotheses"]
    assert "hypothesis_store" in stub, (
        "hypotheses/ stub must name scripts/hypothesis_store.py (#528 "
        "landed — the 'future writer' language is stale)")
    assert "superseded" in stub  # the state machine is named


def test_hypotheses_stub_no_future_writer_language() -> None:
    mod = _load_init()
    stub = mod.CARRIER_READMES["hypotheses"]
    assert "stub" not in stub.lower(), (
        "the hypotheses/ README still calls itself a stub — #528 has landed")
    assert "随 #528" not in stub


def test_notes_stub_names_supersedes_chain() -> None:
    """The notes/ stub (also #538's) already names the supersedes chain —
    pin it so the two layers stay cross-referenced."""
    mod = _load_init()
    stub = mod.CARRIER_READMES["notes"]
    assert "supersedes" in stub
    assert "hypotheses" in stub  # and points at the hypothesis layer


# ---------- 3. workspace manifest row updated ----------

def test_manifest_hypotheses_row_names_writers() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert "hypothesis_store" in text
    assert "sec_g" in text or "digest" in text


def test_manifest_no_stub_only_language() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert "stub only" not in text, (
        "workspace-manifest.md still says hypotheses/ is 'stub only' — "
        "#528 landed its writer")


# ---------- 4. anti-orphan: named consumers documented ----------

def test_scripts_readme_lists_new_modules() -> None:
    """Anti-orphan rule: every new module has a named consumer row."""
    text = (REPO / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "hypothesis_store.py" in text
    assert "notes_writer.py" in text


def test_new_modules_have_importers() -> None:
    """The dead-code rule: both new modules are imported by real (non-test)
    code — hypothesis_store by digest_build + state_anchor, notes_writer
    documented as the write-side contract."""
    import digest_build  # noqa: F401
    import state_anchor  # noqa: F401
    src = (REPO / "scripts" / "digest_build.py").read_text(encoding="utf-8")
    assert "hypothesis_store" in src
    src = (REPO / "hooks" / "state_anchor.py").read_text(encoding="utf-8")
    assert "hypothesis_store" in src
