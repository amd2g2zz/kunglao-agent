# -*- coding: utf-8 -*-
"""Issue #532 — write_guard PreToolUse hook on the four contract carriers.

RED contract (dev baseline, 2026-08-20): hooks/write_guard.py did not exist
and wire_up_settings registered 8 files, none of them on a Write/Edit
matcher. An agent Edit of facts/F001.md was completely ungated — the
external-user 2026-08-20 workspace dump reproduced 3 imitation facts + a
ghost claim cite through exactly this hole.

Fixture note: GOOD_FACT is the REAL #336 ICD-203 schema shape (type/title/
created/last_reviewed/provenance with content_sha256+credibility, extension
layer), not the plan-draft minimal shape — HEAD's lint_facts enforces the
full matrix, so a plan-era 7-key frontmatter would fail every allow test
for the wrong reason.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
WRITE_GUARD = HOOKS / "write_guard.py"

RC_ALLOW = 0
RC_BLOCK = 2


def _mk_ws(tmp_path: Path) -> Path:
    """A minimal but schema-legal workspace: register + facts/ + notes/."""
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: sample resolves imports dynamically\n",
        encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n", encoding="utf-8")
    return ws


def _payload(ws: Path, tool: str, file_path: Path, **tool_input) -> str:
    return json.dumps({
        "tool_name": tool,
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), **tool_input},
    }, ensure_ascii=False)


def _run_guard(ws: Path, payload: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60,
        env=env, errors="replace")


_SHA = "a" * 64  # placeholder provenance hash (shadow lint checks shape only)

GOOD_FACT = f"""---
id: F001-dynamic-imports
type: fact
title: Dynamic import resolution
status: INFERRED
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: C-001
claim: sample resolves imports dynamically
boundary_type: observation
promotion_gate: resolve the loader stub under dynamic-trace
source: static-decompile
confidence: medium
verify_status: partial
reproduce: python runs/verify-f001.py
expected: {_SHA}
verified: pending
provenance:
  - {{role: decompiled_c, path: evidence/f001.c, content_sha256: {_SHA}, credibility: B2}}
---

# F001 — Dynamic import resolution

## Status
INFERRED
"""


SELF_STAMPED_FACT = f"""---
id: F010-selfstamp
type: fact
title: Self-stamped verdict
status: PROVEN
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: C-001
claim: sample resolves imports dynamically
boundary_type: observation
promotion_gate: resolve the loader stub under dynamic-trace
source: static-decompile
confidence: high
verify_status: passes
reproduce: python runs/verify-f010.py
expected: {_SHA}
verified: 2026-08-20
verifier_sign_off:
  verifier_id: worker-alpha
  verdict: CONFIRMED
provenance:
  - {{role: decompiled_c, path: evidence/f010.c, content_sha256: {_SHA}, credibility: B2}}
---

# F010 — Self-stamped verdict

## Status
PROVEN
"""

NONSTANDARD_STATUS_FACT = f"""---
id: F011-invented
type: fact
title: Invented status word
status: VERIFIED-BY-EXTRACTION
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: C-001
claim: sample resolves imports dynamically
boundary_type: observation
promotion_gate: resolve the loader stub under dynamic-trace
source: static-decompile
confidence: high
verify_status: passes
reproduce: python runs/verify-f011.py
expected: {_SHA}
verified: 2026-08-20
provenance:
  - {{role: decompiled_c, path: evidence/f011.c, content_sha256: {_SHA}, credibility: B2}}
---

# F011 — Invented status word

## Status
VERIFIED-BY-EXTRACTION
"""


def _seed_producer(ws: Path, claim: str, worker: str) -> None:
    """Record `worker` as the PRODUCER of `claim` in the register, so a
    sign-off by the same id is self-verification (R1)."""
    ws.joinpath("claim-register.yaml").write_text(
        "claims:\n"
        f"  - id: {claim}\n"
        "    status: OPEN\n"
        "    statement: imports resolved at runtime\n"
        f"    worker_id: {worker}\n",
        encoding="utf-8")


# ---------- Task 1: carrier matcher + fail-closed skeleton ----------

def test_write_guard_module_exists():
    assert WRITE_GUARD.exists(), (
        "#532: hooks/write_guard.py is the mechanical trigger point for the "
        "three already-built write-side checkers; it does not exist yet")


def test_non_carrier_write_passes_through(tmp_path):
    """A write outside the four carriers is none of this hook's business."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(ws, "Write", ws / "scratch.txt", content="hi"))
    assert r.returncode == RC_ALLOW, f"non-carrier write blocked: {r.stderr}"


def test_carrier_write_with_clean_content_passes(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F001-dynamic-imports.md",
        content=GOOD_FACT))
    assert r.returncode == RC_ALLOW, (
        f"a schema-clean fact write must pass: {r.stdout}{r.stderr}")


def test_unresolvable_workspace_is_fail_closed(tmp_path):
    """No workspace markers but the path looks like a carrier -> BLOCK.

    fail-closed is the #532 posture: a write we cannot adjudicate is a write
    we do not allow (the pre-#532 default was 'no gate at all')."""
    orphan = tmp_path / "not-a-ws"
    (orphan / "facts").mkdir(parents=True)
    r = _run_guard(orphan, _payload(
        orphan, "Write", orphan / "facts" / "F001-x.md", content=GOOD_FACT))
    assert r.returncode == RC_BLOCK, (
        f"unadjudicable carrier write must fail closed: rc={r.returncode}")


def test_registry_carries_write_guard():
    sys.path.insert(0, str(ROOT / "scripts"))
    import wire_up_settings
    assert "write_guard.py" in wire_up_settings.WIRE_UP_HOOK_FILES, (
        "#532: write_guard must join THE hook registry so env_check / "
        "hooks_selfcheck / external_kicker all see it")


def test_subset_tables_absorb_the_registry_growth():
    """derive_hook_subset raises at import when a subset table drifts —
    importing both consumers is the assertion."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import external_kicker  # noqa: F401 — import IS the assertion
    import hooks_selfcheck  # noqa: F401


@pytest.mark.parametrize("carrier", [
    "facts/F001-dynamic-imports.md",
    "notes/N001-overview.md",
    "claim-register.yaml",
    "facts/_INDEX.md",
])
def test_all_four_carriers_are_matched(tmp_path, carrier):
    """The matcher must recognize all four contract carriers as in-scope."""
    ws = _mk_ws(tmp_path)
    sys.path.insert(0, str(ROOT / "hooks"))
    import write_guard
    assert write_guard.carrier_of(ws, ws / carrier) is not None, (
        f"{carrier} must be recognized as a contract carrier")


# ---------- Task 3: write_gate R1/R2 + W-2 wiring ----------

def test_r1_self_stamped_proven_is_blocked(tmp_path):
    """verifier == producer: the self-stamping shape the 2026-08-20 dump used."""
    ws = _mk_ws(tmp_path)
    _seed_producer(ws, "C-001", "worker-alpha")
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F010-selfstamp.md",
        content=SELF_STAMPED_FACT))
    assert r.returncode == RC_BLOCK, (
        f"R1 must block verifier==producer PROVEN: rc={r.returncode} "
        f"{r.stdout}{r.stderr}")
    assert "R1" in r.stderr or "self" in r.stderr.lower(), r.stderr


def test_w2_nonstandard_status_is_treated_as_stamp(tmp_path):
    """W-2: an invented status carrying verified/proven semantics must not
    slip past the PROVEN gate by simply not spelling PROVEN."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F011-invented.md",
        content=NONSTANDARD_STATUS_FACT))
    assert r.returncode == RC_BLOCK, (
        f"W-2: VERIFIED-BY-EXTRACTION must be adjudicated as a STAMP and "
        f"blocked: rc={r.returncode} {r.stdout}{r.stderr}")


def test_stamp_semantics_helper_is_exposed():
    sys.path.insert(0, str(ROOT / "scripts"))
    import write_gate
    assert write_gate.is_verified_semantics("VERIFIED-BY-EXTRACTION")
    assert write_gate.is_verified_semantics("proven-by-hand")
    assert not write_gate.is_verified_semantics("OPEN")
    assert not write_gate.is_verified_semantics("INFERRED")


def test_edit_post_image_is_adjudicated(tmp_path):
    """The Edit face: the post-image (old->new applied) is what gets judged,
    not the current on-disk text."""
    ws = _mk_ws(tmp_path)
    target = ws / "facts" / "F001-dynamic-imports.md"
    target.write_text(GOOD_FACT, encoding="utf-8")
    r = _run_guard(ws, _payload(
        ws, "Edit", target,
        old_string="status: INFERRED", new_string="status: PROVEN"))
    assert r.returncode == RC_BLOCK, (
        f"an Edit promoting to PROVEN with no verifier evidence must block: "
        f"rc={r.returncode} {r.stderr}")


# ---------- Task 5: every rejection emits into kunglao_log ----------

def _events(ws: Path) -> list[dict]:
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    out = []
    for p in logs:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def test_write_block_emits_a_kunglao_log_event(tmp_path):
    """An enforcement action that leaves no trace is not observable (E-1/E-2)."""
    ws = _mk_ws(tmp_path)
    _seed_producer(ws, "C-001", "worker-alpha")
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F010-selfstamp.md",
        content=SELF_STAMPED_FACT))
    assert r.returncode == RC_BLOCK
    evs = [e for e in _events(ws) if e["action"] == "write_blocked"]
    assert evs, f"no write_blocked event in runs/logs/: {_events(ws)}"
    e = evs[0]
    assert e["actor"] == "hook"
    assert e["tool"] == "Write"
    assert e["exit"] == RC_BLOCK
    assert "F010-selfstamp.md" in str(e["artifact"])
    assert e["detail"], "the rejection reason must be in the event detail"


def test_allowed_write_emits_nothing(tmp_path):
    """The log is a signal, not a firehose — clean writes stay silent."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F001-dynamic-imports.md",
        content=GOOD_FACT))
    assert r.returncode == RC_ALLOW, r.stderr
    assert [e for e in _events(ws) if e["action"] == "write_blocked"] == []


def test_write_blocked_is_in_the_controlled_vocabulary():
    sys.path.insert(0, str(ROOT / "scripts"))
    import event_taxonomy
    assert "write_blocked" in event_taxonomy.EMIT_ACTIONS, (
        "#459 contract: every emit action word must be registered in "
        "EMIT_ACTIONS or tests/test_event_stream_adoption.py turns red")
