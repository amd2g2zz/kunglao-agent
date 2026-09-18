# -*- coding: utf-8 -*-
"""TDD RED — issue #237 D2: the B1o drift blocker must not reject the
verifier dispatches that ARE the remediation for UNVERIFIED_EVIDENCE.

The #602 wire-up blocks every parsed-claim dispatch on drift-severe
(plan_drift_detector --auto rc 2) with no agent-based exemption. The #237
field incident: an honest red-team dispatch was rejected too — the gate
deadlocked its own remediation and made self-minting the only exit.

Pass-through condition (minimal, mechanical): the dispatch targets a
verifier-class agent (kunglao-redteam / verdict-scorer) for a PROVEN claim
(the UNVERIFIED_EVIDENCE precondition — a cheap register intersection with
the flagged set, no detector re-run in-process).

Hook-interaction tier (subprocess dispatch_gate runs) -> slow marker.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "hooks"

pytestmark = pytest.mark.slow


def _load_dispatch_gate():
    """Load hooks/dispatch_gate.py as a module (unit-face tests)."""
    spec = importlib.util.spec_from_file_location(
        "_dispatch_gate_for_237_passthrough_test",
        HOOKS_DIR / "dispatch_gate.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_ws(tmp_path: Path) -> Path:
    """Workspace the canonical resolver picks up (claim-register sentinel)."""
    ws = tmp_path / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    return ws


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _write_plan(ws: Path, ids: list[str]) -> None:
    (ws / "global_plan.txt").write_text(
        "plan body mentioning " + " ".join(ids) + "\n", encoding="utf-8")


def _write_hook_state(ws: Path) -> None:
    from _factories import write_hook_state
    write_hook_state(ws, active_hooks=["dispatch_gate"])


def _run_hook(tmp_path: Path, agent: str,
              claim: str = "C-001") -> tuple[int, str, str]:
    """Drive hooks/dispatch_gate.py main() via subprocess."""
    prompt = json.dumps({
        "kunglao_dispatch": {
            "version": 1, "claim": claim, "tier": 1, "tools": [],
            "agent": agent,
        }
    })
    payload = json.dumps({
        "cwd": str(tmp_path),
        "tool_name": "Agent",
        "tool_input": {"prompt": prompt, "subagent_type": agent},
    })
    proc = subprocess.run(
        [sys.executable, str(HOOKS_DIR / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=REPO_ROOT, errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _passthrough_rows(ws: Path) -> list[dict]:
    rows = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for log in sorted(logs.glob("kunglao-*.jsonl")):
        for line in log.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (isinstance(row, dict)
                    and row.get("action") == "drift_verifier_passthrough"):
                rows.append(row)
    return rows


# =========================================================================
# Unit face: _is_verifier_remediation_dispatch
# =========================================================================


class TestVerifierRemediationPredicate:
    def test_predicate_accepts_redteam_proven(self, tmp_path):
        dg = _load_dispatch_gate()
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        payload = {"tool_input": {"subagent_type": "kunglao-redteam"}}
        assert dg._is_verifier_remediation_dispatch(
            ws, "C-001", payload, "") is True

    def test_predicate_rejects_worker_agent(self, tmp_path):
        dg = _load_dispatch_gate()
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        payload = {"tool_input": {"subagent_type": "kunglao-worker"}}
        assert dg._is_verifier_remediation_dispatch(
            ws, "C-001", payload, "") is False

    def test_predicate_rejects_redteam_on_open_claim(self, tmp_path):
        dg = _load_dispatch_gate()
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "OPEN"}])
        payload = {"tool_input": {"subagent_type": "kunglao-redteam"}}
        assert dg._is_verifier_remediation_dispatch(
            ws, "C-001", payload, "") is False

    def test_predicate_rejects_verdict_scorer_on_open_claim(self, tmp_path):
        dg = _load_dispatch_gate()
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "OPEN"}])
        payload = {"tool_input": {"subagent_type": "verdict-scorer"}}
        assert dg._is_verifier_remediation_dispatch(
            ws, "C-001", payload, "") is False

    def test_predicate_accepts_verdict_scorer_proven(self, tmp_path):
        dg = _load_dispatch_gate()
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        payload = {"tool_input": {"subagent_type": "verdict-scorer"}}
        assert dg._is_verifier_remediation_dispatch(
            ws, "C-001", payload, "") is True


# =========================================================================
# Hook-interaction face: main() pass-through vs block
# =========================================================================


class TestVerifierPassthroughWireUp:
    def _drift_ws(self, tmp_path: Path) -> Path:
        """Drift-severe workspace: 3 PROVEN claims, no verify records ->
        3 UNVERIFIED_EVIDENCE -> detector --auto rc 2 (BLOCKED)."""
        ws = _mk_ws(tmp_path)
        ids = ["C-001", "C-002", "C-003"]
        _write_register(ws, [{"id": c, "status": "PROVEN"} for c in ids])
        _write_plan(ws, ids)
        _write_hook_state(ws)
        return ws

    def test_redteam_dispatch_not_blocked(self, tmp_path):
        """RED: drift-severe workspace, red-team dispatch on the flagged
        PROVEN claim -> the gate must NOT return the drift BLOCKED rc."""
        self._drift_ws(tmp_path)
        rc, out, err = _run_hook(tmp_path, "kunglao-redteam")
        assert rc != 2, (
            f"verifier dispatch is the remediation; must not be blocked by "
            f"the drift gate: rc={rc} out={out!r} err={err!r}")

    def test_worker_dispatch_still_blocked(self, tmp_path):
        """Control: same workspace, kunglao-worker dispatch -> BLOCKED (2)."""
        self._drift_ws(tmp_path)
        rc, out, err = _run_hook(tmp_path, "kunglao-worker")
        assert rc == 2, (
            f"non-verifier dispatch must stay drift-blocked: rc={rc} "
            f"out={out!r} err={err!r}")

    def test_redteam_on_open_claim_not_passthrough(self, tmp_path):
        """A verifier dispatch for a non-PROVEN claim is ordinary traffic:
        no drift here, so the gate falls through (rc 0). With drift present
        the block would apply — covered by the worker control."""
        ws = _mk_ws(tmp_path)
        ids = ["C-001"]
        _write_register(ws, [{"id": c, "status": "OPEN"} for c in ids])
        _write_plan(ws, ids)
        _write_hook_state(ws)
        rc, out, err = _run_hook(tmp_path, "kunglao-redteam")
        assert rc == 0, (
            f"no drift, no pass-through needed: rc={rc} out={out!r} "
            f"err={err!r}")

    def test_passthrough_leaves_trace_row(self, tmp_path):
        """The pass-through must be observable in the unified log."""
        ws = self._drift_ws(tmp_path)
        _run_hook(tmp_path, "kunglao-redteam")
        rows = _passthrough_rows(ws)
        assert rows and rows[-1].get("claim") == "C-001", (
            f"drift_verifier_passthrough trace row missing: {rows!r}")


# =========================================================================
# H1 loop: dispatch -> pass-through -> REAL #461 emitter -> corroboration
# =========================================================================


class TestCorroborationLoop:
    """The full honest path must actually land: a subagent_type-shaped
    verifier dispatch (the native Agent tool shape — no `name` key) passes
    BOTH drift faces, the REAL #461 emitter records `agent=kunglao-redteam`
    (the marker plan_drift_detector's D3 corroboration matches), and the
    drift clears for the dispatched claim. H1: the row used to record
    `agent=?` for this shape, so corroboration never landed and the
    deadlock survived the pass-through."""

    def _loop_ws(self, tmp_path: Path) -> Path:
        ws = _mk_ws(tmp_path)
        ids = ["C-001", "C-002", "C-003"]
        _write_register(ws, [{"id": c, "status": "PROVEN"} for c in ids])
        _write_plan(ws, ids)
        _write_hook_state(ws)
        (ws / "runs").mkdir(exist_ok=True)
        (ws / "runs" / "plan-C001-verify.md").write_text(
            "goal: adversarial verification of C-001\nsteps:\nfallback:\n",
            encoding="utf-8")
        return ws

    @staticmethod
    def _pre_check_payload() -> dict:
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
                  '"tier": 1, "tools": ["Read"], '
                  '"agent": "kunglao-redteam"}}\n'
                  'facts-snapshot: 1 facts')
        # H1 shape: subagent_type only, NO `name` key in tool_input
        return {"tool_input": {"prompt": prompt,
                               "subagent_type": "kunglao-redteam"}}

    def test_loop_corroboration_lands(self, tmp_path, capsys):
        from worker_budget_sinks import pre_check
        import plan_drift_detector as pdd

        ws = self._loop_ws(tmp_path)

        # 1. D2 pass-through face (dispatch_gate subprocess, subagent_type)
        rc, out, err = _run_hook(tmp_path, "kunglao-redteam")
        assert rc != 2, f"pass-through failed: rc={rc} {err!r}"

        # 2. the REAL emitter: worker_budget pre_check approval path — the
        #    same drift workspace, drift gate passed for the verifier
        rc2 = pre_check(self._pre_check_payload(), {
            "workspace": str(ws),
            "state": ws / "analysis_state.txt",
            "register": ws / "claim-register.yaml",
            "deps": ws / "claim_deps.yaml",
            "task_spec": ws / "task_spec.yaml",
        })
        captured = capsys.readouterr()
        assert rc2 == 0, (
            f"pre_check must approve the verifier remediation (drift gate "
            f"pass-through), got rc={rc2}: {captured.err!r}")

        # 3. the #461 row landed and names the verifier
        logs = ws / "runs" / "logs"
        row_texts = []
        for log in sorted(logs.glob("kunglao-*.jsonl")):
            row_texts += log.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
        dispatch_rows = [json.loads(ln) for ln in row_texts
                         if ln.strip() and "dispatch" in ln
                         and json.loads(ln).get("claim") == "C-001"]
        assert dispatch_rows, f"no #461 dispatch row for C-001: {row_texts!r}"
        assert any("kunglao-redteam" in str(r.get("detail"))
                   and str(r.get("actor", "")).startswith("hook:")
                   for r in dispatch_rows), dispatch_rows

        # 4. the verifier's write contract: the record lands after the
        #    dispatch -> corroboration lands and the drift clears for C-001
        (ws / "runs" / "verify-redteam-C-001.md").write_text(
            "RED-TEAM VERDICT: CONFIRMED\n\nindependent check body\n",
            encoding="utf-8")
        verified = pdd.corroborated_verified_ids(ws)
        assert verified == {"C-001"}, (
            f"corroboration must land for the dispatched claim: {verified!r}")
        rc3 = pdd.check(ws, active_only=True)
        out3 = capsys.readouterr().out
        assert rc3 == 1, out3  # 2 remaining drifts (C-002, C-003)
        assert "C-001 is PROVEN but" not in out3, out3

    def test_worker_dispatch_rejected_at_pre_check_drift_gate(self, tmp_path,
                                                              capsys):
        """Control: the same drift workspace, a worker-shaped dispatch is
        still rejected by worker_budget's own drift gate."""
        from worker_budget_sinks import pre_check

        ws = self._loop_ws(tmp_path)
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
                  '"tier": 1, "tools": ["Read"], '
                  '"agent": "kunglao-worker"}}\n'
                  'facts-snapshot: 1 facts')
        payload = {"tool_input": {"name": "kunglao-worker", "prompt": prompt}}
        rc = pre_check(payload, {
            "workspace": str(ws),
            "state": ws / "analysis_state.txt",
            "register": ws / "claim-register.yaml",
            "deps": ws / "claim_deps.yaml",
            "task_spec": ws / "task_spec.yaml",
        })
        captured = capsys.readouterr()
        assert rc == 2, f"worker dispatch must stay drift-blocked: {captured.err!r}"
        assert "REJECT drift" in captured.err
