#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_top1_reject_603.py — #603: a top-1 REJECT must be durable.

Pre-#603, `_top1_enforcement`'s REJECT face (rank >= 2 dispatched with no
`agent-reasoning:` prefix) emitted ONLY a stderr/stdout trace
(`_emit_trace(top1_reject)` + `_reject_with_guidance`). Nothing durable
landed on disk that a post-mortem could count — an orchestrator looping
on the same REJECT accumulated silently.

ADJUDICATION (v0.1.3 adversarial review, final): REJECT is a PRE-DISPATCH
event. Worker attribution at this point is structurally unreliable — the
time-fallback key (`w<epoch>`) never accumulates, and agent-name
attribution would trip the #604 breaker and punish COMPLIANT dispatches
(that same worker's next, fully reasoned dispatch would be blocked). So:

  KEEP    one row per REJECT appended to <ws>/runs/gate-rejections.jsonl
          (ts / gate / claim / msg / exit_code; row shape mirrors
          scripts/gate_telemetry.py's append-only JSONL);
  REMOVE  any worker_budget.record_retry call from the REJECT path — the
          #604 runs/.retry-counter.yaml is the ORCHESTRATOR's
          silent-failure counter and must stay semantically clean
          (test_reject_never_writes_retry_counter is the regression
          guard against re-contamination);
  ADD     a minimal consumer: scripts/kunglao_resume.py (the read-only
          crash-recovery brief) renders a gate-rejections summary (count
          + last N rejections) from the SAME JSONL — fail-open, a
          missing file means the section is simply absent.

Fail-open discipline is unchanged: if the ledger append cannot run, the
REJECT itself still fires — a broken bookkeeping side effect must never
turn a deviation into a silent pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))

# Exact same fixture shape as tests/test_decision_teeth.py::_top1_ws —
# the authority rank is C-1 > C-2 > C-3, so dispatching C-3 with no
# `agent-reasoning:` hits the REJECT face deterministically.


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _top1_ws(root: Path) -> Path:
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-2", "status": "OPEN", "statement": "background work",
         "answers_question": "PQ-1"},
        {"id": "C-1", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1"},
        {"id": "C-3", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1", "evidence_tier_attempted": 1},
    ]})
    _write(ws / "claim_deps.yaml", {
        "depends_on": {}, "competitor_groups": {"g1": ["C-1", "C-3"]}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    (ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate"],
        "paused_hooks": [],
        "expires_at": "2099-12-31T23:59:59Z",
    }), encoding="utf-8")
    return ws


def _run_gate(root: Path, ws: Path, prompt: str,
              agent_name: str | None = None) -> subprocess.CompletedProcess:
    """agent_name rides the v1 dispatch payload's `agent` field — the
    structural protocol slot for the dispatched specialist (kunglao_dispatch
    {..., "agent": "ghidra-light"}). Used here to prove that EVEN A NAMED
    worker's REJECT never lands in the #604 counter (adjudication: agent-
    name attribution would punish compliant dispatches)."""
    script = REPO_ROOT / "hooks" / "dispatch_gate.py"
    if agent_name:
        tool_input: dict = {
            "prompt": json.dumps({
                "kunglao_dispatch": {
                    "version": 1, "claim": "C-3", "tier": 2,
                    "tools": ["grep"], "agent": agent_name,
                },
            }),
        }
    else:
        tool_input = {"prompt": prompt}
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": tool_input,
    })
    return subprocess.run(
        [sys.executable, str(script)],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )


def _rejection_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "gate-rejections.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()]


# ---------- ① the REJECT face lands in runs/gate-rejections.jsonl -----

class TestGateRejectionsLedger:
    def test_reject_appends_one_ledger_row(self, tmp_path) -> None:
        """#603 AC-a: a top-1 REJECT (rc=2) MUST append exactly one row to
        runs/gate-rejections.jsonl identifying gate=top1, the claim, and the
        authority msg — pre-#603 the file is never created on this path."""
        root = tmp_path / "r1"
        ws = _top1_ws(root)
        r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep")
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        rows = _rejection_rows(ws)
        assert len(rows) == 1, (
            f"one ledger row per REJECT; got {len(rows)} rows={rows!r}")
        row = rows[0]
        assert row.get("gate") == "top1"
        assert row.get("claim") == "C-3"
        assert row.get("exit_code") == 2
        assert "C-1" in str(row.get("msg", "")), (
            "row must carry the authority msg naming the rank-1 claim")

    def test_pass_and_excused_paths_never_touch_the_ledger(self, tmp_path) -> None:
        """Guard: only the REJECT face writes the ledger — a rank-1 dispatch
        and an `agent-reasoning:`-excused deviation stay silent (narrow
        tooth, #496 parity)."""
        root = tmp_path / "r2"
        ws = _top1_ws(root)
        r0 = _run_gate(root, ws, "[T1 tools=grep] claim C-1 background work")
        assert r0.returncode == 0, f"stderr={r0.stderr!r}"
        r1 = _run_gate(root, ws,
                       "[T1 tools=grep] claim C-2 background work\n"
                       "agent-reasoning: C-1 blocked on VM lease")
        assert r1.returncode == 0, f"stderr={r1.stderr!r}"
        assert _rejection_rows(ws) == [], (
            "pass / excused-deviation paths must not write the ledger")

    def test_ledger_is_append_only_across_repeated_rejects(self, tmp_path) -> None:
        """Two REJECTs = two rows (append-only, one row per event) — the
        ledger is the replay source for post-mortem, overwriting would hide
        the loop the issue is about."""
        root = tmp_path / "r3"
        ws = _top1_ws(root)
        for _ in range(2):
            r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep")
            assert r.returncode == 2
        rows = _rejection_rows(ws)
        assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
        assert [row["claim"] for row in rows] == ["C-3", "C-3"]


# ---------- ② semantic firewall: REJECT never touches the #604 counter -

class TestRetryCounterFirewall:
    def test_reject_never_writes_retry_counter(self, tmp_path) -> None:
        """ADJUDICATION AC-b (regression guard): a REJECT is PRE-DISPATCH —
        the #604 runs/.retry-counter.yaml counts the ORCHESTRATOR's
        silent-failure RE-DISPATCHES. Wiring REJECT into it (the WIP this
        replaces) contaminates the semantics: the time-fallback key never
        accumulates, and agent-name attribution would trip the breaker on
        the worker's NEXT, fully compliant dispatch. A REJECT must leave
        the counter file absent — not even created empty."""
        root = tmp_path / "r4"
        ws = _top1_ws(root)
        r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep",
                      agent_name="kunglao-worker-01")
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        counter = ws / "runs" / ".retry-counter.yaml"
        assert not counter.exists(), (
            "REJECT must not create or write runs/.retry-counter.yaml "
            "(#604 semantic contamination)")
        sys.path.insert(0, str(REPO_ROOT / "hooks"))
        from worker_budget import read_retry_counter
        assert read_retry_counter(str(ws)) == {}

    def test_repeated_rejects_still_never_touch_counter(self, tmp_path) -> None:
        """The firewall holds across a REJECT LOOP — the loop the issue is
        about is made durable by the LEDGER, never by the retry counter."""
        root = tmp_path / "r5"
        ws = _top1_ws(root)
        for _ in range(3):
            r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep",
                          agent_name="kunglao-worker-01")
            assert r.returncode == 2
        assert len(_rejection_rows(ws)) == 3, (
            "the ledger — not the counter — is the durable record of the loop")
        assert not (ws / "runs" / ".retry-counter.yaml").exists(), (
            "3 REJECTs must still leave the #604 counter untouched")
        sys.path.insert(0, str(REPO_ROOT / "hooks"))
        from worker_budget import check_max_retries
        ok, _msg = check_max_retries(str(ws), "kunglao-worker-01", "C-3")
        assert ok, (
            "#604 breaker must NOT fire on gate REJECTs — it tracks "
            "silent-failure re-dispatches only")

    def test_excused_deviation_does_not_touch_counter(self, tmp_path) -> None:
        """Guard: no path of _top1_enforcement touches the counter."""
        root = tmp_path / "r6"
        ws = _top1_ws(root)
        prompt = ("[T1 tools=grep] claim C-2 background work\n"
                  "agent-reasoning: C-1 needs the VM lease which is not up")
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        assert not (ws / "runs" / ".retry-counter.yaml").exists()


# ---------- ③ the ledger is not write-only: resume consumes it --------

# Minimal armed workspace (same shape as test_resume_hypotheses_528) —
# resume is read-only, so seeding the ledger directly (no gate run needed)
# is the honest fixture: the consumer contract is about the FILE.
def _armed_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n", encoding="utf-8")
    (ws / "runs").mkdir(exist_ok=True)
    (ws / ".convergence_ledger.jsonl").write_text(
        json.dumps({"ts": "2026-08-20T00:00:00Z", "decision": "DISPATCH",
                    "open_count": 1, "open_ids": ["C-1"],
                    "partial_count": 0, "active_workers": 0,
                    "blockers": [], "facts_total": 0}) + "\n",
        encoding="utf-8")
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "last_tick_ts": "2099-08-20T00:05:00Z",
        "activity_ts": "2099-08-20T00:05:00Z"}), encoding="utf-8")
    (ws / ".hook_state.json").write_text(json.dumps({
        "expires_at": "2099-01-01T00:00:00Z", "active_hooks": []}),
        encoding="utf-8")
    return ws


def _seed_rejections(ws: Path, n: int) -> None:
    with open(ws / "runs" / "gate-rejections.jsonl", "a",
              encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({
                "ts": f"2026-08-20T00:0{i}:00Z", "gate": "top1",
                "claim": f"C-{i + 1}", "msg": f"C-0 outranks C-{i + 1}",
                "exit_code": 2}) + "\n")


class TestResumeConsumer:
    def test_resume_renders_rejection_summary_when_file_exists(
            self, tmp_path) -> None:
        """ADJUDICATION AC-c: kunglao_resume (the read-only crash-recovery
        brief) surfaces the gate-rejections ledger — count + the most
        recent rejections — so a crashed loop's REJECT history is on the
        recovery surface instead of a write-only file."""
        import kunglao_resume as kr
        ws = _armed_ws(tmp_path)
        _seed_rejections(ws, 5)
        text = kr.render_text(kr.build_brief(ws))
        assert "gate-rejections" in text, (
            "resume brief must carry a gate-rejections section when "
            "runs/gate-rejections.jsonl exists")
        assert "total: 5" in text, "the section must state the rejection count"
        assert "C-5" in text, "the most recent rejection must be rendered"

    def test_resume_omits_section_when_ledger_absent(
            self, tmp_path) -> None:
        """Fail-open: a workspace with no rejections (or pre-#603) renders
        the same brief as before — no empty section, no crash."""
        import kunglao_resume as kr
        ws = _armed_ws(tmp_path)
        text = kr.render_text(kr.build_brief(ws))
        assert "gate-rejections" not in text

    def test_resume_renders_only_last_n(self, tmp_path) -> None:
        """The section shows the LAST N rejections (bounded brief), not the
        whole file — the ledger is the replay source, the brief is a
        summary."""
        import kunglao_resume as kr
        ws = _armed_ws(tmp_path)
        _seed_rejections(ws, 8)
        text = kr.render_text(kr.build_brief(ws))
        assert "C-8" in text
        assert "C-1\n" not in text and "C-2\n" not in text, (
            "older rejections beyond the last-N window must not render")
