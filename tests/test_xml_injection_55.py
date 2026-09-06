# -*- coding: utf-8 -*-
"""tests/test_xml_injection_55.py — XML tag injection standard (#55).

Owner-ruled design (issue #55, do not relitigate): every message kunglao
injects into the AGENT's context is producer-attributed and trust-tagged
with one of EIGHT fixed XML tags (references/xml-injection-standard.md).
Tags MARK information — they never gate on tag presence (lighting, not
enforcement).

Surfaces wired in this PR:
  - hooks/recall_inject.py _guidance()          -> <kunglao-facts>
  - hooks/worker_pulse.py additionalContext     -> <worker-signal>
  - hooks/dispatch_gate.py verdict faces        -> <gate-verdict>
  - hooks/worker_budget_sinks.py _reject        -> <gate-verdict>

Contract pinned here, enforced by the wrapper helpers:
  - the human-readable guidance/repair text sits INSIDE the tag; the
    Claude Code hook JSON contract (hookSpecificOutput.additionalContext,
    decision/block/reason) is untouched
  - stderr summaries (the operator channel) stay UNtagged
  - statusline_snapshot / heartbeat reports are USER-facing UI — never
    tagged (tags are for agent-context injection only)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

KUNGLAO_FACTS = ("<kunglao-facts>", "</kunglao-facts>")
GATE_VERDICT = ("<gate-verdict>", "</gate-verdict>")
WORKER_SIGNAL = ("<worker-signal>", "</worker-signal>")


def _assert_wrapped(text: str, tag: tuple[str, str]) -> None:
    assert text.startswith(tag[0]), f"must open with {tag[0]}: {text!r}"
    assert text.endswith(tag[1]), f"must close with {tag[1]}: {text!r}"


# ---------- <kunglao-facts>: recall_inject._guidance (#55 surface 2) ----------


def _recall_payload(ws: Path, prompt: str) -> dict:
    return {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": prompt},
    }


def _recall_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    return ws


VM_CLAIM = (
    "[T3 tools=mcp__x64dbg__*,mcp__frida__*] claim C-101 observe the sample's "
    "dynamic behavior in the VM with x64dbg breakpoints and frida injection"
)


def test_recall_guidance_wrapped_in_kunglao_facts(tmp_path):
    """Knowledge recall is INTERNAL kunglao knowledge -> <kunglao-facts>,
    never <external-tools> (the reference library is not third-party output).
    """
    from recall_inject import evaluate

    ws = _recall_ws(tmp_path)

    def runner(query):
        return 0, ("# references recall\n"
                   "dynamic-re-tool-priority.md | a | b | c\n")

    rc, stderr, ctx = evaluate(_recall_payload(ws, VM_CLAIM), recall_runner=runner)
    assert rc == 0 and stderr == ""
    assert ctx, "recall must still inject"
    _assert_wrapped(ctx, KUNGLAO_FACTS)


def test_recall_guidance_inner_text_preserved_inside_tag(tmp_path):
    """The wrapper is additive: the pre-#55 guidance lines survive verbatim
    INSIDE the tag (existing substring pins stay green)."""
    from recall_inject import evaluate

    ws = _recall_ws(tmp_path)
    rc, _, ctx = evaluate(
        _recall_payload(ws, VM_CLAIM),
        recall_runner=lambda q: (
            0, "dynamic-re-tool-priority.md | a | b | c\n"))
    assert rc == 0
    inner = ctx
    for edge in KUNGLAO_FACTS:
        inner = inner.replace(edge, "")
    assert "recall_inject: claim dispatch knowledge recall" in inner
    assert "Before dispatching, read: dynamic-re-tool-priority.md" in inner


def test_recall_main_stdin_wrapped_end_to_end(tmp_path):
    """The wired shape: the additionalContext JSON carries the tagged text."""
    ws = _recall_ws(tmp_path)
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "recall_inject.py")],
        input=json.dumps(_recall_payload(ws, VM_CLAIM)), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **__import__("os").environ},
        cwd=str(ws), timeout=120,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, KUNGLAO_FACTS)


# ---------- <gate-verdict>: worker_budget_sinks._reject (#55 surface 4) ------


def test_budget_reject_additional_context_wrapped_in_gate_verdict():
    """Every worker_budget REJECT lands its guidance inside <gate-verdict>;
    the repair path (the canned fix text) must sit inside the tag."""
    from worker_budget_sinks import REJECT_FIXES, _reject

    for name in ("plan", "toolfirst", "workers", "cap", "devreason"):
        entry = REJECT_FIXES[name]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("worker_budget_sinks._SKILL_ROOT", REPO_ROOT)
            import io
            import contextlib
            buf_out, buf_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf_out), \
                    contextlib.redirect_stderr(buf_err):
                rc = _reject(name, "synthetic verdict message",
                             {"workspace": "/tmp/ws-x"})
            assert rc == 2
        err = buf_err.getvalue()
        assert f"REJECT {name}" in err
        assert GATE_VERDICT[0] not in err, "stderr is the operator channel"
        out = json.loads(buf_out.getvalue())
        ctx = out["hookSpecificOutput"]["additionalContext"]
        _assert_wrapped(ctx, GATE_VERDICT)
        # the reason AND the repair path are inside the tag
        assert "synthetic verdict message" in ctx
        fix_keyword = entry["additionalContext"].split(".")[0][:20]
        assert fix_keyword in ctx


def test_toolfirst_reject_reason_and_repair_path_inside_tag():
    """The #294 tool-first REJECT reason (which already carries the
    'Add `tool-catalog: ...`' repair instruction) is emitted INSIDE
    <gate-verdict> — the agent reads verdict + repair as one unit."""
    from worker_budget_gates import _toolfirst_evaluate
    from worker_budget_sinks import _reject

    ev = _toolfirst_evaluate(
        "decode the crypto layer of the payload".lower(), cited=None)
    assert ev["mode"] == "reject", "keyword hit without marker must reject"
    reason = ev["reason"]
    assert "tool-catalog" in reason, "reason must carry the repair marker"

    import io
    import contextlib
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), \
            contextlib.redirect_stderr(buf_err):
        rc = _reject("toolfirst", reason, {"workspace": "/tmp/ws-x"})
    assert rc == 2
    ctx = json.loads(buf_out.getvalue())["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, GATE_VERDICT)
    assert reason in ctx, "the evaluate() reason must survive inside the tag"


def test_budget_reject_fixes_table_untagged():
    """The tag is applied at the EMISSION site (_reject), not baked into the
    REJECT_FIXES table — stderr reuse and tests read the raw guidance."""
    from worker_budget_sinks import REJECT_FIXES
    for name, entry in REJECT_FIXES.items():
        assert GATE_VERDICT[0] not in entry["additionalContext"], name


# ---------- <gate-verdict>: dispatch_gate verdict faces (#55 surface 4) ------


def test_dispatch_gate_reject_with_guidance_wrapped(capsys):
    """dispatch_gate._reject_with_guidance (top1 / mcp_prefix / capability /
    tools_rack faces) wraps the verdict + fix path in <gate-verdict>."""
    import dispatch_gate as dg

    rc = dg._reject_with_guidance(
        "top1", "synthetic top1 message",
        "add `agent-reasoning: <why>` to the dispatch prompt.")
    assert rc == 2
    captured = capsys.readouterr()
    assert "REJECT top1" in captured.err
    assert GATE_VERDICT[0] not in captured.err, "stderr stays untagged"
    ctx = json.loads(captured.out)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, GATE_VERDICT)
    assert "synthetic top1 message" in ctx
    assert "agent-reasoning" in ctx, "repair path inside the tag"


def test_dispatch_gate_must_stop_verdict_wrapped(tmp_path, capsys):
    """The #447 must-stop HARD_PAUSE refusal is a gate verdict too."""
    import dispatch_gate as dg

    ws = tmp_path / "ws"
    ws.mkdir()
    rc = dg._warn_must_stop(ws, "C-9", "vmrun delete snapshot one", "must_stop_snapshot_ops")
    assert rc == 2
    captured = capsys.readouterr()
    ctx = json.loads(captured.out)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, GATE_VERDICT)
    assert "HARD_PAUSE" in ctx
    assert "vmrun delete" in ctx


def _failure_blocked_ws(root: Path) -> Path:
    """Workspace whose claim C-1 was attempted (promotion_attempts > 0) but
    has no failure_analysis -> dispatch_gate's #495 corrective injection."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "OPEN", "statement": "x",
                     "promotion_attempts": 1}]},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


def test_dispatch_gate_failure_blocked_guidance_wrapped(tmp_path):
    """The #495 failure-blocked corrective injection (repair path: run
    failure_analysis_gate) is a verdict face -> wrapped in <gate-verdict>."""
    root = tmp_path / "root"
    ws = _failure_blocked_ws(root)
    payload = json.dumps({
        "cwd": str(root), "workspace": str(ws),
        "tool_input": {"prompt": "[T1 tools=grep] claim C-1 retry"}},
    )
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "failure-blocked" in ctx, "pre-#55 guidance text preserved"
    _assert_wrapped(ctx, GATE_VERDICT)
    assert "failure_analysis_gate.py" in ctx, "repair path inside the tag"


# ---------- <worker-signal>: worker_pulse payloads (#55 surface 3) -----------


@pytest.fixture()
def pulse_ws(tmp_path, monkeypatch):
    """worker_pulse with the IO seams patched; capture the JSON it prints."""
    import worker_pulse as wp

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    monkeypatch.setattr(wp, "_resolve_workspace", lambda payload: ws)
    monkeypatch.setattr(wp, "_kunglao_active", lambda ws_: True)
    return wp, ws


def test_worker_pulse_payload_wrapped_in_worker_signal(pulse_ws, capsys, monkeypatch):
    """The convergence pulse is a worker lifecycle/status signal."""
    wp, ws = pulse_ws
    monkeypatch.setattr(wp, "_was_dispatch", lambda payload: True)
    monkeypatch.setattr(wp, "_build_pulse", lambda ws_: ("PULSE-BODY next up: C-1", None))
    monkeypatch.setattr(wp, "_delivery_reminder", lambda ws_: "")
    rc = wp.main({"cwd": str(ws)})
    assert rc == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, WORKER_SIGNAL)
    assert "PULSE-BODY next up: C-1" in ctx, "inner text preserved"


def test_worker_pulse_stale_message_wrapped(pulse_ws, capsys, monkeypatch):
    """The non-dispatch stale-worker soft pulse is the same signal class."""
    wp, ws = pulse_ws
    monkeypatch.setattr(wp, "_was_dispatch", lambda payload: False)
    monkeypatch.setattr(wp, "_check_stale_workers",
                        lambda ws_: "[worker_pulse] 1 stale in-progress worker(s): w1")
    rc = wp.main({"cwd": str(ws)})
    assert rc == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, WORKER_SIGNAL)
    assert "w1" in ctx


def test_worker_pulse_taskstop_reminder_wrapped(pulse_ws, capsys, monkeypatch):
    """The #88 TASKSTOP delivery reminder rides the same <worker-signal>."""
    wp, ws = pulse_ws
    monkeypatch.setattr(wp, "_was_dispatch", lambda payload: True)
    monkeypatch.setattr(wp, "_build_pulse", lambda ws_: ("", None))
    monkeypatch.setattr(wp, "_delivery_reminder",
                        lambda ws_: "TASKSTOP: w1 delivered - TaskStop now")
    rc = wp.main({"cwd": str(ws)})
    assert rc == 0
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, WORKER_SIGNAL)
    assert "TASKSTOP: w1 delivered" in ctx


def test_worker_pulse_blocked_stderr_untagged(pulse_ws, capsys, monkeypatch):
    """On BLOCKED the pulse goes to STDERR (operator channel, rc=3) — the
    operator channel stays untagged; tags mark agent-context injection."""
    wp, ws = pulse_ws
    monkeypatch.setattr(wp, "_was_dispatch", lambda payload: True)
    monkeypatch.setattr(wp, "_build_pulse", lambda ws_: ("BLOCKED body", "BLOCKED"))
    rc = wp.main({"cwd": str(ws)})
    assert rc == 3
    captured = capsys.readouterr()
    assert captured.out == "", "BLOCKED path must not emit additionalContext"
    assert "BLOCKED body" in captured.err
    assert WORKER_SIGNAL[0] not in captured.err


# ---------- <gate-verdict> end-to-end via the wired dispatch_gate ------------


def _top1_ws(root: Path) -> Path:
    """Rank-unambiguous workspace (exact pattern from test_decision_teeth):
    C-1 = top-1 (competitor_group g1), C-2 = rank #2 (answers_question),
    C-3 = rank #3 (g1 member, tier-2 cost) — dispatching C-3 without
    agent-reasoning REJECTs through _top1_enforcement."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [
            {"id": "C-2", "status": "OPEN", "statement": "background work",
             "answers_question": "PQ-1"},
            {"id": "C-1", "status": "OPEN", "statement": "background work",
             "competitor_group": "g1"},
            {"id": "C-3", "status": "OPEN", "statement": "background work",
             "competitor_group": "g1", "evidence_tier_attempted": 1},
        ]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text(yaml.safe_dump(
        {"depends_on": {}, "competitor_groups": {"g1": ["C-1", "C-3"]}},
        allow_unicode=True, sort_keys=False), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": []}), encoding="utf-8")
    # #107 re-pin: C-1 holds a strong GREEN oracle-case posterior — its
    # Thompson case face pins it at rank #1, so the C-3 dispatch is a
    # non-top-1 deviation (the thing this test REJECTs on).
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "oracle" / "cases" / "case-c1.yaml").write_text(
        yaml.safe_dump({"id": "case-c1", "target_pq": "PQ-C1"}),
        encoding="utf-8")
    (ws / "runs" / "posteriors.yaml").write_text(yaml.safe_dump({
        "schema": "posteriors-schema/1",
        "cases": {"case-c1": {"alpha": 30.0, "beta": 1.0,
                              "pending_entries": 0}},
        "pqs": {}}), encoding="utf-8")
    # link C-1's row to the case's PQ
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    for c in reg["claims"]:
        if c["id"] == "C-1":
            c["answers_question"] = "PQ-C1"
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        reg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


def test_top1_reject_end_to_end_wrapped(tmp_path):
    """The wired dispatch_gate top-1 REJECT carries the repair instruction
    inside <gate-verdict> — verdict and fix read as one producer-attributed
    unit (#55 surface 4, the #496 top-1 tooth)."""
    root = tmp_path / "root"
    ws = _top1_ws(root)
    payload = json.dumps({
        "cwd": str(root), "workspace": str(ws),
        "tool_input": {"prompt": "[T2 tools=grep] claim C-3 background sweep"}},
    )
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )
    assert r.returncode == 2, f"top-1 deviation must REJECT; stderr={r.stderr!r}"
    assert "REJECT top1" in r.stderr
    assert GATE_VERDICT[0] not in r.stderr
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    _assert_wrapped(ctx, GATE_VERDICT)
    assert "agent-reasoning" in ctx, "repair path inside the tag"
    assert "C-1" in ctx, "the ranked authority is named inside the tag"


# ---------- the standard document (#55 surface 1) ----------------------------

STANDARD = REPO_ROOT / "references" / "xml-injection-standard.md"


def test_standard_doc_exists_and_pins_all_eight_tags():
    text = STANDARD.read_text(encoding="utf-8")
    for tag in ("<kunglao-state>", "<kunglao-facts>",
                "<external-tools", "<tool-recommendations",
                "<case-hints>", "<gate-verdict>",
                "<oracle-sanction>", "<worker-signal>"):
        assert tag in text, f"{tag} missing from the standard"
    # owner-mandated attributes
    assert 'trust="raw-signal"' in text, "external-tools MUST carry raw-signal"
    assert 'no-enforcement="true"' in text, "recommendations MUST be non-binding"
    assert "#49" in text, "case-hints producer lands with #49"


def test_standard_doc_states_ui_vs_agent_context_rule():
    """statusline_snapshot / heartbeat reports are USER-facing UI — the
    standard must record that they are NOT tagged."""
    text = STANDARD.read_text(encoding="utf-8")
    assert "statusline" in text and "agent" in text.lower()


def test_standard_doc_states_lighting_not_enforcement():
    text = STANDARD.read_text(encoding="utf-8")
    assert "never gate" in text.lower() or "not enforcement" in text.lower()
