# -*- coding: utf-8 -*-
"""tests/test_blind_settlement_687.py — settlement is not blind: the
settlement subagent rides a BLIND input contract (issue-687).

Acceptance pins from the card:

1. settler inputs exclude runs/method-family-log.jsonl (and the q-cell
   sibling) — refused at the door, never opened on a legal build;
2. re-running settlement on the same artifacts is byte-identical;
3. the settler's own cost enters cost_t (r_incr = ALPHA*dPhi - LAMBDA*
   cost_t = tokens/10000 + seconds/3600 — the grader pays);
4. the producer's narrative (notes/, worker-status, verification records,
   fact conclusions, the verdict conclusion) never enters the settler
   input — neither as an artifact nor smuggled at the settlement gate.

Mechanical blindness for the settler ACT identity pins live with the
barrier's own suite (tests/test_rt_read_barrier_652.py). Fixtures are
SYNTHETIC and deliberately POISONED (sentinel strings in every
excluded face).
"""
from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlvr.settlement_scorer as bss  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import ledger as rl  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"
LEDGER_REL = Path("runs") / "rollout-ledger.jsonl"


def _ws(tmp_path: Path) -> Path:
    """Poisoned workspace: every excluded face carries a sentinel."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "evidence").mkdir()
    (ws / "evidence" / "raw-step.bin").write_bytes(b"raw-step-artifact-bytes")
    (ws / "evidence" / "verdict.json").write_text(
        '{"verdict": "POISON_VERDICT"}', encoding="utf-8")
    (ws / "runs").mkdir()
    (ws / "runs" / "method-family-log.jsonl").write_text(
        '{"sentinel": "POISON_METHOD_FAMILY"}\n', encoding="utf-8")
    (ws / "runs" / "q-cell-log.jsonl").write_text(
        '{"sentinel": "POISON_Q_CELL"}\n', encoding="utf-8")
    (ws / "runs" / "experience.jsonl").write_text(
        '{"sentinel": "POISON_EXPERIENCE"}\n', encoding="utf-8")
    for name, body in (("worker-status-w9.md", "POISON_WORKER_STATUS"),
                       ("W9-verify-note.md", "POISON_VERIFY_NOTE"),
                       ("verification-C-9.md", "POISON_VERIFICATION")):
        (ws / "runs" / name).write_text(body + "\n", encoding="utf-8")
    (ws / "notes").mkdir()
    (ws / "notes" / "worker-report.md").write_text(
        "POISON_PRODUCER_NARRATIVE\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\ntype: fact\n---\nPOISON_FACT_CONCLUSION\n",
        encoding="utf-8")
    return ws


def _sig(type_: str, source: str, value) -> dict:
    return {"type": type_, "source": source, "value": value, "ts": "2026-10-15T00:00:00Z"}


def _input(ws: Path) -> dict:
    return bss.settler_input(
        ws, claim="C-9", identity="settle-1",
        artifact_paths=["evidence/raw-step.bin"])


def _verdict(credit: float, cite: str) -> dict:
    """The settler's natural ruling: cite the artifact it actually saw
    (the input doc's own path — the settle entry vouches for it)."""
    return {"actions": [{"action_id": "step-1", "credit": credit,
                         "evidence": [cite]}],
            "trajectory_credit": credit}


def _spy_opens(monkeypatch) -> list[str]:
    """Record every file handle the builder opens during the call window."""
    opened: list[str] = []
    real_open = builtins.open

    def _spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy)
    return opened


def test_settler_inputs_exclude_method_family_log(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    # refused at the door — the learning faces are never legal artifacts
    # (#721: the consolidated experience.jsonl rides the same wall)
    for rel in ("runs/method-family-log.jsonl", "runs/q-cell-log.jsonl",
                "runs/experience.jsonl"):
        with pytest.raises(ValueError, match="excluded"):
            bss.settler_input(ws, claim="C-9", identity="settle-1",
                              artifact_paths=[rel])
    # a legal build opens ONLY the listed artifacts (no workspace scan)
    opened = _spy_opens(monkeypatch)
    doc = bss.settler_input(ws, claim="C-9", identity="settle-1",
                            artifact_paths=["evidence/raw-step.bin"])
    blob = json.dumps(doc, sort_keys=True)
    assert doc["schema"] == bss.SETTLEMENT_INPUT_SCHEMA
    assert "POISON_METHOD_FAMILY" not in blob
    assert "POISON_Q_CELL" not in blob
    assert "POISON_EXPERIENCE" not in blob
    assert not any("method-family-log" in p or "q-cell-log" in p
                   or "experience.jsonl" in p
                   for p in opened), opened
    assert any(p.endswith("raw-step.bin") for p in opened), opened


# ---------- 2: byte-identical idempotency ---------------------------------

def test_settlement_is_idempotent_byte_identical(tmp_path):
    ws = _ws(tmp_path)
    rl.record(ws, kind="task", anchor="C-9",
              signals=[_sig("oracle_verdict", "oracle_runner", "pass")])
    input_doc = _input(ws)
    verdict = _verdict(0.6, "evidence/raw-step.bin")
    first = bss.settle_blind(
        ws, "task/C-9", verdict, input_doc=input_doc,
        oracle_verdict=None, has_reproducible_evidence=False,
        now="2026-10-15T00:00:00Z")
    assert first["settled"] is True, first
    ledger = ws / LEDGER_REL
    bytes_after_first = ledger.read_bytes()
    # same artifacts, same verdict, DIFFERENT clock — no ledger churn
    second = bss.settle_blind(
        ws, "task/C-9", verdict, input_doc=input_doc,
        oracle_verdict=None, has_reproducible_evidence=False,
        now="2027-01-01T23:59:59Z")
    assert second["settled"] is False, second
    assert "duplicate" in str(second["reason"])
    assert ledger.read_bytes() == bytes_after_first, (
        "identical re-application must leave the ledger byte-identical")
    # the input build itself is deterministic (same bytes, same doc)
    rebuilt = _input(ws)
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(
        input_doc, sort_keys=True)


# ---------- 3: the grader pays (cost_t) -----------------------------------

def test_settler_cost_enters_cost_t(tmp_path):
    ws = _ws(tmp_path)
    rl.record(ws, kind="task", anchor="C-9",
              signals=[_sig("oracle_verdict", "oracle_runner", "pass")])
    # the settle act's launch stash — no stash, no cost row (fail-loud)
    assert ir.record_launch(ws, "C-9", "settle-act", phi=0.5,
                             action_type="settle") is not None
    res = bss.settle_blind(
        ws, "task/C-9", _verdict(1.0, "evidence/raw-step.bin"),
        input_doc=_input(ws),
        oracle_verdict="pass", has_reproducible_evidence=False,
        claim="C-9", cost_tokens=20_000.0, cost_seconds=3_600.0)
    assert res["settled"] is True, res
    assert res.get("settler_cost"), "the settler's run cost must be booked"
    rows = ir.read_transitions(ws)
    assert rows, "the settler's run must land a transition row"
    row = rows[-1]
    assert row["action_type"] == "settle"
    phi_after = ir.potential(ws)
    expected = ir.incremental_reward(0.5, phi_after, tokens=20_000.0, seconds=3_600.0)
    zero_cost = ir.incremental_reward(0.5, phi_after)
    # cost_t = 20000/10000 + 3600/3600 = 3.0 lands in r_incr
    assert row["r_incr"] == expected
    assert expected == round(zero_cost - 3.0, 6)


def test_settler_cost_without_claim_refused_loudly(tmp_path):
    """A silent cost drop would hide spend — the entry refuses instead."""
    ws = _ws(tmp_path)
    rl.record(ws, kind="task", anchor="C-9",
              signals=[_sig("oracle_verdict", "oracle_runner", "pass")])
    res = bss.settle_blind(
        ws, "task/C-9", _verdict(1.0, "evidence/raw-step.bin"),
        input_doc=_input(ws),
        oracle_verdict="pass", has_reproducible_evidence=False,
        cost_tokens=1_000.0)
    assert res["settled"] is False
    assert res["reason"].startswith("input:")


def test_producer_narrative_never_in_settler_input(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    excluded = ("notes/worker-report.md", "runs/worker-status-w9.md", "runs/W9-verify-note.md",
                "runs/verification-C-9.md", "facts/F001.md", "evidence/verdict.json")
    for rel in excluded:
        with pytest.raises(ValueError, match="excluded"):
            bss.settler_input(ws, claim="C-9", identity="settle-1",
                              artifact_paths=[rel])
    opened = _spy_opens(monkeypatch)
    doc = bss.settler_input(
        ws, claim="C-9", identity="settle-1",
        artifact_paths=["evidence/raw-step.bin"], question="q2",
        rules_path=RULES_PATH)
    blob = json.dumps(doc, sort_keys=True)
    for sentinel in ("POISON_PRODUCER_NARRATIVE", "POISON_WORKER_STATUS",
                     "POISON_VERIFY_NOTE", "POISON_VERIFICATION",
                     "POISON_FACT_CONCLUSION", "POISON_VERDICT"):
        assert sentinel not in blob, sentinel
    assert not any(
        "notes/" in p or "worker-status" in p or "verify-note" in p
        or "verification-" in p or "F001" in p or "verdict.json" in p
        for p in opened), opened
    # the settlement gate re-checks a HAND-BUILT doc too
    smuggled = dict(doc)
    smuggled["artifacts"] = list(doc["artifacts"]) + [
        {"path": "notes/worker-report.md", "sha256": "0" * 64}]
    gate = bss.check_blind_input(smuggled)
    assert gate["ok"] is False
    assert "excluded" in gate["reason"]


# ---------- identity: credit without a named grader does not settle -------

def test_settlement_refuses_missing_identity(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        bss.settler_input(ws, claim="C-9", identity="",
                          artifact_paths=["evidence/raw-step.bin"])
    forged = {"schema": bss.SETTLEMENT_INPUT_SCHEMA, "identity": "   ", "claim": "C-9", "artifacts": []}
    gate = bss.check_blind_input(forged)
    assert gate["ok"] is False
    assert "identity" in gate["reason"]
    rl.record(ws, kind="task", anchor="C-9",
              signals=[_sig("oracle_verdict", "oracle_runner", "pass")])
    res = bss.settle_blind(
        ws, "task/C-9", _verdict(1.0, "evidence/raw-step.bin"),
        input_doc=forged,
        oracle_verdict="pass", has_reproducible_evidence=False)
    assert res["settled"] is False
    assert res["reason"].startswith("input:")


# ---------- review hardening: aliases, escapes, double-billing -----------

def test_gate_refuses_aliased_and_escaping_paths(tmp_path):
    """Case aliases (the dev FS is case-insensitive), dot-dot/dot
    segments, and absolute escapes all land on the same refusal — the
    alias must never route around a denied face, at either door."""
    ws = _ws(tmp_path)
    for rel in ("Runs/Method-Family-Log.Jsonl", "Notes/worker-report.md",
                "runs/../notes/worker-report.md"):
        with pytest.raises(ValueError, match="excluded"):
            bss.settler_input(ws, claim="C-9", identity="settle-1",
                              artifact_paths=[rel])
    # the rules table may live outside the ws, never on a denied face
    with pytest.raises(ValueError, match="excluded"):
        bss.settler_input(ws, claim="C-9", identity="settle-1",
                          artifact_paths=[], rules_path="notes/worker-report.md")
    base = {"schema": bss.SETTLEMENT_INPUT_SCHEMA, "identity": "settle-1",
            "claim": "C-9", "artifacts": []}
    for bad in ("Runs/Method-Family-Log.Jsonl", "runs/../notes/x.md",
                "notes/./n.md", "/etc/hosts", "evidence/../../notes/x.md"):
        doc = dict(base, artifacts=[{"path": bad, "sha256": "0" * 64}])
        assert bss.check_blind_input(doc)["ok"] is False, bad
    rules_doc = dict(base, rules={"path": "notes/worker-report.md",
                                  "sha256": "0" * 64})
    assert bss.check_blind_input(rules_doc)["ok"] is False
    # the legal repo-side rules table still rides through both doors
    ok = bss.settler_input(ws, claim="C-9", identity="settle-1",
                           artifact_paths=[], rules_path=RULES_PATH)
    assert bss.check_blind_input(ok)["ok"] is True


def test_settler_cost_cannot_double_bill(tmp_path):
    """The launch stash is the billing guard: first close consumes it."""
    ws = _ws(tmp_path)
    rl.record(ws, kind="task", anchor="C-9",
              signals=[_sig("oracle_verdict", "oracle_runner", "pass")])
    ir.record_launch(ws, "C-9", "settle-act", phi=0.5,
                     action_type="settle")
    args = dict(input_doc=_input(ws), oracle_verdict="pass",
                has_reproducible_evidence=False, claim="C-9",
                cost_tokens=1_000.0, now="2026-10-15T00:00:00Z")
    v = _verdict(1.0, "evidence/raw-step.bin")
    first = bss.settle_blind(ws, "task/C-9", v, **args)
    assert first["settled"] is True, first
    assert first["settler_cost"]["o"]["status"] == "SUCCESS"
    # the transition rows land in the consolidated experience file
    trans = ws / "runs" / "experience.jsonl"
    bytes_after_first = trans.read_bytes()
    second = bss.settle_blind(ws, "task/C-9", v, **args)
    assert second["settled"] is False  # duplicate settlement
    assert second.get("settler_cost") is None  # stash consumed — no bill
    assert trans.read_bytes() == bytes_after_first
