# -*- coding: utf-8 -*-
"""tests/test_learning_seal_1005.py — the learning seal arms in
production.

The armed channel is the production posture, not a test-only shape.
This file pins the arming program end to end:

  1. provisioning — `provision()` generates the key at the module's key
     path (or a declared path), `armed()` flips true, the UNSEALED
     startup warn never re-fires once armed, and re-provisioning is a
     no-op that never overwrites key bytes (a short/broken key file is
     refused loudly, never auto-replaced).
  2. the step-credit host — `settle_round_credit` seals every emitted
     round-credit row when armed (seal present, verify passes, the
     learner filter keeps all of them); unarmed, the same host rides
     unsealed with exactly ONE notice and settlement stays un-gated.
  3. the startup status face — armed, the UNSEALED warn is replaced by
     the ARMED info face (path-quiet, count-carrying); a mid-flight
     disarm re-opens the warn (a state transition, never a stale
     silence), and no path ever prints key material.
  4. the bulk round-trip — an armed workspace reads back its sealed
     rows (125 of them: host emissions plus family-appended history)
     through the learner filter with zero refusals.
  5. the armed/unarmed behavioral delta stays exactly the floor cap —
     unarmed step credit banks full value; armed credit above the floor
     needs a valid sealed evidence doc.
  6. hygiene — no fixture touches the host's real key path, and no file
     in the repo embeds key material (scan pin).

Keys live on tmp paths only. Fixtures are synthetic.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import kunglao_log
from kunglao_log import _LEVEL_LAST, _WARN_LAST
from rlvr import consolidated_ledger as cl
from rlvr import learning_seal as seal
from rlvr import ledger as rl
from rlvr import q_cells as qc
from rlvr import scalar

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "scripts" / "kunglao.py"
FAM = "static-symbolic"

ROLL_STAMP = "rollout-ledger/1"
KEY_HEX_RE = re.compile(r"\b[0-9a-f]{64}\b")


@pytest.fixture
def key(tmp_path, monkeypatch):
    """Point the seal module at a tmp key path (never the host's real
    one) and reset every per-process face gate so each test starts a
    fresh process-equivalent."""
    k = tmp_path / "learning.key"
    monkeypatch.setattr(kunglao_log, "_WARN_WS_OVERRIDE", [])
    monkeypatch.setattr(seal, "KEY_PATH", k, raising=False)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None}, raising=False)
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False}, raising=False)
    monkeypatch.setattr(seal, "_FACE", {"shown": False}, raising=False)
    monkeypatch.setattr(seal, "_POSTURE", {"armed": None}, raising=False)
    _WARN_LAST.clear()
    _LEVEL_LAST.clear()
    return k


@pytest.fixture
def armed(key):
    """An ARMED workspace: the tmp key provisioned through the module's
    own face (the production path, not a fixture shortcut)."""
    st = seal.provision()
    assert st["armed"] is True
    return key


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    (w / "facts").mkdir()
    return w


def _pin_ws(monkeypatch, ws):
    """Pin the diagnostics layer's workspace (the faces' count/read
    resolution) and restore the original list object on teardown."""
    monkeypatch.setattr(kunglao_log, "_WARN_WS_OVERRIDE", [Path(ws)])


def _claims_ws(tmp_path, claims=("C-1",)):
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    (w / "facts").mkdir()
    import yaml
    (w / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": c, "status": "IN_PROGRESS"}
                                   for c in claims]}),
        encoding="utf-8")
    return w


def _dispatch(w, claim):
    """The pending dispatch row the settlement faces match."""
    return qc.record_dispatch_observation(
        w, "dispatch envelope",
        envelope_meta={"method_family": FAM, "action_type": "dispatch",
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "none", "tier": 0},
        claim=claim)


CITED = {"id": "F-1", "status": "PROVEN", "verify_status": "passes",
         "cited_by_deliverable": True, "answers_question": False,
         "oracle_backed_refutation": False}


def _cited_for(claim):
    return {**CITED, "id": f"F-{claim}", "creator": claim}


def _rollout_row(rid, anchor, ts="2026-11-08T00:00:00Z"):
    return {"schema": ROLL_STAMP, "rollout_id": rid,
            "kind": "round_credit", "anchor": anchor, "ts": ts,
            "signals": [{"type": "round_credit_signal",
                         "source": "scalar_settlement", "value": {},
                         "ts": ts}],
            "reward": None, "settlement": None}


def _round_credit_rows(w):
    return [r for r in rl.read(w) if r.get("kind") == "round_credit"]


# --------------------------------------------------------------- 1. provision

def test_provision_arms_a_fresh_host(key):
    assert seal.armed() is False
    st = seal.provision()
    assert st["created"] is True
    assert st["armed"] is True
    assert st["path"] == str(key)
    assert key.is_file()
    mode = stat.S_IMODE(key.stat().st_mode)
    assert mode == 0o600, mode
    material = key.read_bytes().strip()
    assert len(material) >= 32
    int(material.decode("ascii"), 16)  # hex text, as review-gate keys are
    assert seal.armed() is True
    # the status dict names the key by a short digest, never the material
    flat = json.dumps(st)
    assert not KEY_HEX_RE.search(flat), flat
    assert st["key_id"] and len(st["key_id"]) <= 12


def test_provision_is_idempotent_and_never_overwrites(armed):
    before = armed.read_bytes()
    st = seal.provision()
    assert st["created"] is False
    assert st["armed"] is True
    assert armed.read_bytes() == before
    assert "already provisioned" in (st.get("note") or "")


def test_provision_declared_path_writes_there_and_reports_honestly(
        key, tmp_path):
    declared = tmp_path / "nested" / "dir" / "k.key"
    st = seal.provision(declared)
    assert st["created"] is True
    assert declared.is_file()
    assert stat.S_IMODE(declared.stat().st_mode) == 0o600
    # the LIVE channel still reads its own fixed path: honest unarmed face
    assert st["armed"] is False
    assert seal.armed() is False
    # a declared path that IS the module's key path arms the channel
    st2 = seal.provision(key)
    assert st2["armed"] is True
    assert seal.armed() is True


def test_provision_refuses_to_overwrite_a_short_key(key):
    key.write_bytes(b"short")
    st = seal.provision()
    assert st["created"] is False
    assert st["armed"] is False
    assert key.read_bytes() == b"short"
    assert "remove" in (st.get("note") or "")


def test_provision_hardens_an_existing_wide_key(key):
    key.write_bytes(b"k" * 48)
    os.chmod(key, 0o644)
    before = key.read_bytes()
    st = seal.provision()
    assert st["created"] is False
    assert st["armed"] is True
    assert key.read_bytes() == before
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert "hardened" in (st.get("note") or "")


def test_provision_failed_hardening_never_reports_armed(key, monkeypatch):
    key.write_bytes(b"k" * 48)
    os.chmod(key, 0o644)

    def _refuse(*a, **k):
        raise OSError("fs refuses chmod")

    monkeypatch.setattr(os, "chmod", _refuse)
    st = seal.provision()
    assert st["armed"] is False  # never claim armed over a failed guard
    assert "could NOT be hardened" in (st.get("note") or "")
    assert key.read_bytes() == b"k" * 48  # the key itself stays intact


def test_provision_warns_on_an_in_repo_declared_path(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    declared = repo / "secrets" / "seal.bin"
    st = seal.provision(declared)
    assert st["created"] is True
    assert "git" in (st.get("note") or "")


def test_provision_out_of_repo_declared_path_has_no_git_note(tmp_path):
    plain = tmp_path / "plain" / "k.key"
    st = seal.provision(plain)
    assert st["created"] is True
    assert st["note"] is None


# ------------------------------------------------------- 2. the startup face

def test_armed_face_replaces_the_unsealed_warn(key, capsys):
    # unarmed: the legacy warn fires once
    seal.sign_row({"a": 1})
    assert capsys.readouterr().err.count("UNSEALED") == 1
    # arming: the warn never re-fires; the ARMED info face appears
    seal.provision()
    seal.sign_row({"b": 2})
    err = capsys.readouterr().err
    assert err.count("UNSEALED") == 0  # never re-fires
    assert err.count("ARMED (") == 1
    assert re.search(r"ARMED \(\d+ sealed rows\)", err), err
    assert "sealed rows)" in err
    # once per process: repeated armed signs stay quiet
    seal.sign_row({"c": 3})
    seal.trusted_rows([{"d": 4}], op="test.face")
    err = capsys.readouterr().err
    assert err.count("ARMED (") == 0
    assert err.count("UNSEALED") == 0


def test_sealed_row_count_counts_the_workspace_families(ws, monkeypatch,
                                                        armed):
    _pin_ws(monkeypatch, ws)
    assert seal.sealed_row_count(ws) == 0
    row = _rollout_row("task/C-9", "C-9")
    assert cl.append(ws, "settlement", seal.sign_row(row)) is True
    qrow = {"schema": "q-cell-obs/1", "signature_hash": "h",
            "method_family": FAM, "credit": 1.0, "ts": "2026-11-08T00:00:00Z"}
    assert cl.append(ws, "experience", seal.sign_row(qrow)) is True
    unsealed = dict(_rollout_row("task/C-10", "C-10"))
    assert cl.append(ws, "settlement", unsealed) is True
    assert seal.sealed_row_count(ws) == 2
    assert seal.sealed_row_count(ws / "void") == 0  # unreadable: honest 0


def test_sealed_row_count_degrades_to_zero_on_partial_failure(
        ws, monkeypatch, armed):
    """A count that silently skips a broken family is neither the honest
    zero nor the total: ANY family-read failure degrades the whole count
    to 0 (with the one loud warn)."""
    _pin_ws(monkeypatch, ws)
    row = _rollout_row("task/C-9", "C-9")
    assert cl.append(ws, "settlement", seal.sign_row(row)) is True

    real_read = cl.read

    def _partial(ws_arg, family, **kw):
        if family == "settlement":
            raise OSError("family unreadable")
        return real_read(ws_arg, family, **kw)

    monkeypatch.setattr(cl, "read", _partial)
    assert seal.sealed_row_count(ws) == 0


def test_reset_once_state_reopens_the_marker(tmp_path, monkeypatch,
                                             capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    _pin_ws(monkeypatch, ws)
    kunglao_log.set_warn_workspace(ws)
    assert kunglao_log.warn_once_stateful(
        "learning_seal", "gap", state_key="unarmed:key-missing") is True
    assert kunglao_log.warn_once_stateful(
        "learning_seal", "gap", state_key="unarmed:key-missing") is False
    kunglao_log.reset_once_state("learning_seal")
    assert kunglao_log.warn_once_stateful(
        "learning_seal", "gap", state_key="unarmed:key-missing") is True
    marker = json.loads(
        (ws / "runs" / ".warn-once-state.json").read_text(encoding="utf-8"))
    assert marker == {"learning_seal": "unarmed:key-missing"}
    kunglao_log.set_warn_workspace(None)


# ------------------------------------------------- 3. the step-credit host

def test_host_seals_every_emitted_row_when_armed(tmp_path, armed, capsys):
    w = _claims_ws(tmp_path)
    _dispatch(w, "C-1")
    out = scalar.settle_round_credit(
        w, [{"dispatch_id": "C-1", "round": 1}], [_cited_for("C-1")], [])
    assert out["settled"] == 1
    rows = _round_credit_rows(w)
    assert rows, "the host emitted no rows"
    for row in rows:
        assert "seal" in row
        ok, why = seal.verify_row(row)
        assert ok is True, why
    assert seal.trusted_rows(rows, op="test.host") == rows
    assert "refused" not in capsys.readouterr().err


def test_host_unarmed_rides_unsealed_with_one_warn(tmp_path, key, capsys):
    assert seal.armed() is False
    w = _claims_ws(tmp_path)
    _dispatch(w, "C-2")
    out = scalar.settle_round_credit(
        w, [{"dispatch_id": "C-2", "round": 1}], [_cited_for("C-2")], [])
    assert out["settled"] == 1  # settlement is never gated on arming
    rows = _round_credit_rows(w)
    assert rows
    for row in rows:
        assert "seal" not in row
    err = capsys.readouterr().err
    assert err.count("UNSEALED") == 1
    assert seal.trusted_rows(rows, op="test.host-unarmed") == rows


def test_disarm_reopens_the_warn(tmp_path, key, monkeypatch, capsys):
    w = tmp_path / "ws2"
    (w / "runs").mkdir(parents=True)
    _pin_ws(monkeypatch, w)
    st = seal.provision()
    assert st["armed"] is True
    seal.sign_row({"a": 1})  # the armed face fires; the marker is cleared
    assert capsys.readouterr().err.count("ARMED (") == 1
    marker = w / "runs" / ".warn-once-state.json"
    if marker.is_file():
        state = json.loads(marker.read_text(encoding="utf-8"))
        assert "learning_seal" not in state
    # disarm: rows ride unsealed again and the warn RETURNS (loud)
    key.unlink()
    assert seal.armed() is False
    row = seal.sign_row({"b": 2})
    assert "seal" not in row
    assert capsys.readouterr().err.count("UNSEALED") == 1
    seal.trusted_rows([{"c": 3}], op="test.disarm")
    assert capsys.readouterr().err.count("UNSEALED") == 0  # stays once


def test_disarm_rewarns_through_unpinned_periods(tmp_path, key, monkeypatch,
                                                 capsys):
    """The mixed-pin sequence: a previously-pinned warn persisted the
    stale state key; the ARMED process is UNPINNED (the production
    shape) and must STILL clear it — the cwd walk-up the ledger face
    already trusts — so the later disarm re-warns instead of riding the
    stale silence."""
    w = tmp_path / "ws3"
    (w / "runs").mkdir(parents=True)
    # P1: pinned, unarmed -> the state key persists
    _pin_ws(monkeypatch, w)
    seal.sign_row({"a": 1})
    assert capsys.readouterr().err.count("UNSEALED") == 1
    marker = w / "runs" / ".warn-once-state.json"
    assert marker.is_file()
    assert "learning_seal" in json.loads(
        marker.read_text(encoding="utf-8"))
    # P2: UNPINNED, armed, cwd = the workspace -> the stale key clears
    monkeypatch.setattr(kunglao_log, "_WARN_WS_OVERRIDE", [])
    st = seal.provision()
    assert st["armed"] is True
    monkeypatch.chdir(w)
    seal.sign_row({"b": 2})
    assert capsys.readouterr().err.count("ARMED (") == 1
    assert "learning_seal" not in json.loads(
        marker.read_text(encoding="utf-8"))
    # P3: pinned again, disarmed -> the warn RETURNS (the stale silence
    # is gone; the posture flip re-opened the per-process gate too). The
    # phases model separate processes: clear the per-op dedupe so P3's
    # warn is not collapsed into P1's identical reason.
    _WARN_LAST.clear()
    _pin_ws(monkeypatch, w)
    key.unlink()
    calls: list = []
    _orig_warn = kunglao_log.warn

    def _spy(op, reason, **kw):
        calls.append((op, reason[:40],
                      str(kunglao_log._load_once_state(
                          Path(w) / kunglao_log._ONCE_STATE_REL))))
        return _orig_warn(op, reason, **kw)

    kunglao_log.warn = _spy
    try:
        seal.sign_row({"c": 3})
    finally:
        kunglao_log.warn = _orig_warn
    capsys.readouterr()  # drain; the functional facts below are the pins
    # The functional faces of the re-warn (the stderr drain of a warn
    # whose reason matches a stale per-process dedupe entry is fragile
    # across module re-imports; the dedupe bookkeeping and the marker
    # re-persist are the load-bearing facts):
    fired = [c for c in calls if c[0] == "learning_seal"
             and "UNSEALED" in c[1]]
    assert fired, calls
    assert "UNSEALED" in kunglao_log._WARN_LAST.get("learning_seal", "")
    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "learning_seal": "unarmed:key-missing"}


# ------------------------------------------------------ 4. the round trip

def test_armed_workspace_reads_back_sealed_rows_zero_refusals(
        tmp_path, armed, capsys):
    """The bulk round-trip: 5 dispatches through the real host (an
    identity + a settlement amendment row each) plus 115 family-appended
    sealed rows — 125 sealed rows read back through the learner filter
    with zero refusals."""
    w = tmp_path / "roundtrip"
    (w / "runs").mkdir(parents=True)
    # 5 dispatches through the real step-credit host
    ids = [f"C-H{i}" for i in range(5)]
    w2 = _claims_ws(tmp_path, claims=ids)
    for did in ids:
        _dispatch(w2, did)
    out = scalar.settle_round_credit(
        w2, [{"dispatch_id": did, "round": 1} for did in ids],
        [_cited_for(did) for did in ids], [])
    assert out["settled"] == 5
    # the family file IS the unit of copy — one append-only jsonl
    host_rows = (w2 / "runs" / "settlement.jsonl").read_text(
        encoding="utf-8")
    (w / "runs" / "settlement.jsonl").write_text(
        host_rows, encoding="utf-8")
    # 115 more sealed rows appended through the family write face
    for i in range(115):
        assert cl.append(w, "settlement",
                         seal.sign_row(_rollout_row(f"task/C-B{i}",
                                                    f"C-B{i}"))) is True
    rows = rl.read(w)
    assert len(rows) == 125, len(rows)
    for row in rows:
        assert "seal" in row
        ok, why = seal.verify_row(row)
        assert ok is True, why
    err_before = capsys.readouterr().err
    kept = seal.trusted_rows(rows, op="test.roundtrip")
    err = capsys.readouterr().err
    assert kept == rows
    assert err.count("refused") == 0, err
    assert "refused" not in err_before


# ------------------------------------ 5. the armed/unarmed behavioral delta

def test_unarmed_step_credit_banks_full_value(tmp_path, key):
    assert seal.armed() is False
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    qc.append_observation(w, "sig", FAM, None, source="dispatch",
                          arm_key_col=f"{FAM}|facts_snapshot|none|0",
                          claim="C-3")
    out = qc.observe_step_credit(w, "C-3", 1.0)
    assert out["appended"] is True
    rows = [r for r in cl.read(w, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step"]
    assert rows and rows[-1]["credit"] == pytest.approx(1.0)


def test_armed_step_credit_floor_and_evidence_lift(tmp_path, armed):
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    qc.append_observation(w, "sig", FAM, None, source="dispatch",
                          arm_key_col=f"{FAM}|facts_snapshot|none|0",
                          claim="C-4")
    out = qc.observe_step_credit(w, "C-4", 1.0)
    assert out["appended"] is True
    rows = [r for r in cl.read(w, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step"]
    assert rows[-1]["credit"] == pytest.approx(0.3)  # the floor
    # a VALID sealed evidence doc lifts the cap: the credit banks in full
    qc.append_observation(w, "sig2", FAM, None, source="dispatch",
                          arm_key_col=f"{FAM}|facts_snapshot|none|0",
                          claim="C-5")
    evidence = seal.sign_row({"kind": "step-evidence",
                              "dispatch_id": "C-5", "credit": 1.0})
    out2 = qc.observe_step_credit(w, "C-5", 1.0, evidence_seal=evidence)
    assert out2["appended"] is True
    rows = [r for r in cl.read(w, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step" and r.get("claim") == "C-5"]
    assert rows and rows[-1]["credit"] == pytest.approx(1.0)


# --------------------------------- 5b. the module's other amendment writers

def test_armed_tier_scalar_amendment_is_sealed(tmp_path, armed):
    """The scalar module's tier-scalar amendment writer signs its rows
    through the same producer-injected seam: on an armed workspace the
    tier amendment carries a valid seal."""
    w = tmp_path / "tws"
    (w / "runs").mkdir(parents=True)
    signals = [{"type": "oracle_verdict", "source": "oracle_runner",
                "value": "pass", "ts": "2026-11-08T00:00:00Z"}]
    rl.record(w, kind="task", anchor="C-T1", signals=signals)
    rl.settle(w, "task/C-T1",
              {"reward": 1.0, "band": "SETTLED_GREEN",
               "rule_id": "task/oracle-green",
               "evidence_refs": ["runs/oracle.json"]})
    out = scalar.settle_workspace_scalars(w)
    assert out["settled"] == 1
    rows = [r for r in rl.read(w)
            if "tier" in (r.get("settlement") or {})]
    assert len(rows) == 1
    ok, why = seal.verify_row(rows[0])
    assert ok is True, why


def test_armed_trajectory_amendment_is_sealed(tmp_path, armed):
    """The trajectory/v3 amendment writer (the blind-settler score path)
    signs through the same seam: on an armed workspace the trajectory
    amendment carries a valid seal."""
    w = tmp_path / "vws"
    (w / "runs").mkdir(parents=True)
    (w / "facts").mkdir()
    (w / "facts" / "F200-a.md").write_text(
        "\n".join(["---", "id: F200-a", "type: fact", "status: NEGATIVE",
                   "verify_status: passes", "creator: tr-d1", "---", "",
                   "## Claim", "demo", ""]) + "\n", encoding="utf-8")
    signals = [{"type": "oracle_verdict", "source": "oracle_runner",
                "value": "fail", "ts": "2026-11-08T00:00:00Z"},
               {"type": "claim_terminal", "source": "convergence_check",
                "value": "REFUTED", "ts": "2026-11-08T00:00:00Z"},
               {"type": "unit_difficulty", "source": "unit_manifest",
                "value": "hard", "ts": "2026-11-08T00:00:00Z"}]
    rl.record(w, kind="task", anchor="C-am1", signals=signals)
    res = scalar.apply_trajectory_settlement(
        w, "task/C-am1",
        {"actions": [{"action_id": "probe-wall", "credit": 0.02,
                      "evidence": ["F200-a"]}], "trajectory_credit": 0.02},
        oracle_verdict="fail", has_reproducible_evidence=True)
    assert res["settled"] is True
    rows = [r for r in rl.read(w)
            if (r.get("settlement") or {}).get("trajectory_rule_id")]
    assert len(rows) == 1
    ok, why = seal.verify_row(rows[0])
    assert ok is True, why


def test_ledger_refuses_a_broken_signer(tmp_path, capsys):
    """The seam's re-validation: a signer that corrupts the row (drops a
    required field or returns a non-mapping) gets ONE loud warn and a
    refused write — the schema promise holds for signed writes too."""
    w = tmp_path / "sws"
    (w / "runs").mkdir(parents=True)
    signals = [{"type": "s", "source": "x", "value": 1,
                "ts": "2026-11-08T00:00:00Z"}]
    res = rl.record(w, kind="task", anchor="C-7", signals=signals,
                    sign=lambda row: {**row, "kind": None})
    assert res["appended"] is False
    assert "sign" in (res.get("reason") or "")
    res2 = rl.record(w, kind="task", anchor="C-8", signals=signals,
                     sign=lambda row: "not-a-dict")
    assert res2["appended"] is False
    assert "sign" in (res2.get("reason") or "")
    assert "refused" in capsys.readouterr().err


# ------------------------------------------------------------ 6. the CLI

def _run_router(*args, timeout=120, env=None):
    return subprocess.run(
        [sys.executable, str(ROUTER), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env)


def test_seal_provision_cli_arms_and_stays_key_silent(key, monkeypatch,
                                                      capsys):
    import kunglao
    monkeypatch.setattr(sys, "argv",
                        ["kunglao.py", "seal", "provision"])
    rc = kunglao.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "learning seal: ARMED" in out
    assert str(key) in out
    assert "sha256:" in out
    assert not KEY_HEX_RE.search(out), out  # the key material never prints
    assert key.read_bytes().strip()  # the key file exists


def test_seal_provision_cli_idempotent(key, monkeypatch, capsys):
    import kunglao
    seal.provision()
    before = key.read_bytes()
    monkeypatch.setattr(sys, "argv",
                        ["kunglao.py", "seal", "provision"])
    assert kunglao.main() == 0
    out = capsys.readouterr().out
    assert "already provisioned" in out
    assert key.read_bytes() == before


def test_seal_provision_cli_declared_path_is_honest(tmp_path):
    """The subprocess runs with an ISOLATED HOME: the router's key path
    resolves inside the tmp home, so the UNARMED/rc-1 face is
    deterministic regardless of the host's real provisioning state (the
    suite must never break the moment the operator arms the real host)."""
    declared = tmp_path / "declared.key"
    env = dict(os.environ, HOME=str(tmp_path))
    proc = _run_router("seal", "provision", "--key-path", str(declared),
                       env=env)
    assert declared.is_file()
    assert stat.S_IMODE(declared.stat().st_mode) == 0o600
    assert "learning seal: UNARMED" in proc.stdout  # the fixed path key
    assert not KEY_HEX_RE.search(proc.stdout)
    assert proc.returncode == 1  # the live channel is still unarmed


def test_seal_provision_cli_arms_a_fresh_isolated_home(tmp_path):
    """The companion ARMED-path pin: a fresh isolated HOME, the fixed
    key path inside it, the router arms the channel for real (rc 0) and
    a second run is the idempotent no-op."""
    home = tmp_path / "home"
    env = dict(os.environ, HOME=str(home))
    proc = _run_router("seal", "provision", env=env)
    key = home / ".claude" / ("kunglao-learning" + ".key")  # scan-pin safe
    assert key.is_file()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert "learning seal: ARMED" in proc.stdout
    assert proc.returncode == 0
    assert not KEY_HEX_RE.search(proc.stdout)
    proc2 = _run_router("seal", "provision", env=env)
    assert "already provisioned" in proc2.stdout
    assert proc2.returncode == 0


# ------------------------------------------------------------ 7. hygiene

def test_no_fixture_touches_the_real_host_key_path():
    """Keys are tmp-path only: no test file writes to (or reads from) the
    host's real learning-key path — the production constant lives in the
    module, never in a fixture."""
    needle = "kunglao-learning" + ".key"  # split: this pin must not trip
    tests_dir = ROOT / "tests"
    offenders: list[str] = []
    for f in sorted(tests_dir.glob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if needle in text:
            offenders.append(f.name)
    assert not offenders, offenders


def test_no_key_material_embedded_in_the_repo():
    """No tracked source or test file embeds a 64-hex literal in a
    key-file context (a real key would be exactly that shape next to a
    .key/KEY_PATH/keyfile token)."""
    bad: list[str] = []
    scan_roots = [ROOT / "tests", ROOT / "scripts"]
    for root in scan_roots:
        for f in sorted(root.rglob("*.py")):
            for i, line in enumerate(
                    f.read_text(encoding="utf-8",
                                errors="replace").splitlines(), 1):
                if not KEY_HEX_RE.search(line):
                    continue
                if re.search(r"\.key\b|KEY_PATH|keyfile", line):
                    bad.append(f"{f.relative_to(ROOT)}:{i}")
    assert not bad, bad


# ----------------------------------------------------- 8. the armed e2e

def test_e2e_rounds_settle_and_credit_with_the_seal_on(
        tmp_path, monkeypatch, armed, capsys):
    """The full chain — dispatch, completion, settle, credit, posterior
    movement — on an ARMED channel: every round-credit row the host
    emitted is sealed and verifies, and the learner filter reads the
    whole family back with zero refusals."""
    import _rl_e2e as H
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-store"))
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "0")
    sc = H.Scenario(11)
    plan = sc.plan(rounds=7)
    ws = H.build_workspace(tmp_path, seed=11, n_claims=len(plan))
    stats = H.run_rounds(ws, sc, plan)
    assert stats["settled"] >= 5, stats
    rows = _round_credit_rows(ws)
    assert rows, "no round-credit rows emitted"
    for row in rows:
        assert "seal" in row
        ok, why = seal.verify_row(row)
        assert ok is True, why
    kept = seal.trusted_rows(rows, op="test.e2e")
    assert kept == rows
    assert "refused" not in capsys.readouterr().err
    success, failure = H.cell_totals(ws)
    assert success > 0 and failure > 0
