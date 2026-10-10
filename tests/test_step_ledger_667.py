# -*- coding: utf-8 -*-
"""tests/test_step_ledger_667.py — the shadow experience substrate.

The card's acceptance, pinned: hash-only rows (raw content physically
cannot reach the ledger), fail-open recording, the escrow lifecycle
(confirm requires certification / revoke targets the producing step's
evidence / expiry ages pending out), the farming scenario netting zero
CONFIRMED credit, replay byte-identity, and the shadow hook writing
nothing but its own ledger.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import step_ledger as sl  # noqa: E402

TS = "2026-10-11T00:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _step(ws: Path, tool: str = "Bash", session: str = "s1") -> dict:
    row = sl.build_step_row(
        session_id=session, tool=tool,
        tool_input={"command": "uv run python target/derive.py"},
        tool_response={"stdout": "SECRET-OUTPUT-TEXT"},
        reads=["facts/F001.md"], writes=["runs/out.txt"],
        duration_ms=1200, ts=TS)
    assert sl.record_step(ws, row) is not None
    return row


# ------------------------------------------------- hash-only rows ----

def test_step_row_is_hash_only(tmp_path) -> None:
    ws = _ws(tmp_path)
    _step(ws)
    text = (ws / "runs" / "step-ledger.jsonl").read_text("utf-8")
    assert "SECRET-OUTPUT-TEXT" not in text
    assert "uv run python" not in text
    row = json.loads(text.splitlines()[0])
    assert row["schema"] == "step-record/1"
    assert len(row["input_sha"]) == 64 and len(row["output_sha"]) == 64
    assert row["duration_ms"] == 1200.0
    assert len(row["call_id"]) == 16


def test_record_step_refuses_smuggled_content(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = sl.build_step_row(session_id="s", tool="Read",
                            tool_input={}, tool_response={},
                            ts=TS)
    row["raw_output"] = "SECRET"
    sl.record_step(ws, row)
    text = (ws / "runs" / "step-ledger.jsonl").read_text("utf-8")
    assert "SECRET" not in text


def test_recording_is_fail_open(tmp_path) -> None:
    ws = tmp_path / "bare"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs").chmod(0o500)      # unwritable ledger dir
    try:
        row = sl.build_step_row(session_id="s", tool="Bash",
                                tool_input={}, tool_response={}, ts=TS)
        assert sl.record_step(ws, row) is None   # None, never a raise
    finally:
        (ws / "runs").chmod(0o700)


# ------------------------------------------------- the lifecycle ----

def _item(ws: Path, *, certified: bool, step: str = "call-1",
          kind: str = "confirm") -> dict:
    row = sl.record_evidence(ws, step_ref=step, claim_ref="C-005",
                             kind=kind, artifact={"out": "x"},
                             certified=certified, ts=TS)
    assert row is not None
    return row


def test_escrow_then_confirm_on_certified_item(tmp_path) -> None:
    ws = _ws(tmp_path)
    item = _item(ws, certified=True)
    assert sl.amend(ws, evidence_id=item["id"], verb="escrow",
                    ts=TS) is not None
    assert sl.amend(ws, evidence_id=item["id"], verb="confirm",
                    amount=0.5, ts=TS) is not None
    actions = [a["action"] for a in sl.read_amendments(ws)]
    assert actions == ["escrow", "confirm"]


def test_uncertified_evidence_never_confirms(tmp_path) -> None:
    """The farming scenario: uncertified evidence escrows and can only
    expire — zero CONFIRMED credit by construction."""
    ws = _ws(tmp_path)
    item = _item(ws, certified=False)
    assert sl.amend(ws, evidence_id=item["id"], verb="escrow",
                    ts=TS) is not None
    assert sl.amend(ws, evidence_id=item["id"], verb="confirm",
                    ts=TS) is None
    actions = [a["action"] for a in sl.read_amendments(ws)]
    assert actions == ["escrow"], "no CONFIRMED credit for the farm"


def test_revoke_resolves_and_blocks_second_confirm(tmp_path) -> None:
    ws = _ws(tmp_path)
    item = _item(ws, certified=True, kind="refute")
    assert sl.amend(ws, evidence_id=item["id"], verb="escrow",
                    ts=TS) is not None
    assert sl.amend(ws, evidence_id=item["id"], verb="revoke",
                    reason="the producing step was refuted",
                    ts=TS) is not None
    assert sl.amend(ws, evidence_id=item["id"], verb="confirm",
                    ts=TS) is None, "a revoked item stays resolved"
    assert sl.amend(ws, evidence_id=item["id"], verb="escrow",
                    ts=TS) is None


def test_expire_pending_ages_items_out(tmp_path) -> None:
    ws = _ws(tmp_path)
    old = (datetime.now(timezone.utc)
           - timedelta(hours=sl.PENDING_TTL_HOURS + 5)
           ).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = _item(ws, certified=False)
    # rewrite the item's ts to the aged shape (append-only ledger: the
    # fixture does what time would)
    lines = (ws / "runs" / "evidence-credit.jsonl").read_text(
        "utf-8").splitlines()
    lines[0] = json.dumps({**json.loads(lines[0]), "ts": old},
                          ensure_ascii=False)
    (ws / "runs" / "evidence-credit.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    expired = sl.expire_pending(ws)
    assert expired == [item["id"]]
    actions = [a["action"] for a in sl.read_amendments(ws)]
    assert actions == ["expire"]


# --------------------------------------------- replay + determinism ----

def _record_session(ws: Path) -> None:
    row = _step(ws, tool="Bash")
    certified = sl.record_evidence(
        ws, step_ref=row["call_id"], claim_ref="C-005", kind="confirm",
        artifact={"sha": "a"}, certified=True, ts=TS)
    uncertified = sl.record_evidence(
        ws, step_ref=row["call_id"], claim_ref="C-006", kind="refute",
        artifact={"sha": "b"}, certified=False, ts=TS)
    assert certified is not None and uncertified is not None
    sl.amend(ws, evidence_id=certified["id"], verb="escrow", ts=TS)
    sl.amend(ws, evidence_id=certified["id"], verb="confirm", ts=TS)
    sl.amend(ws, evidence_id=uncertified["id"], verb="escrow", ts=TS)


def test_replay_is_byte_identical(tmp_path) -> None:
    ws = _ws(tmp_path)
    _record_session(ws)
    replayed = sl.replay_credit_ledger(ws)
    recorded = (ws / "runs" / "evidence-credit.jsonl").read_text("utf-8")
    amendments = [json.dumps(r, ensure_ascii=False) for r in
                  sl.read_amendments(ws)]
    assert replayed == "\n".join(amendments) + "\n"
    assert all(line in recorded for line in replayed.splitlines())


def test_same_session_records_byte_identically(tmp_path) -> None:
    a, b = _ws(tmp_path / "a"), _ws(tmp_path / "b")
    for ws in (a, b):
        _record_session(ws)
    assert ((a / "runs" / "step-ledger.jsonl").read_text("utf-8")
            == (b / "runs" / "step-ledger.jsonl").read_text("utf-8"))
    assert ((a / "runs" / "evidence-credit.jsonl").read_text("utf-8")
            == (b / "runs" / "evidence-credit.jsonl").read_text("utf-8"))


# ---------------------------------------------------- interventions ----

def test_intervention_row_is_hash_only(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = sl.record_intervention(ws, trigger="operator-stop",
                                 actor="owner", subject="C-005",
                                 note="pulled the plug", ts=TS)
    assert row is not None
    text = (ws / "runs" / "interventions.jsonl").read_text("utf-8")
    assert "C-005" not in text and "pulled the plug" not in text
    assert len(row["subject_sha"]) == 64 and len(row["note_sha"]) == 64


def test_intervention_fail_open(tmp_path) -> None:
    ws = tmp_path / "bare"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs").chmod(0o500)
    try:
        assert sl.record_intervention(ws, trigger="t", actor="a",
                                      subject="s", note="n") is None
    finally:
        (ws / "runs").chmod(0o700)


# ---------------------------------------------------- the shadow hook ----

def test_hook_writes_only_its_ledger(tmp_path) -> None:
    ws = _ws(tmp_path)
    payload = json.dumps({
        "session_id": "s1", "tool_name": "Bash",
        "tool_input": {"command": "echo SECRET-COMMAND"},
        "tool_response": {"stdout": "SECRET-OUT"},
        "cwd": str(ws)})
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "step_record_capture.py")],
        input=payload, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    ledger = ws / "runs" / "step-ledger.jsonl"
    assert ledger.is_file()
    text = ledger.read_text("utf-8")
    assert "SECRET-COMMAND" not in text and "SECRET-OUT" not in text
    # shadow posture: nothing else appeared in the workspace
    unexpected = {p.relative_to(ws) for p in ws.rglob("*")
                  if p.name != "step-ledger.jsonl"
                  and p.parent.name == "runs"}
    assert not unexpected


def test_hook_garbage_payload_exits_zero(tmp_path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "step_record_capture.py")],
        input="{broken", capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
