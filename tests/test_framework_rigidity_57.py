# -*- coding: utf-8 -*-
"""Issue #57 — framework rigidity: five discipline gates (plan §W5-#57).

Owner ruling (design anchor, not relitigated here): framework-layer protocol
integrity (plan written by the worker / status sync / verifier dispatch /
scheduler alive / orchestrator not overreaching) is NEVER relaxed — violations
REJECT with no opt-out; strategy-layer choices stay with the agent. Every
REJECT carries a CONCRETE repair path (exact command/file/action), and a
REJECT is always "protocol not honored", never "method is bad".

The five gates and their existing machinery:

  g1 scheduler-alive    hooks/worker_budget_sinks.check_heartbeat_alive —
                        ALREADY wired into pre_check (v1.9.28, #754
                        continuity). This file pins the wiring (no duplicate
                        gate) and the REJECT repair-path format (concrete
                        start command), it does NOT add detection.
  g2 orchestrator-      hooks/orchestrator_tool_guard.py — MCP host-channel
    overreach           face already REJECTs; this file pins the posture
                        upgrade of the Bash face (WARN -> REJECT per the
                        ruling), the wrapper-unwrap fix (sh -c 'jadx ...'
                        used to bypass the command-position match) and the
                        mcp__ida__* namespace addition.
  g3 plan-author        hooks/worker_budget_gates.check_worker_plan —
                        verified FILE EXISTENCE only (#239/#294); the
                        comment near the top admitted "orchestrator wrote it
                        pre-dispatch". Upgraded: when a per-dispatch anchor
                        (nonce) exists for the claim — the dispatch-context
                        corridor's dispatch_ts — the on-disk plan must carry
                        worker-session evidence created AFTER dispatch (cite
                        the anchor ts, or carry a `dispatch-anchor:` line
                        and an mtime after the first issued dispatch).
  g4 status-first       hooks/write_guard.py — the worker's first
                        worker-surface write must be the status sync
                        (kunglao-worker.md §1c write order). Session-scoped
                        state in runs/.status-first.json; FAIL_OPEN without
                        a session id or without live dispatched workers.
  g5 verifier-dispatch  the PROVEN promotion path — a claim may not reach
                        PROVEN without evidence a verifier was EVER
                        dispatched for it (red-team DIFF in runs/ or a
                        verifier-class dispatch row in runs/logs/). Composed
                        into compare_register_change_proven_gate (hook
                        backstop) and kunglao_record.claim_migrator
                        (REQUIRED_FOR_TERMINAL_STATE policy).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TS_T0 = "2026-09-04T01:00:00Z"
TS_T1 = "2026-09-04T02:00:00Z"


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


# =====================================================================
# g1 — scheduler-alive gate (exists; pin wiring + repair format)
# =====================================================================

def _make_hb(ws: Path, last_tick_ts: str) -> Path:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    dt = datetime.fromisoformat(last_tick_ts.replace("Z", "+00:00"))
    prev = (dt - timedelta(minutes=5)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"last_tick_ts": last_tick_ts, "started_ts": prev,
         "tick_history": [prev, last_tick_ts]}), encoding="utf-8")
    state = ws / "loop-state.json"
    state.write_text("{}", encoding="utf-8")
    return state


@pytest.mark.skipif(
    (ROOT / "runs" / ".heartbeat.json").exists(),
    reason="skill-side heartbeat probe would mask the workspace-level absence")
def test_g1_scheduler_dead_dispatch_rejected_with_start_command(tmp_path):
    """No .heartbeat.json -> the gate REJECTS and its message carries the
    concrete start command (hook_activation --heartbeat-on), not a plea."""
    import worker_budget as wb
    state = tmp_path / "ws" / "loop-state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")
    alive, msg = wb.check_heartbeat_alive(state)
    assert alive is False, "dispatch without a registered heartbeat must reject"
    assert "hook_activation.py" in msg and "--heartbeat-on" in msg, (
        f"repair path must carry the exact start command: {msg}")


def test_g1_reject_face_carries_concrete_start_command():
    """The #270 additionalContext repair for the heartbeat gate names the
    exact commands: hook_activation --heartbeat-on + the cron registration."""
    import worker_budget_sinks as sinks
    fix = sinks.REJECT_FIXES["heartbeat"]["additionalContext"]
    assert "--heartbeat-on" in fix
    assert "CronCreate" in fix


def test_g1_gate_is_wired_exactly_once_in_pre_check():
    """The scheduler-alive gate already lives in the pre_check battery —
    #57 does NOT duplicate it, it only pins the format."""
    src = (ROOT / "hooks" / "worker_budget_sinks.py").read_text(encoding="utf-8")
    assert "('heartbeat', check_heartbeat_alive(paths['state']))" in src, (
        "the heartbeat gate must stay in the pre_check battery")
    assert src.count("check_heartbeat_alive(paths['state'])") == 1


def test_g1_alive_two_tick_history_passes(tmp_path):
    """Compliance pin: a continuous two-tick heartbeat keeps dispatch open."""
    import worker_budget as wb
    state = _make_hb(tmp_path / "ws",
                     datetime.now(timezone.utc).isoformat(
                         timespec="seconds").replace("+00:00", "Z"))
    alive, msg = wb.check_heartbeat_alive(state)
    assert alive, msg


# =====================================================================
# g2 — orchestrator-overreach gate (bypass fixes + posture)
# =====================================================================

def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "orchestrator_tool_guard_57", ROOT / "hooks" / "orchestrator_tool_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_g2_bash_analysis_binary_rejects_outside_worktree(tmp_path):
    """Ruling: orchestrator overreach is framework-layer -> REJECT (rc 2)
    with a concrete repair path (dispatch a worker), no opt-out."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "Bash",
                                 "tool_input": {"command": "jadx -d out app.apk"}})
    assert rc == 2, "the Bash face must REJECT (#57-2), not WARN"
    assert "REJECT orchestrator_tool_guard" in err, err
    assert ctx and "ispatch" in ctx, "repair path must say: dispatch a worker"


def test_g2_worker_worktree_still_passes(tmp_path):
    """Workers inside .wt-* keep running analysis tools freely."""
    mod = _load_guard()
    wt = tmp_path / ".wt-C100"
    wt.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(wt), "tool_name": "Bash",
                                 "tool_input": {"command": "jadx -d out app.apk"}})
    assert (rc, err, ctx) == (0, "", None)


def test_g2_sh_c_wrapper_no_longer_bypasses(tmp_path):
    """Bypass fix: `sh -c 'jadx ...'` previously matched the command word
    `sh` and slipped past the guard."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    rc, _err, _ctx = mod.evaluate({
        "cwd": str(ws), "tool_name": "Bash",
        "tool_input": {"command": "sh -c 'jadx -d out app.apk'"}})
    assert rc == 2, "sh -c must not bypass the orchestrator-overreach gate"


def test_g2_wrapper_words_no_longer_bypass(tmp_path):
    """nohup / timeout N / env VAR= / xargs wrappers attribute the inner
    analysis binary."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    for cmd in ("nohup floss sample.exe",
                "timeout 60 floss sample.exe",
                "env PATH=/usr/bin jadx -d out app.apk",
                "ls files | xargs apktool d app.apk"):
        rc, _err, _ctx = mod.evaluate({
            "cwd": str(ws), "tool_name": "Bash",
            "tool_input": {"command": cmd}})
        assert rc == 2, f"{cmd!r} must not bypass the gate"


def test_g2_false_positive_controls_stay_silent(tmp_path):
    """#601 precision survives the unwrap: argument-text mentions are not
    command positions."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    for cmd in ("grep floss runs/notes.txt",
                "cat evidence/floss-raw.txt",
                "cd /opt/jadx/bin && ls",
                "echo jadx is worker-exclusive",
                "ls -la"):
        rc, err, ctx = mod.evaluate({
            "cwd": str(ws), "tool_name": "Bash",
            "tool_input": {"command": cmd}})
        assert (rc, err, ctx) == (0, "", None), \
            f"{cmd!r} must stay silent (no alarm fatigue)"


def test_g2_mcp_ida_namespace_joins_host_channel_reject(tmp_path):
    """mcp__ida__* is a decompiler corridor exactly like mcp__ghidra__* —
    the main agent calling it directly bypassed the dispatch corridor."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "mcp__ida__get_metadata",
                                 "tool_input": {}})
    assert rc == 2
    assert "REJECT orchestrator_tool_guard" in err
    # worker face passes
    wt = tmp_path / ".wt-C100"
    wt.mkdir()
    rc2, _e, _c = mod.evaluate({"cwd": str(wt), "tool_name": "mcp__ida__get_metadata",
                                "tool_input": {}})
    assert rc2 == 0


def test_g2_mcp_x64dbg_host_channel_still_rejects(tmp_path):
    """Regression pin for the pre-existing #601 face."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    rc, err, _ctx = mod.evaluate({"cwd": str(ws), "tool_name": "mcp__x64dbg__start_session",
                                  "tool_input": {}})
    assert rc == 2 and "REJECT orchestrator_tool_guard" in err


def test_g2_reject_is_durable(tmp_path):
    """The REJECT face leaves a durable kunglao_log row (#532 item 5)."""
    mod = _load_guard()
    ws = tmp_path / "ws"
    ws.mkdir()
    mod.evaluate({"cwd": str(ws), "tool_name": "Bash",
                  "tool_input": {"command": "ghidra analyzeHeadless proj"}})
    rows = []
    log = ws / "runs" / "logs"
    if log.exists():
        for f in sorted(log.glob("kunglao-*.jsonl")):
            rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    hits = [r for r in rows if r.get("action") == "orchestrator_tool_violation"]
    assert hits, "the REJECT must also be durable"
    assert hits[0].get("exit") == 2


# =====================================================================
# g3 — plan-author gate (worker-session evidence after dispatch)
# =====================================================================

def _seed_anchor_log(ws: Path, key: str, *ts_list: str) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "runs").mkdir(exist_ok=True)
    p = ws / "runs" / f".dispatch-anchor-{key}.jsonl"
    p.write_text("".join(json.dumps({"ts": ts, "claim": "C-001"}) + "\n"
                         for ts in ts_list), encoding="utf-8")
    return p


def _seed_plan(ws: Path, body: str = "goal: decode strings\nsteps: dump strings\n"
               "fallback: xxd walk\n", name: str = "plan-C001.md") -> Path:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    p = ws / "runs" / name
    p.write_text(body, encoding="utf-8")
    return p


def _plan_paths(ws: Path) -> dict:
    return {"workspace": str(ws)}


def test_g3_prewritten_plan_rejected_when_dispatch_anchor_exists(tmp_path):
    """The #239 gate verified the plan FILE, not the AUTHOR — an
    orchestrator pre-written plan (mtime before dispatch, no anchor citation)
    must REJECT once a dispatch anchor exists for the claim."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws)
    _seed_anchor_log(ws, "C001", TS_T0)
    # plan predates the dispatch
    os.utime(ws / "runs" / "plan-C001.md",
             (_epoch(TS_T0) - 3600, _epoch(TS_T0) - 3600))
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok is False, "a pre-dispatch (orchestrator-written) plan must reject"
    assert "dispatch-anchor" in msg, msg
    assert "worker" in msg.lower(), msg


def test_g3_worker_authored_plan_citing_anchor_passes(tmp_path):
    """A plan the worker wrote after dispatch citing the anchor ts passes."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws, body=(
        "---\n"
        f"dispatch-anchor: {TS_T0}\n"
        "---\n"
        "goal: decode strings\nsteps: dump strings\nfallback: xxd walk\n"))
    _seed_anchor_log(ws, "C001", TS_T0)
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok, msg


def test_g3_anchor_line_plus_fresh_mtime_passes(tmp_path):
    """Path B of the contract: an explicit `dispatch-anchor:` line plus an
    mtime after the first issued dispatch proves in-session authorship even
    when the cited value differs (clock/quote variance)."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws, body=(
        f"dispatch-anchor: {TS_T1}\ngoal: x\nsteps: y\nfallback: z\n"))
    _seed_anchor_log(ws, "C001", TS_T0)
    later = _epoch(TS_T0) + 600
    os.utime(ws / "runs" / "plan-C001.md", (later, later))
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok, msg


def test_g3_context_file_arms_the_gate(tmp_path):
    """The #527 corridor artifact (runs/dispatch-context-C001.json) carries
    the nonce too — its dispatch_ts arms the author gate."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws)
    (ws / "runs" / "dispatch-context-C001.json").write_text(json.dumps(
        {"claim_id": "C-001", "dispatch_ts": TS_T0}), encoding="utf-8")
    os.utime(ws / "runs" / "plan-C001.md",
             (_epoch(TS_T0) - 3600, _epoch(TS_T0) - 3600))
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok is False, "context-carried nonce must arm the author gate"
    # citing the context ts passes
    _seed_plan(ws, body=f"dispatch-anchor: {TS_T0}\ngoal: x\nsteps: y\nfallback: z\n")
    ok2, msg2 = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok2, msg2


def test_g3_prompt_context_block_arms_the_gate(tmp_path):
    """A dispatch prompt carrying the KUNGLAO_DISPATCH_CONTEXT block arms
    the gate even without any on-disk anchor artifact."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws)
    os.utime(ws / "runs" / "plan-C001.md",
             (_epoch(TS_T0) - 3600, _epoch(TS_T0) - 3600))
    prompt = (
        "<!-- KUNGLAO_DISPATCH_CONTEXT v1 -->\n"
        f'```json\n{{"claim_id": "C-001", "dispatch_ts": "{TS_T0}"}}\n```\n')
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001", prompt)
    assert ok is False, "prompt-carried nonce must arm the author gate"


def test_g3_not_armed_legacy_posture_unchanged(tmp_path):
    """Regression pin (#239/#294): no dispatch anchor anywhere -> the gate
    behaves exactly as before (content check only)."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws)
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok, f"legacy posture must stay green: {msg}"


def test_g3_prompt_relaxation_path_untouched(tmp_path):
    """Regression pin: plan referenced in the prompt (worker writes it
    post-dispatch) still passes — that IS worker authorship by construction."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    ok, msg = check_worker_plan(
        _plan_paths(ws), "C-001",
        "write runs/plan-C001-strings.md first, then execute")
    assert ok, msg


def test_g3_empty_shell_still_rejected_first(tmp_path):
    """Content gate (#294) keeps precedence over the author gate."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / "ws"
    _seed_plan(ws, body="goal:\npreflight:\nsteps:\nfallback:\n")
    _seed_anchor_log(ws, "C001", TS_T0)
    ok, msg = check_worker_plan(_plan_paths(ws), "C-001")
    assert ok is False and "empty-shell" in msg, msg


def test_g3_approval_point_stamps_the_anchor(tmp_path, capsys):
    """A PASSING dispatch leaves the per-dispatch nonce on disk — that is
    what arms the author gate on the claim's NEXT dispatch."""
    import worker_budget_sinks as sinks
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "runs" / "plan-C001.md").write_text(
        "goal: decode strings\nsteps:\nfallback:\n", encoding="utf-8")
    payload = {
        "tool_input": {
            "name": "w-test",
            "description": "",
            "prompt": '{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
                      '"tier": 1, "tools": ["grep"], "agent": "w-test"}}\n'
                      "facts-snapshot: 1 facts",
        },
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml", "task_spec": ws / "task_spec.yaml",
    }
    rc = sinks.pre_check(payload, paths)
    assert rc == 0, capsys.readouterr().err
    anchor_log = ws / "runs" / ".dispatch-anchor-C001.jsonl"
    assert anchor_log.exists(), "a passing dispatch must stamp its anchor"
    row = json.loads(anchor_log.read_text(encoding="utf-8").splitlines()[-1])
    assert row.get("ts"), "the anchor row carries the dispatch timestamp"


def test_g3_reject_fix_text_documents_the_anchor_contract():
    """The #270 repair wrapper for the plan gate carries the anchor line
    contract (concrete marker + where the worker gets the value)."""
    import worker_budget_sinks as sinks
    fix = sinks.REJECT_FIXES["plan"]["additionalContext"]
    assert "dispatch-anchor" in fix


# =====================================================================
# g4 — status-first gate (worker's first worker-surface write)
# =====================================================================

def _load_wg():
    spec = importlib.util.spec_from_file_location(
        "write_guard_57", ROOT / "hooks" / "write_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _active_worker_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    (ws / "runs" / "worker-status-w1.md").write_text(
        "[12:00] step: started C-001 | status: in-progress\n", encoding="utf-8")
    return ws


def _g4_payload(session_id: str, rel: str) -> tuple[dict, Path]:
    """`rel` is a WORKSPACE-RELATIVE posix path (the status_first_block
    contract — main() computes it via relative_to(ws))."""
    payload = {"session_id": session_id, "tool_name": "Write",
               "tool_input": {"file_path": rel}}
    return payload, Path(rel)


def test_g4_first_worker_surface_write_without_status_blocked(tmp_path):
    """A worker session whose first worker-surface write is a fact file (not
    the status sync) is REJECTed with the concrete repair path."""
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    payload, rel = _g4_payload("sess-worker-a", "facts/F001.md")
    block = mod.status_first_block(ws, payload, rel)
    assert block, "the first worker-surface write must be the status sync"
    assert "worker-status" in block
    assert "status: in-progress" in block, "repair carries the wire format"


def test_g4_status_write_first_passes(tmp_path):
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    payload, rel = _g4_payload(
        "sess-worker-b", "runs/worker-status-w2.md")
    assert mod.status_first_block(ws, payload, rel) is None


def test_g4_second_write_of_session_passes(tmp_path):
    """The gate judges only the FIRST worker-surface write of a session."""
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    p1, r1 = _g4_payload("sess-worker-c", "runs/worker-status-w3.md")
    assert mod.status_first_block(ws, p1, r1) is None
    p2, r2 = _g4_payload("sess-worker-c", "facts/F001.md")
    assert mod.status_first_block(ws, p2, r2) is None, \
        "after a compliant first write, later writes pass"


def test_g4_no_session_id_fails_open(tmp_path):
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    payload, rel = _g4_payload("", "facts/F001.md")
    payload.pop("session_id")
    assert mod.status_first_block(ws, payload, rel) is None


def test_g4_no_active_workers_not_armed(tmp_path):
    """No dispatched worker live -> the face is not the worker face."""
    mod = _load_wg()
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    payload, rel = _g4_payload("sess-x", "facts/F001.md")
    assert mod.status_first_block(ws, payload, rel) is None


def test_g4_orchestrator_carriers_skipped(tmp_path):
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    for name in ("claim-register.yaml", "analysis_state.txt", "task_spec.yaml"):
        payload, rel = _g4_payload("sess-orch", name)
        assert mod.status_first_block(ws, payload, rel) is None, name


def test_g4_out_of_scope_first_write_does_not_mask_the_gate(tmp_path):
    """A scratch write outside the worker surfaces is not 'first action'
    evidence — the first WORKER-SURFACE write is the one adjudicated."""
    mod = _load_wg()
    ws = _active_worker_ws(tmp_path)
    p1, r1 = _g4_payload("sess-d", "scripts/tool.py")
    assert mod.status_first_block(ws, p1, r1) is None
    p2, r2 = _g4_payload("sess-d", "notes/n.md")
    assert mod.status_first_block(ws, p2, r2), \
        "the first worker-surface write still must be the status sync"


def test_g4_end_to_end_block_then_status_write(tmp_path):
    """Subprocess e2e: facts-first write BLOCKs (rc 2); writing the status
    file afterwards is allowed (the session self-heals via the repair)."""
    ws = _active_worker_ws(tmp_path)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(
               [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])}

    def _run(file_path: str, sid: str = "sess-e2e") -> subprocess.CompletedProcess:
        payload = json.dumps({
            "session_id": sid, "tool_name": "Write", "cwd": str(ws),
            "tool_input": {"file_path": file_path, "content": "x"},
        })
        return subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "write_guard.py")],
            input=payload, capture_output=True, text=True, timeout=60,
            env=env, errors="replace")

    facts_first = _run(str(ws / "facts" / "F001.md"))
    assert facts_first.returncode == 2, facts_first.stderr
    assert "worker-status" in facts_first.stderr
    # the repair path is executable: write the status, then the session is
    # recorded and later worker-surface writes go through (non-carrier target
    # keeps this assert about gate 4, not about the fact-schema legs)
    status_write = _run(str(ws / "runs" / "worker-status-w9.md"))
    assert status_write.returncode == 0, status_write.stderr
    next_write = _run(str(ws / "runs" / "progress.txt"))
    assert next_write.returncode == 0, next_write.stderr


# =====================================================================
# g5 — verifier-dispatch gate (PROVEN promotion needs a dispatched verifier)
# =====================================================================

VALID_SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w2
      refute_attempt: "tried grep for alt-config; not found - claim holds"
      sign_off_at: 2026-09-04T02:00:00Z
      verdict: CONFIRMED
    ```
    """)


def _proven_ws(tmp_path: Path, status_before: str = "OPEN") -> tuple[Path, Path]:
    """Canonical register dialect (`- id:` col 0, attrs at 2 spaces — the
    same dialect _set_claim_status's line rewrite preserves). The fact avoids
    inference-pattern words (e.g. `gate`) so the claim stays non-inferential
    and the promotion reaches PROVEN-candidate."""
    from _factories import seed_difficulty, write_claims_register
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    # #16: these gates pin the LEGACY single-verification posture — tier easy
    # (a feed-less workspace now fails closed to hard, two verifier records).
    seed_difficulty(ws, "easy")
    (ws / "analysis_state.txt").write_text("[current_task]\n", encoding="utf-8")
    reg = write_claims_register(ws, [{
        "id": "C-001", "status": status_before,
        "statement": "imports resolved at runtime",
    }])
    (ws / "facts" / "C-001.md").write_text(
        "---\nid: F001\ntype: fact\ntitle: t\nstatus: INFERRED\n"
        "created: 2026-09-04\nlast_reviewed: 2026-09-04\nclaim_id: C-001\n"
        "claim: imports resolved at runtime\nboundary_type: observation\n"
        "source: static-decompile\nconfidence: medium\n"
        "verify_status: partial\nreproduce: python runs/verify.py\n"
        "expected: pending\nverified: pending\nprovenance:\n"
        "  - {role: decompiled_c, path: evidence/x.c}\n---\n\n"
        "## Status\nINFERRED\n\n" + VALID_SIGNOFF, encoding="utf-8")
    return ws, reg


def _flip_to_proven(reg: Path, before_status: str = "OPEN") -> dict:
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        f"status: {before_status}", "status: PROVEN"), encoding="utf-8")
    return {"C-001": before_status}


def _seed_redteam_diff(ws: Path, claim: str = "C-001") -> Path:
    p = ws / "runs" / f"verify-redteam-{claim}.md"
    p.write_text(
        f"# Red-team verification: {claim}\n\n## My independent derivation\n"
        "recomputed offsets from the raw bytes.\n\n"
        "RED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
    return p


def _seed_dispatch_log_row(ws: Path, claim: str = "C-001") -> Path:
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    p = logs / "kunglao-2026-09-04.jsonl"
    row = {"ts": TS_T1, "actor": "hook:worker_budget", "action": "dispatch",
           "claim": claim,
           "detail": f"tier=1 tools=grep agent=kunglao-redteam (verifier for {claim})"}
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return p


def test_g5_proven_without_verifier_dispatch_blocked(tmp_path):
    """A claim reaching PROVEN-candidate with NO verifier dispatch record is
    blocked, and the reason carries the concrete dispatch repair."""
    import worker_budget as wb
    ws, reg = _proven_ws(tmp_path)
    before = _flip_to_proven(reg)
    ok, reason = wb.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok is False, "PROVEN without a dispatched verifier must be blocked"
    assert "verifier" in reason.lower()
    assert "kunglao-redteam" in reason, "repair names the verifier agent"
    assert "verify-redteam" in reason, "repair names the DIFF landing zone"


def test_g5_proven_with_redteam_diff_passes(tmp_path):
    import worker_budget as wb
    ws, reg = _proven_ws(tmp_path)
    _seed_redteam_diff(ws)
    before = _flip_to_proven(reg)
    ok, reason = wb.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok, f"a dispatched verifier's DIFF satisfies the gate: {reason}"


def test_g5_proven_with_dispatch_log_row_passes(tmp_path):
    import worker_budget as wb
    ws, reg = _proven_ws(tmp_path)
    _seed_dispatch_log_row(ws)
    before = _flip_to_proven(reg)
    ok, reason = wb.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok, f"a verifier-class dispatch row satisfies the gate: {reason}"


def test_g5_no_promotion_passthrough_unchanged(tmp_path):
    """Regression pin: non-promoting register edits do not trip the gate."""
    import worker_budget as wb
    ws, reg = _proven_ws(tmp_path)
    before = {"C-001": "OPEN"}
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "imports resolved at runtime", "imports resolved lazily"),
        encoding="utf-8")
    ok, _reason = wb.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok


def test_g5_worker_redteam_rows_do_not_satisfy_other_claims(tmp_path):
    """Evidence is claim-scoped: another claim's DIFF does not open this one."""
    import worker_budget as wb
    ws, reg = _proven_ws(tmp_path)
    _seed_redteam_diff(ws, "C-002")
    before = _flip_to_proven(reg)
    ok, _reason = wb.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok is False


def test_g5_claim_migrator_blocks_without_evidence(tmp_path):
    """REQUIRED_FOR_TERMINAL_STATE face: claim_migrator refuses the PROVEN
    migration when no verifier was ever dispatched (register untouched)."""
    import yaml as _yaml
    from kunglao_record import claim_migrator
    ws, _reg = _proven_ws(tmp_path, status_before="VERIFIED")
    ok, msg = claim_migrator(ws, "C-001", "PROVEN", actor="orchestrator")
    assert ok is False, "promotion without a dispatched verifier must refuse"
    assert "VERIFIER DISPATCH" in msg, msg
    statuses = _yaml.safe_load((ws / "claim-register.yaml").read_text())["claims"]
    assert [c["status"] for c in statuses if c["id"] == "C-001"] == ["VERIFIED"], \
        "the register must stay unmodified (fail closed)"


def test_g5_claim_migrator_passes_with_evidence(tmp_path):
    import yaml as _yaml
    from kunglao_record import claim_migrator
    ws, _reg = _proven_ws(tmp_path, status_before="VERIFIED")
    _seed_redteam_diff(ws)
    ok, msg = claim_migrator(ws, "C-001", "PROVEN", actor="orchestrator")
    assert ok, msg
    statuses = _yaml.safe_load((ws / "claim-register.yaml").read_text())["claims"]
    assert [c["status"] for c in statuses if c["id"] == "C-001"] == ["PROVEN"]


def test_g5_gate_joins_required_for_terminal_state():
    """The policy tuple names the new gate — same REQUIRED policy as #78."""
    from kunglao_record import REQUIRED_FOR_TERMINAL_STATE
    assert "blind_gate:check_verifier_dispatch_evidence" in REQUIRED_FOR_TERMINAL_STATE


def test_g5_downgrade_to_stamp_does_not_demand_evidence(tmp_path, monkeypatch):
    """Runtime verifier failure degrades to STAMP (unchanged #98 posture) —
    the dispatch-evidence gate only governs claims that would land PROVEN."""
    import blind_gate
    import kunglao_record
    ws, _reg = _proven_ws(tmp_path, status_before="VERIFIED")

    def _boom(*_a, **_k):
        raise RuntimeError("boom: gate crashed")

    monkeypatch.setattr(blind_gate, "check_proven_gate", _boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
    assert ok, f"runtime error should degrade to STAMP: {msg}"
    assert "VERIFIER DISPATCH" not in msg, "downgrades skip the dispatch gate"


# =====================================================================
# cross-gate ruling pins
# =====================================================================

def test_no_opt_out_flags_added():
    """Ruling: NO opt-out flags. The five gate surfaces must not grow
    env/flag-based escapes."""
    banned = ("KUNGLAO_SKIP_FRAMEWORK_GATES", "KUNGLAO_DISABLE_RIGIDITY",
              "skip_framework_gate", "rigidity_opt_out")
    for rel in ("hooks/worker_budget_sinks.py", "hooks/worker_budget_gates.py",
                "hooks/write_guard.py", "hooks/orchestrator_tool_guard.py",
                "scripts/blind_gate.py", "scripts/kunglao_record.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for token in banned:
            assert token not in src, f"{rel} must not carry opt-out {token}"
