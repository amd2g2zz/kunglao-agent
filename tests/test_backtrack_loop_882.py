#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_backtrack_loop_882.py — #882 回溯环宿主与座舱 (three touchpoints,
four outputs, cockpit trio).

Sections (TDD order):
  1. micro-retro (touchpoint 1, dispatch face): the settlement index records
     settlements per (scene, operation); micro_lessons / micro_lessons_context
     return the K most recent same-key settlements; dispatch_gate injects the
     前车之鉴 block as additionalContext on the ALLOW path (zero lessons ->
     zero output, #754).
  2. settlement retro (touchpoint 2, register_proven_gate face): every
     terminal transition writes runs/<ts>-retro-<claim>.md (trace subgraph
     replay) and bumps the backlog lag; PROVEN-without-PQ-movement is
     flagged (fake-success early exposure).
  3. policy retro (touchpoint 3, heartbeat_tick face): gated by every-N-
     settlements / mission stall / plan_review ritual; the agenda carries
     data items (window metrics, drift report, DECIDE output, PROPOSAL
     lines); kunglao-decide is invoked (revive); hypothesis seeds are filed
     idempotently; lag resets.
  4. cockpit trio: cockpit_summary + statusline snapshot carry
     {backtrack_lag, unattributed_rate, pending_proposals}; the two #883
     slots go live with thresholds + budgets.

Constitutional isolation invariant pinned here: NO code path executes a
replan (plan_reviser --apply / plan_stages.review are never called; the
retro only files proposals for the orchestrator).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import backtrack_loop as bl  # noqa: E402
import kunglao_log  # noqa: E402
from _factories import write_hook_state


# ---------------------------------------------------------------- helpers --

def _ws(tmp: Path) -> Path:
    """Minimal workspace with two claims sharing one (scene, operation) key."""
    ws = tmp / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    operation: aes,decrypt\n"
        "    promotion_attempts: 0\n"
        "  - id: C-002\n"
        "    status: OPEN\n"
        "    operation: aes,decrypt\n"
        "    promotion_attempts: 0\n",
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "mission: retro-test\nplatform: windows-x64\n",
        encoding="utf-8")
    return ws


def _mission_ledger(ws: Path, *, history=None, pqs=None) -> None:
    pqs = pqs if pqs is not None else [{"id": "pq-1", "state": "unattempted"}]
    data = {"mission": {"pqs": pqs, "history": history or []}}
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml_dump(data), encoding="utf-8")


def yaml_dump(data: dict) -> str:
    import yaml
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _reg_text(ws: Path) -> str:
    return (ws / "claim-register.yaml").read_text(encoding="utf-8")


def _settle(ws: Path, cid: str, frm: str, to: str, **kw) -> None:
    """Drive the real settlement face (register_proven_gate.emit_settlements)
    the way write_guard does — the #882 hooks hang inside it. The register on
    disk is the PRE-transition image (old_text); the post-image is derived by
    flipping ONLY the target claim's status line frm -> to (emit_settlements
    itself never writes the register — the Claude Write already passed the
    gate in the real flow)."""
    from register_proven_gate import emit_settlements
    lines = _reg_text(ws).splitlines(keepends=True)
    out, seen = [], False
    for ln in lines:
        if f"id: {cid}\n" in ln:
            seen = True
        elif seen and ln.startswith("    status:"):
            ln = ln.replace(f"status: {frm}", f"status: {to}")
            seen = False
        out.append(ln)
    new = "".join(out)
    n = emit_settlements(ws, new, _reg_text(ws))
    assert n == 1, f"expected exactly one settlement row, got {n}"


# ==========================================================================
# 1. micro-retro (dispatch face)
# ==========================================================================

class TestMicroRetro:
    def test_same_key_hit(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        bl.record_settlement(ws, "C-001", "REFUTED",
                             tools=["frida"], outcome="REFUTED")
        hits = bl.micro_lessons(ws, "C-002")
        assert len(hits) == 1
        assert hits[0]["claim"] == "C-001"
        assert hits[0]["outcome"] == "REFUTED"

    def test_other_operation_miss(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        # relabel C-002 to a different operation: settlements at C-002's key
        # must not surface when asking from C-001's key
        text = _reg_text(ws).replace(
            "  - id: C-002\n    status: OPEN\n    operation: aes,decrypt\n",
            "  - id: C-002\n    status: OPEN\n    operation: hook,trace\n")
        (ws / "claim-register.yaml").write_text(text, encoding="utf-8")
        bl.record_settlement(ws, "C-002", "REFUTED", outcome="REFUTED")
        assert bl.micro_lessons(ws, "C-001") == []

    def test_unlabeled_claims_share_key(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n"
            "  - id: C-001\n"
            "    status: REFUTED\n"
            "  - id: C-002\n"
            "    status: OPEN\n",
            encoding="utf-8")
        bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        hits = bl.micro_lessons(ws, "C-002")
        assert len(hits) == 1 and hits[0]["claim"] == "C-001"

    def test_index_rolls_at_k(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        for i in range(bl.MICRO_K + 2):
            bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        assert len(bl.micro_lessons(ws, "C-002")) == bl.MICRO_K

    def test_context_block_shape(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        bl.record_settlement(ws, "C-001", "REFUTED",
                             tools=["frida", "hook"], outcome="REFUTED")
        ctx = bl.micro_lessons_context(ws, "C-002")
        assert ctx is not None
        assert "前车之鉴" in ctx
        assert "C-001" in ctx and "REFUTED" in ctx and "frida" in ctx

    def test_no_lessons_no_block(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        assert bl.micro_lessons_context(ws, "C-002") is None

    def _gate_ws(self, root: Path) -> Path:
        """Workspace the gate can DISCOVER: cwd -> <layout.workspace_dir>
        (env_manifest DEFAULT_LAYOUT = malware-analysis-workspace, the #772
        test shape). C-001 already carries a REFUTED settlement's register
        state at the same (scene, operation) as the dispatched C-002."""
        ws = root / "malware-analysis-workspace"
        ws.mkdir()
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n"
            "  - id: C-001\n"
            "    status: REFUTED\n"
            "    operation: aes,decrypt\n"
            "  - id: C-002\n"
            "    status: OPEN\n"
            "    operation: aes,decrypt\n",
            encoding="utf-8")
        (ws / "task_spec.yaml").write_text(
            "mission: retro-test\nplatform: windows-x64\n", encoding="utf-8")
        return ws

    def _run_gate(self, root: Path, ws: Path) -> subprocess.CompletedProcess:
        expires = (datetime.now(timezone.utc)
                   + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        write_hook_state(ws, active_hooks=["dispatch_gate"],
                         paused_hooks=None, expires_at=expires)
        payload = json.dumps({
            "cwd": str(root), "workspace": str(ws),
            "tool_input": {"prompt":
                           "[T1 tools=Read,Write,Grep] claim C-002 "
                           "analyze hook tracing"},
        })
        import os
        env = dict(os.environ, PYTHONUTF8="1")  # the harness pipes UTF-8
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
            input=payload, capture_output=True, text=True, timeout=120,
            cwd=str(REPO_ROOT), encoding="utf-8", errors="replace", env=env)

    def test_dispatch_gate_injects_block(self, tmp_path: Path) -> None:
        """Touchpoint 1 proof: a real dispatch_gate run on the ALLOW path
        carries the 前车之鉴 block as additionalContext (rc stays 0)."""
        root = tmp_path
        ws = self._gate_ws(root)
        bl.record_settlement(ws, "C-001", "REFUTED",
                             tools=["frida"], outcome="REFUTED")
        r = self._run_gate(root, ws)
        assert r.returncode == 0, r.stderr[-400:]
        assert "前车之鉴" in r.stdout, r.stdout[:400]
        assert "C-001" in r.stdout

    def test_dispatch_gate_silent_without_lessons(self, tmp_path: Path) -> None:
        """Zero-noise (#754): no same-key settlements -> no additionalContext."""
        root = tmp_path
        ws = self._gate_ws(root)
        r = self._run_gate(root, ws)
        assert r.returncode == 0, r.stderr[-400:]
        assert "前车之鉴" not in r.stdout


# ==========================================================================
# 2. settlement retro (register_proven_gate face)
# ==========================================================================

class TestSettlementRetro:
    def test_settlement_writes_retro_report(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "hook:write_guard", "dispatch", claim="C-001",
                         detail="tools=frida,hook")
        _settle(ws, "C-001", "OPEN", "PROVEN")
        reports = sorted((ws / "runs").glob("*-retro-C-001.md"))
        assert reports, "settlement must write runs/<ts>-retro-<claim>.md"
        body = reports[-1].read_text(encoding="utf-8")
        assert "C-001" in body and "OPEN" in body and "PROVEN" in body
        rows = kunglao_log.tail(ws, 100)
        assert any(r.get("action") == "retro_report" for r in rows)

    def test_fake_success_flagged(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        text = _reg_text(ws).replace(
            "    status: OPEN\n    operation: aes,decrypt\n",
            "    status: OPEN\n    operation: aes,decrypt\n"
            "    answers_question: pq-1\n")
        (ws / "claim-register.yaml").write_text(text, encoding="utf-8")
        _mission_ledger(ws)  # pq-1 unattempted
        _settle(ws, "C-001", "OPEN", "PROVEN")
        body = sorted((ws / "runs").glob("*-retro-C-001.md"))[-1] \
            .read_text(encoding="utf-8")
        assert "FAKE-SUCCESS" in body
        assert "pq-1" in body

    def test_proven_with_answered_pq_not_flagged(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        text = _reg_text(ws).replace(
            "    status: OPEN\n    operation: aes,decrypt\n",
            "    status: OPEN\n    operation: aes,decrypt\n"
            "    answers_question: pq-1\n")
        (ws / "claim-register.yaml").write_text(text, encoding="utf-8")
        _mission_ledger(ws, pqs=[{"id": "pq-1", "state": "answered"}])
        _settle(ws, "C-001", "OPEN", "PROVEN")
        body = sorted((ws / "runs").glob("*-retro-C-001.md"))[-1] \
            .read_text(encoding="utf-8")
        assert "- fake_success: none" in body

    def test_no_answers_question_flagged(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _settle(ws, "C-001", "OPEN", "PROVEN")
        body = sorted((ws / "runs").glob("*-retro-C-001.md"))[-1] \
            .read_text(encoding="utf-8")
        assert "FAKE-SUCCESS" in body and "answers_question" in body

    def test_lag_and_index_updated_by_settlement_face(self, tmp_path: Path) \
            -> None:
        ws = _ws(tmp_path)
        assert bl.lag(ws) == 0
        _settle(ws, "C-001", "OPEN", "REFUTED")
        assert bl.lag(ws) == 1
        hits = bl.micro_lessons(ws, "C-002")
        assert len(hits) == 1 and hits[0]["claim"] == "C-001"


# ==========================================================================
# 3. policy retro (heartbeat_tick face)
# ==========================================================================

class TestPolicyGate:
    def test_not_due_when_fresh(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        due = bl.policy_due(ws)
        assert due["due"] is False and due["why"] == []

    def test_due_on_n_settlements(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        for _ in range(bl.POLICY_EVERY_N_SETTLEMENTS):
            bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        due = bl.policy_due(ws)
        assert due["due"] is True
        assert any("settlements" in w for w in due["why"])

    def test_due_on_stall_fingerprint(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        _mission_ledger(ws, history=[
            {"ts": "2026-09-01T00:00:00Z", "v_m": 1.5},
            {"ts": "2026-09-01T00:05:00Z", "v_m": 1.5},
            {"ts": "2026-09-01T00:10:00Z", "v_m": 1.5},
            {"ts": "2026-09-01T00:15:00Z", "v_m": 1.5},
        ])
        due = bl.policy_due(ws)
        assert due["due"] is True
        assert any("stall" in w for w in due["why"])

    def test_due_on_review_ritual(self, tmp_path: Path) -> None:
        ws = _ws(tmp_path)
        (ws / "runs" / "plan-stages.yaml").write_text(yaml_dump(
            {"stages": [
                {"id": "S1", "name": "n", "goal": "g", "claims": ["C-001"],
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "active"},
                {"id": "S2", "name": "n", "goal": "g", "claims": ["C-002"],
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "pending"}]}), encoding="utf-8")
        due = bl.policy_due(ws)
        assert due["due"] is True
        assert any("review" in w for w in due["why"])


class TestPolicyRetro:
    def _ws_with_repeats(self, tmp_path: Path) -> Path:
        ws = _ws(tmp_path)
        _mission_ledger(ws, history=[
            {"ts": "2026-09-01T00:00:00Z", "v_m": 0.0},
            {"ts": "2026-09-01T01:00:00Z", "v_m": 1.0},
        ])
        # two negative settlements at the same (scene, operation) via the
        # REAL settlement face (ledger rows + index + lag, pre-#882 faces)
        _settle(ws, "C-001", "OPEN", "REFUTED")
        _settle(ws, "C-001", "OPEN", "REFUTED")
        return ws

    def test_agenda_written_with_data_items(self, tmp_path: Path) -> None:
        ws = self._ws_with_repeats(tmp_path)
        # deterministic reviser proposal: cost advisory signal file
        (ws / "runs" / "cost_advice.json").write_text(
            json.dumps({"tier": "advisory", "count": 9}), encoding="utf-8")
        out = bl.run_policy_retro(ws)
        agendas = sorted((ws / "runs").glob("retro-agenda-*.md"))
        assert agendas and agendas[-1] == Path(out["agenda"])
        body = agendas[-1].read_text(encoding="utf-8")
        # data items: window metrics + decide output + proposals
        assert "repeat_rate" in body
        assert "DECIDE" in body          # kunglao-decide was invoked
        assert "PROPOSAL" in body        # reviser proposal on the agenda
        assert "cost" in body.lower()
        assert "v_m" in body             # ΔV_m/claim computable
        rows = kunglao_log.tail(ws, 100)
        assert any(r.get("action") == "retro_policy" for r in rows)

    def test_lag_resets_after_retro(self, tmp_path: Path) -> None:
        ws = self._ws_with_repeats(tmp_path)
        bl.run_policy_retro(ws)
        assert bl.lag(ws) == 0

    def test_hypothesis_seed_idempotent(self, tmp_path: Path) -> None:
        ws = self._ws_with_repeats(tmp_path)
        bl.run_policy_retro(ws)
        seeds = list((ws / "hypotheses").glob("H-*.md"))
        assert seeds, "repeated failure signature must seed a hypothesis"
        bl.run_policy_retro(ws)
        seeds2 = list((ws / "hypotheses").glob("H-*.md"))
        assert len(seeds2) == len(seeds), "seed must be idempotent"
        body = seeds2[0].read_text(encoding="utf-8")
        assert "retro:" in body  # the idempotency marker

    def test_proposals_never_executed(self, tmp_path: Path) -> None:
        """Constitutional isolation: the retro files proposals but NEVER
        applies them (no plan revision segment, no stage review commit)."""
        ws = self._ws_with_repeats(tmp_path)
        (ws / "runs" / "cost_advice.json").write_text(
            json.dumps({"tier": "advisory", "count": 9}), encoding="utf-8")
        (ws / "runs" / "plan-stages.yaml").write_text(yaml_dump(
            {"stages": [
                {"id": "S1", "name": "n", "goal": "g", "claims": ["C-001"],
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "active"},
                {"id": "S2", "name": "n", "goal": "g", "claims": ["C-002"],
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "pending"}]}), encoding="utf-8")
        bl.run_policy_retro(ws)
        assert not list((ws / "runs").glob("plan-review-*.md")), \
            "plan_review verdict docs are orchestrator-only"
        plan = ws / "runs" / "plan-c001.md"
        if plan.exists():
            assert "revision-" not in plan.read_text(encoding="utf-8")

    def test_pending_proposals_lifecycle(self, tmp_path: Path) -> None:
        ws = self._ws_with_repeats(tmp_path)
        bl.run_policy_retro(ws)
        assert bl.pending_proposals(ws) >= 1
        # the orchestrator runs the review ritual -> plan_review row lands
        kunglao_log.emit(ws, "orchestrator", "plan_review",
                         detail=json.dumps({"verdict": "adjust"}))
        assert bl.pending_proposals(ws) == 0

    def test_tick_carries_backtrack_face(self, tmp_path: Path) -> None:
        """Touchpoint 3 proof: real heartbeat_tick runs the policy gate
        (advisory) and the tick report records it."""
        ws = _ws(tmp_path)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "heartbeat_tick.py"), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        report = json.loads((ws / "runs" / ".heartbeat-tick.json")
                            .read_text(encoding="utf-8"))
        assert "backtrack" in report, (
            f"tick must record the backtrack step; rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")


# ==========================================================================
# 4. cockpit trio + statusline slots
# ==========================================================================

class TestCockpitTrio:
    def test_cockpit_summary_backtrack(self, tmp_path: Path) -> None:
        from tuition_curve import cockpit_summary
        ws = _ws(tmp_path)
        _mission_ledger(ws)  # cockpit_summary requires the ledger (pre-#873 shape)
        bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        cs = cockpit_summary(ws)
        assert set(cs["backtrack"]) == {
            "backtrack_lag", "unattributed_rate", "pending_proposals"}
        assert cs["backtrack"]["backtrack_lag"] == 1

    def test_snapshot_backtrack_section(self, tmp_path: Path) -> None:
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        snap = sls.build_snapshot(ws)
        assert set(snap["backtrack"]) == {
            "backtrack_lag", "unattributed_rate", "pending_proposals"}
        assert snap["backtrack"]["backtrack_lag"] == 1

    def test_slots_go_live_with_budgets(self) -> None:
        import statusline_snapshot as sls
        by_id = {p["id"]: p for p in sls.PROBES}
        for pid in ("unattributed_rate", "backtrack_lag"):
            p = by_id[pid]
            assert p["enabled"] is True, pid
            assert p["probe"], pid
            assert p["staleness_budget"], f"{pid} without budget"
        # the third field is not a probe — it lives in the backtrack section
        assert "pending_proposals" not in by_id

    def test_probe_unattributed_rate_faults(self, tmp_path: Path) -> None:
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "heartbeat_tick", "converge")  # no trace_id
        entry = {"id": "unattributed_rate", "dimension": "moving",
                 "threshold": sls.UNATTRIBUTED_RATE_WARN,
                 "severity": "WARN", "short_code": "[stall]"}
        d = sls.probe_unattributed_rate(ws, entry)
        assert d["ok"] is False

    def test_probe_backtrack_lag_faults(self, tmp_path: Path) -> None:
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        for _ in range(sls.BACKTRACK_LAG_WARN + 1):
            bl.record_settlement(ws, "C-001", "REFUTED", outcome="REFUTED")
        entry = {"id": "backtrack_lag", "dimension": "moving",
                 "threshold": sls.BACKTRACK_LAG_WARN,
                 "severity": "WARN", "short_code": "[stall]"}
        d = sls.probe_backtrack_lag(ws, entry)
        assert d["ok"] is False

    def test_event_words_registered(self) -> None:
        import event_taxonomy as et
        words = et.EMIT_ACTIONS
        assert words == sorted(words) and len(words) == len(set(words))
        assert "retro_policy" in words and "retro_report" in words
