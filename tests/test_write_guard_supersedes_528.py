# -*- coding: utf-8 -*-
"""tests/test_write_guard_supersedes_528.py — the supersedes-chain check
wired into the write_guard note leg (#528 work item 4).

The AES->ChaCha20 anti-pattern: an agent corrects a conclusion by simply
overwriting the note (or writing a sibling note) with no trace of the
prior. notes_writer enforces the chain at its own API; this suite proves
the PreToolUse write face (#532 write_guard) CALLS it, so the rule has a
mechanical caller, not just a library.

Note shape here is the minimal notes frontmatter the convergence note
layer reads (claim_id + verify_status) — lint_facts' FACT matrix does not
apply to notes; write_gate R1 applies only to verify_status=passes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
WRITE_GUARD = HOOKS / "write_guard.py"

RC_ALLOW = 0
RC_BLOCK = 2


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n"
        "    statement: cipher selection\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n",
                                           encoding="utf-8")
    return ws


def _run_guard(ws: Path, payload: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60, env=env,
        errors="replace")


def _payload(ws: Path, file_path: Path, content: str) -> str:
    return json.dumps({
        "tool_name": "Write",
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), "content": content},
    }, ensure_ascii=False)


STAMPED_PRIOR = """---
id: N-001
claim_id: C-001
status: PROVEN
verify_status: passes
---

# N-001 — cipher verdict

The cipher is AES.
"""

# The correction WITHOUT a supersedes pointer — the anti-pattern shape.
CORRECTION_NO_CHAIN = """---
id: N-002
claim_id: C-001
status: PROVEN
verify_status: passes
---

# N-002 — corrected verdict

Actually the cipher is ChaCha20.
"""

# The correction WITH the chain (still blocked for verify_status=passes
# without independent verification by R1 — so the ALLOW shape is the
# pending one).
CORRECTION_WITH_CHAIN_PENDING = """---
id: N-002
claim_id: C-001
status: note
verify_status: pending
supersedes: N-001
---

# N-002 — corrected verdict

Actually the cipher is ChaCha20.
"""


def test_correction_without_supersedes_is_blocked(tmp_path: Path) -> None:
    """Same-claim stamped prior exists; new note carries no supersedes
    pointer -> BLOCK with the chain rule named."""
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    r = _run_guard(ws, _payload(
        ws, ws / "notes" / "N-002.md", CORRECTION_NO_CHAIN))
    assert r.returncode == RC_BLOCK, (
        f"a chainless same-claim correction must be blocked: "
        f"rc={r.returncode} {r.stdout}{r.stderr}")
    assert "supersedes" in r.stderr or "SUPERSEDE" in r.stderr


def test_correction_with_chain_pending_passes(tmp_path: Path) -> None:
    """The traceable shape — supersedes pointer + verify_status reset to
    pending — is allowed through (the correction still needs an
    independent verifier to stamp; that is #236 R1's job at stamp time)."""
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    r = _run_guard(ws, _payload(
        ws, ws / "notes" / "N-002.md", CORRECTION_WITH_CHAIN_PENDING))
    assert r.returncode == RC_ALLOW, (
        f"a chained pending correction must pass: rc={r.returncode} "
        f"{r.stdout}{r.stderr}")


def test_first_note_no_prior_passes(tmp_path: Path) -> None:
    """No stamped prior -> ordinary note writes are untouched (#528 adds
    the chain rule ONLY to the correction shape)."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(
        ws, ws / "notes" / "N-100.md", CORRECTION_WITH_CHAIN_PENDING.replace(
            "supersedes: N-001\n", "").replace("N-002", "N-100")))
    assert r.returncode == RC_ALLOW, r.stderr


def test_chained_correction_with_inherited_passes_still_blocked(
        tmp_path: Path) -> None:
    """supersedes present BUT verify_status=passes inherited — the reset
    rule: a correction never inherits verification. Blocked (by R1 and/or
    the reset rule — the observable contract is the block + the reason)."""
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    chained_stamped = CORRECTION_WITH_CHAIN_PENDING.replace(
        "verify_status: pending", "verify_status: passes").replace(
        "status: note", "status: PROVEN")
    r = _run_guard(ws, _payload(
        ws, ws / "notes" / "N-002.md", chained_stamped))
    assert r.returncode == RC_BLOCK, (
        f"a correction must not inherit verification: rc={r.returncode}")


def test_supersedes_target_must_exist(tmp_path: Path) -> None:
    """A supersedes pointer at a nonexistent note is a fake chain — the
    write is blocked (traceability without an actual prior is theater)."""
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    fake = CORRECTION_WITH_CHAIN_PENDING.replace(
        "supersedes: N-001", "supersedes: N-999")
    r = _run_guard(ws, _payload(ws, ws / "notes" / "N-002.md", fake))
    assert r.returncode == RC_BLOCK
    assert "N-999" in r.stderr
