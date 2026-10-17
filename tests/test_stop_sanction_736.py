# -*- coding: utf-8 -*-
"""tests/test_stop_sanction_736.py — the stop sanction is hook-owned and sealed.

Defect (#736): the completion gate's second-stop release trusted the
agent-writable task-oracle.yaml adjudication block — the agent could write
its own {second_stop: true, last_decision: PASS} and stop while most claims
were still OPEN (the RC1 live incident: released at 27/37 OPEN). The prior
ledger anchor (#831) only anchored the FIRST sighting of a record, which
legitimizes a forged first entry instead of verifying provenance.

Contract (#736): the gate owns its OWN sanction record and seals it HMAC —
  P1 the seal lives OUTSIDE the agent-writable workspace (shim-owned store
     + key pinned outside the workspace, mirroring the review gate); a
     second stop WITHOUT a sealed record never releases — the old
     self-write path is dead, and the block reason carries the operator
     mint-sanction guidance
  P2 a sealed record whose oracle block was tampered with AFTER the mint
     does not release, and the reason names the tamper (record sha mismatch)
  P3 the seal binds a decision the GATE derived, never the agent-authored
     block text: the gate mints ONLY at a first stop whose judge verdict
     is PASS (a judge-blocked stop mints nothing — a PASS block written
     before the first stop cannot be co-signed), the block's decision
     text is advisory and never read for release (an armed block without
     any decision text still releases on a valid seal), and the operator
     CLI is the only way to seal a deferral while items remain open
  P4 a forged record (agent-written JSON with a wrong HMAC in the store)
     does not release
  P5 the operator CLI face (mint-sanction) is HUMAN-ONLY — the trust root
     for closing with items open — its use is loud (stderr warn + an
     operator-sanctioned deferral ledger event), it mints for legacy runs
     and the gate then releases; a CLI decision contradicting the block's
     own advisory text is refused
  P6 the #831 anchor suite stays green (no regression to its ledger
     behavior), pinned here by a nested run
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"

KEY_HEX = "c" * 64  # 32 bytes of deterministic test key material
_ADJ = {"second_stop": True, "last_decision": "PASS"}


def _load_shim():
    name = "completion_gate_hook_736"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _aim_sanction_home(mod, tmp_path: Path) -> Path:
    """Point the seal key + store at this test's isolated home."""
    home = tmp_path / "sanction-home"
    home.mkdir(exist_ok=True)
    key = home / "kunglao-sanction.key"
    key.write_text(KEY_HEX, encoding="utf-8")
    mod.SANCTION_KEY_PATH = key
    mod.SANCTION_STORE_DIR = home / "sanctions"
    return home


def _mk_ws(tmp_path: Path, adj: dict | None, open_item: bool = False) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    oracle = {"task_text": "x"}
    if open_item:
        oracle["open_items"] = [{"id": "C-1"}]
    if adj is not None:
        oracle["adjudication"] = {"stop_hook_active": adj}
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return ws


def _run(ws: Path, second: bool = True) -> tuple[int, str]:
    mod = _load_shim()
    payload = {"hook_event_name": "Stop", "session_id": "t",
               "cwd": str(ws), "stop_hook_active": second}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(io.StringIO(json.dumps(payload)))
    return rc, buf.getvalue()


def _write_oracle(ws: Path, oracle: dict) -> None:
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


def _activate(ws: Path) -> None:
    from _factories import write_hook_state
    write_hook_state(ws, active_hooks=["completion_gate"],
                     ts="2026-08-11T12:00:00Z", tier="none", phase="IDLE",
                     user_override={}, expires_minutes=30)


# ---------------------------------------------------------------------------
# P1 — without a sealed record the second stop does NOT release
# ---------------------------------------------------------------------------

def test_unsealed_self_write_does_not_release(tmp_path):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    rc, out = _run(ws)
    assert rc == 1, out
    d = json.loads(out)
    assert d["decision"] == "block"
    assert "sealed" in d["reason"]
    # guidance names the operator mint face
    assert "mint-sanction" in d["reason"]


def test_store_record_lives_outside_the_workspace(tmp_path):
    mod = _load_shim()
    home = _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._sanction_mint(ws, _ADJ) is True
    fp = mod._ws_fingerprint(ws)
    rec = mod.SANCTION_STORE_DIR / (fp + ".json")
    assert rec.exists()
    # the store is outside the agent-writable workspace tree
    assert not rec.resolve().is_relative_to(ws.resolve())
    # and the store directory is 0700
    assert stat.S_IMODE(os.stat(mod.SANCTION_STORE_DIR).st_mode) == 0o700
    assert home in rec.resolve().parents


# ---------------------------------------------------------------------------
# P2 — post-mint tamper of the oracle block is detected and named
# ---------------------------------------------------------------------------

def test_post_mint_tamper_blocks_and_names_the_tamper(tmp_path):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._sanction_mint(ws, _ADJ) is True
    # attack: rewrite the block after the seal (the RC1 move, post-mint)
    _write_oracle(ws, {"task_text": "x",
                       "adjudication": {"stop_hook_active": dict(
                           _ADJ, last_decision_at="2026-08-31T02:55:00Z")}})
    rc, out = _run(ws)
    assert rc == 1, out
    d = json.loads(out)
    assert d["decision"] == "block"
    assert "altered" in d["reason"] or "tamper" in d["reason"]


# ---------------------------------------------------------------------------
# P3 — the seal binds the GATE's verdict: mint only at a judge-PASS stop
# ---------------------------------------------------------------------------

def test_pre_first_stop_pass_write_never_releases(tmp_path):
    """The CRITICAL pin: a PASS block written BEFORE the first stop is
    never co-signed. The judge blocks (items open) at the first stop, so
    nothing is sealed, and the second stop stays blocked."""
    mod = _load_shim()
    home = _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ, open_item=True)
    _activate(ws)
    rc1, _ = _run(ws, second=False)  # first stop: judge blocks (open item)
    assert rc1 != 0
    fp = mod._ws_fingerprint(ws)
    assert not (mod.SANCTION_STORE_DIR / (fp + ".json")).exists()
    rc2, out2 = _run(ws)
    assert rc2 == 1, out2
    d = json.loads(out2)
    assert d["decision"] == "block"
    assert "sealed" in d["reason"]


def test_judge_pass_first_stop_seals_then_second_releases(tmp_path):
    """A judge-PASS first stop blocked only by the owed-notes face seals
    the gate's own PASS; the second stop then releases."""
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)  # no open items → judge PASS
    _activate(ws)
    runs = ws / "runs"
    runs.mkdir()
    (runs / "notes-due.yaml").write_text(
        "due:\n  - claim_id: C-1\n", encoding="utf-8")
    rc1, _ = _run(ws, second=False)  # judge PASS + NOTES_DUE block
    assert rc1 != 0
    fp = mod._ws_fingerprint(ws)
    rec = json.loads((mod.SANCTION_STORE_DIR / (fp + ".json")).read_text(
        encoding="utf-8"))
    assert rec["schema"] == "stop-sanction/1"
    assert rec["decision"] == "PASS"  # the gate's verdict, not block text
    assert rec["origin"] == "gate"
    assert rec["record_sha256"] == mod._secondstop_record_sha(_ADJ)
    rc2, out2 = _run(ws)
    assert rc2 == 0, out2
    # and stays released on a repeat stop (idempotent, per the anchor suite)
    rc3, _ = _run(ws)
    assert rc3 == 0


def test_armed_block_without_decision_text_still_releases(tmp_path):
    """The block's decision text is advisory and never read: an armed
    block with NO last_decision at all releases on a valid gate seal."""
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    adj = {"second_stop": True}
    ws = _mk_ws(tmp_path, adj)
    assert mod._sanction_mint(ws, adj) is True
    rc, out = _run(ws)
    assert rc == 0, out


def test_sealed_non_pass_decision_never_releases(tmp_path):
    """A seal bound to a non-PASS decision (operator face) does not release
    even when the on-disk block still matches its sha."""
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    adj = {"second_stop": True}
    ws = _mk_ws(tmp_path, adj)
    assert mod._sanction_mint(ws, adj, decision="DEFER",
                              origin="operator") is True
    rc, out = _run(ws)
    assert rc == 1, out
    assert "not the required PASS" in json.loads(out)["reason"]


# ---------------------------------------------------------------------------
# P4 — a forged store record (no key) does not release
# ---------------------------------------------------------------------------

def test_forged_store_record_does_not_release(tmp_path):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    fp = mod._ws_fingerprint(ws)
    mod.SANCTION_STORE_DIR.mkdir(parents=True)
    forged = {"schema": "stop-sanction/1", "ws_fingerprint": fp,
              "decision": "PASS",
              "record_sha256": mod._secondstop_record_sha(_ADJ),
              "minted_ts": 12345, "hmac": "f" * 64}
    (mod.SANCTION_STORE_DIR / (fp + ".json")).write_text(
        json.dumps(forged), encoding="utf-8")
    rc, out = _run(ws)
    assert rc == 1, out
    assert "HMAC" in json.loads(out)["reason"]


def test_missing_key_blocks_closed(tmp_path):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._sanction_mint(ws, _ADJ) is True
    mod.SANCTION_KEY_PATH.unlink()  # operator lost the key
    rc, out = _run(ws)
    assert rc == 1, out
    d = json.loads(out)
    assert d["decision"] == "block"
    assert "key" in d["reason"]
    assert "sanction-key-init" in d["reason"]


def test_corrupt_store_record_blocks(tmp_path):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    fp = mod._ws_fingerprint(ws)
    mod.SANCTION_STORE_DIR.mkdir(parents=True)
    (mod.SANCTION_STORE_DIR / (fp + ".json")).write_text(
        "{not json", encoding="utf-8")
    rc, out = _run(ws)
    assert rc == 1, out
    assert "corrupt" in json.loads(out)["reason"]


# ---------------------------------------------------------------------------
# P5 — the operator CLI face mints for legacy runs
# ---------------------------------------------------------------------------

def test_operator_cli_mint_releases_legacy_run(tmp_path, capsys):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)  # legacy run: block present, no seal
    (ws / "runs" / "logs").mkdir(parents=True)  # unified-log target
    rc, out = _run(ws)
    assert rc == 1, out  # strict side before the operator mints
    assert mod._cli(["mint-sanction", str(ws), "PASS"]) == 0
    captured = capsys.readouterr()
    assert "mint OK" in captured.out
    # the operator deferral is loud: the stderr warn names it
    assert "operator-sanctioned deferral" in captured.err
    # and a distinct unified-log event names the operator-sanctioned
    # deferral (runs/logs/kunglao-<date>.jsonl)
    logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert logs, "unified-log event face missing"
    rows = [json.loads(line) for line in logs[0].read_text(
        encoding="utf-8", errors="replace").splitlines() if line.strip()]
    assert any(r.get("action") == "operator_sanction_deferral"
               for r in rows), rows
    rc2, out2 = _run(ws)
    assert rc2 == 0, out2


def test_cli_refuses_decision_contradicting_the_block(tmp_path, capsys):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._cli(["mint-sanction", str(ws), "FAIL"]) == 2
    assert "contradicts" in capsys.readouterr().err


def test_cli_refuses_without_a_usable_key(tmp_path, capsys):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    mod.SANCTION_KEY_PATH.unlink()
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._cli(["mint-sanction", str(ws), "PASS"]) == 2
    assert "sanction-key-init" in capsys.readouterr().err


def test_cli_key_init_provisions_and_mints(tmp_path, capsys):
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    mod.SANCTION_KEY_PATH.unlink()
    ws = _mk_ws(tmp_path, _ADJ)
    assert mod._cli(["sanction-key-init"]) == 0
    assert mod.SANCTION_KEY_PATH.exists()
    assert mod._cli(["mint-sanction", str(ws), "PASS"]) == 0
    rc, _ = _run(ws)
    assert rc == 0


# ---------------------------------------------------------------------------
# P6 — the ledger-anchor suite keeps its passing behavior
# ---------------------------------------------------------------------------

def test_anchor_suite_still_green():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_secondstop_anchor_831.py",
         "-q"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("decision", ["PASS", "DEFER"])
def test_mint_records_the_caller_asserted_decision(tmp_path, decision):
    """The record's decision is caller-asserted (the gate's verdict or the
    operator's), never read out of the agent-authored block, and the
    sealing face is bound into the signed record."""
    mod = _load_shim()
    _aim_sanction_home(mod, tmp_path)
    ws = _mk_ws(tmp_path, {"second_stop": True, "last_decision": "WHATEVER"})
    assert mod._sanction_mint(ws, {"second_stop": True},
                              decision=decision,
                              origin="operator") is True
    fp = mod._ws_fingerprint(ws)
    rec = json.loads((mod.SANCTION_STORE_DIR / (fp + ".json")).read_text(
        encoding="utf-8"))
    assert rec["decision"] == decision
    assert rec["origin"] == "operator"
