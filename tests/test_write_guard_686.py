# -*- coding: utf-8 -*-
"""Issue #686 — write_guard must-block payloads rc contract (RED).

Symptom under investigation: 7 must-block payload shapes returned rc=0 with
EMPTY stdout/stderr on Windows hosts (locale cp936) — the hook silently
allowed writes it must block. Root cause (measured 2026-08-25, see
openspec/changes/issue-686-write-guard-adjudicate/design.md D1): the payloads
carry a non-ASCII em-dash; the test parent encodes stdin with the host locale
(GBK) while the child decodes with PYTHONIOENCODING=utf-8, so
_read_payload()'s sys.stdin.read() raised UnicodeDecodeError, the bare
except swallowed it into {}, and main() returned RC_ALLOW before any carrier
was resolved.

Contract pinned here (one parameterized case per issue-listed failure):
every must-block shape MUST return rc=2 end-to-end through the REAL
subprocess — no mocks. The em-dashes in the payload literals are
load-bearing: they are the trigger class of the #686 regression; stripping
them would turn this suite into an ASCII-only false pass.

Allow guards (clean em-dash fact write, non-carrier write) pin the other
side of the contract so a degenerate always-block "fix" cannot go green.
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

_SHA = "a" * 64  # placeholder provenance hash (shadow lint checks shape only)


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


def _seed_producer(ws: Path, claim: str, worker: str) -> None:
    """Record `worker` as the PRODUCER of `claim` so a same-id sign-off is R1."""
    ws.joinpath("claim-register.yaml").write_text(
        "claims:\n"
        f"  - id: {claim}\n"
        "    status: OPEN\n"
        "    statement: imports resolved at runtime\n"
        f"    worker_id: {worker}\n",
        encoding="utf-8")


def _payload(ws: Path, tool: str, file_path: Path, **tool_input) -> str:
    return json.dumps({
        "tool_name": tool,
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), **tool_input},
    }, ensure_ascii=False)


def _run_guard(ws: Path, payload: str,
               extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """The #532 harness shape: real child python, stdin JSON, UTF-8 child IO."""
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60,
        env=env, errors="replace")


# ---------- payload literals (em-dashes are the #686 trigger class) ----------

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

STAMPED_PRIOR = """---
id: N-001
claim_id: C-001
status: PROVEN
verify_status: passes
---

# N-001 — cipher verdict

The cipher is AES.
"""

CORRECTION_NO_CHAIN = """---
id: N-002
claim_id: C-001
status: PROVEN
verify_status: passes
---

# N-002 — corrected verdict

Actually the cipher is ChaCha20.
"""

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


# ---------- the 7 must-block shapes (one per issue-listed failure) ----------

def _events(ws: Path) -> list[dict]:
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    out = []
    for p in logs:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _build_r1(tmp_path: Path) -> tuple[Path, str]:
    ws = _mk_ws(tmp_path)
    _seed_producer(ws, "C-001", "worker-alpha")
    return ws, _payload(
        ws, "Write", ws / "facts" / "F010-selfstamp.md",
        content=SELF_STAMPED_FACT)


def _build_w2(tmp_path: Path) -> tuple[Path, str]:
    ws = _mk_ws(tmp_path)
    return ws, _payload(
        ws, "Write", ws / "facts" / "F011-invented.md",
        content=NONSTANDARD_STATUS_FACT)


def _build_orphan(tmp_path: Path) -> tuple[Path, str]:
    orphan = tmp_path / "not-a-ws"
    (orphan / "facts").mkdir(parents=True)
    return orphan, _payload(
        orphan, "Write", orphan / "facts" / "F001-x.md", content=GOOD_FACT)


def _build_chainless(tmp_path: Path) -> tuple[Path, str]:
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    return ws, _payload(ws, "Write", ws / "notes" / "N-002.md",
                        content=CORRECTION_NO_CHAIN)


def _build_inherited(tmp_path: Path) -> tuple[Path, str]:
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    chained_stamped = CORRECTION_WITH_CHAIN_PENDING.replace(
        "verify_status: pending", "verify_status: passes").replace(
        "status: note", "status: PROVEN")
    return ws, _payload(ws, "Write", ws / "notes" / "N-002.md",
                        content=chained_stamped)


def _build_fake_chain(tmp_path: Path) -> tuple[Path, str]:
    ws = _mk_ws(tmp_path)
    (ws / "notes" / "N-001.md").write_text(STAMPED_PRIOR, encoding="utf-8")
    fake = CORRECTION_WITH_CHAIN_PENDING.replace(
        "supersedes: N-001", "supersedes: N-999")
    return ws, _payload(ws, "Write", ws / "notes" / "N-002.md", content=fake)


def _check_r1_reason(r: subprocess.CompletedProcess, ws: Path) -> None:
    assert "R1" in r.stderr or "self" in r.stderr.lower(), r.stderr


def _check_fake_chain_reason(r: subprocess.CompletedProcess, ws: Path) -> None:
    assert "N-999" in r.stderr, r.stderr


def _check_block_logged(r: subprocess.CompletedProcess, ws: Path) -> None:
    evs = [e for e in _events(ws) if e["action"] == "write_blocked"]
    assert evs, f"no write_blocked event in runs/logs/: {_events(ws)}"
    e = evs[0]
    assert e["actor"] == "hook"
    assert e["tool"] == "Write"
    assert e["exit"] == RC_BLOCK
    assert "F010-selfstamp.md" in str(e["artifact"])
    assert e["detail"], "the rejection reason must be in the event detail"


_MUST_BLOCK = [
    pytest.param(_build_r1, _check_r1_reason, id="r1-self-stamped-proven"),
    pytest.param(_build_w2, None, id="w2-nonstandard-status"),
    pytest.param(_build_orphan, None, id="unresolvable-workspace-fail-closed"),
    pytest.param(_build_r1, _check_block_logged,
                id="block-emits-kunglao_log-event"),
    pytest.param(_build_chainless, None, id="chainless-correction"),
    pytest.param(_build_inherited, None, id="chained-inherited-passes"),
    pytest.param(_build_fake_chain, _check_fake_chain_reason,
                id="fake-chain-target-missing"),
]


@pytest.mark.parametrize("build,extra", _MUST_BLOCK)
def test_must_block_payload_returns_rc_block(tmp_path, build, extra) -> None:
    """Every issue-listed must-block shape: rc=2, end-to-end, no mocks.

    RED note: on a cp936 host at the dev baseline these return rc=0 with
    empty stderr — the silent-allow regression this file pins."""
    ws, payload = build(tmp_path)
    r = _run_guard(ws, payload)
    assert r.returncode == RC_BLOCK, (
        f"must-block write allowed: rc={r.returncode} "
        f"stdout={r.stdout!r} stderr={r.stderr!r}")
    assert r.stderr, "a block must carry its reason on stderr"
    if extra is not None:
        extra(r, ws)


# ---------- allow guards: the fix must not over-block ----------

def test_clean_emdash_fact_write_still_allows(tmp_path) -> None:
    """Schema-clean fact write (em-dash payload — the recovered decode path)
    must stay allowed: the fix restores adjudication, not a blanket block."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(
        ws, "Write", ws / "facts" / "F001-dynamic-imports.md",
        content=GOOD_FACT))
    assert r.returncode == RC_ALLOW, (
        f"clean fact write blocked: rc={r.returncode} {r.stdout}{r.stderr}")


def test_non_carrier_write_still_allows(tmp_path) -> None:
    """A write outside the four carriers is none of this hook's business."""
    ws = _mk_ws(tmp_path)
    r = _run_guard(ws, _payload(ws, "Write", ws / "scratch.txt",
                                content="hi — plain scratch note"))
    assert r.returncode == RC_ALLOW, (
        f"non-carrier write blocked: rc={r.returncode} {r.stderr}")


# ---------- debug trace channel (spec: KUNGLAO_WG_DEBUG=1) ----------

def test_debug_env_exposes_decision_trace(tmp_path) -> None:
    """KUNGLAO_WG_DEBUG=1 must surface the decision flow on stderr so the
    next enforcement failure is localizable without an out-of-tree driver."""
    ws, payload = _build_r1(tmp_path)
    r = _run_guard(ws, payload, extra_env={"KUNGLAO_WG_DEBUG": "1"})
    assert "wg-debug:" in r.stderr, (
        f"debug trace missing on stderr: {r.stderr!r}")
