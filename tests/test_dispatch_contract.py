"""RED — dispatch contract isolation-first + TaskStop-on-delivery (issue #88).

Regression tests for the isolation-first dispatch contract
(openspec/changes/isolation-first-dispatch-contract/). Corrected scope
(2026-08-12 user: "SendMessage我不认为有问题"): SendMessage orchestrator↔worker
pings are RETAINED (sanctioned heartbeat channel); only TEAM features are
banned (no CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS, no teammates, no team setup,
no worker↔worker messaging).

  1. test_no_stale_task_tool_references     — repo-wide grep: no stale `Task`-tool
                                            references (the `Agent` tool is the
                                            only dispatch tool); TaskStop /
                                            TaskList / task_spec / task-oracle
                                            stay untouched
  2. test_skill_dispatch_contract_isolation_first — SKILL.md §1 + §"The dispatch
                                            contract" carry ALL FOUR isolation
                                            markers: no-agent-team, workers-
                                            never-message-each-other,
                                            SendMessage-ping-allowed,
                                            TaskStop-on-delivery
  3. test_cold_start_contract_isolation_first — references/cold-start-contract.md
                                            Phase 0 documents the removed
                                            CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
                                            machine-level root cause
  4. test_operational_mechanics_isolation_first — references/operational-mechanics.md:
                                            "Delivery = TaskStop" checklist +
                                            retained SendMessage ping step +
                                            no agent-team instructions
  5. test_worker_pulse_taskstop_reminder    — hooks/worker_pulse.py injects a
                                            TASKSTOP: reminder on a dispatch
                                            completion whose worker status file
                                            shows a final state (`done`), and
                                            stays silent for `in-progress`
  6. test_heartbeat_prompt_sendmessage_allowed — scripts/heartbeat_loop_prompt.py
                                            output KEEPS the SendMessage ping
                                            step and carries no agent-team
                                            markers
  7. test_redteam_agent_no_team_features    — agents/kunglao-redteam.md has no
                                            `- Task` disallowedTools entry and
                                            no agent-team wording (verdict via
                                            runs/ report file; SendMessage
                                            permitted, not instructed)
  8. test_monitor_background_note           — references/operational-mechanics.md
                                            states kunglao-monitor.py runs as a
                                            BACKGROUND process that never blocks
                                            the loop's scheduled tick actions

RED phase: against the baseline tree the stale-ref tests, the isolation-first
markers, the cold-start Phase 0 note, the delivery checklist, the TASKSTOP
reminder, and the monitor-background note FAIL; the flipped
sendmessage-allowed tests may already pass (the channel was never removed).
The pre-existing failures test_acceptance_overall_passes /
test_skill_lte_500_lines are NOT part of this file and stay untouched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"

# ---------------------------------------------------------------------------
# stale Task-tool reference patterns (spec REQ-1, D6)
# ---------------------------------------------------------------------------
# Legitimate tokens (TaskStop / TaskList / task_spec / task-oracle) are
# excluded BY PATTERN DESIGN, not by a filter: `` `Task` `` requires the
# closing backtick, "Task tool" is the literal phrase, and the tool entry is
# an exact `- Task` list item. test_no_stale_task_tool_references proves the
# exclusion by matching the patterns against the legit tokens themselves.
STALE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Task tool phrase", re.compile(r"Task tool")),
    ("backtick-quoted `Task`", re.compile(r"`Task`")),
    ("disallowedTools entry `- Task`", re.compile(r"^\s*-\s+Task\s*$", re.MULTILINE)),
]
LEGIT_TOKENS = ["TaskStop", "TaskList", "task_spec", "task-oracle"]
SCAN_DIRS = ["references", "hooks", "scripts", "agents", ".claude"]

# Team-feature markers that must NEVER appear as instructions (corrected scope:
# only team features are banned — SendMessage orchestrator↔worker pings are the
# sanctioned channel).
TEAM_MARKERS = ["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "teammate", "team setup"]


def _scan_surface() -> list[tuple[str, int, str, str]]:
    """Grep the contract surface for stale Task-tool references.

    Surface = SKILL.md + everything under references/, hooks/, scripts/,
    agents/, .claude/ (spec REQ-1). .claude/PRPs/ planning records are
    historical prose quoting the old `Task` tool — exempt, not live contract.
    Returns [(relpath, lineno, line, pattern)].
    """
    targets = [SKILL]
    for d in SCAN_DIRS:
        targets.extend(p for p in (ROOT / d).rglob("*") if p.is_file())
    hits: list[tuple[str, int, str, str]] = []
    for p in targets:
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if ".claude" in p.parts and "PRPs" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text:  # binary — not part of the text contract surface
            continue
        for name, pat in STALE_PATTERNS:
            for m in pat.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                line = text.splitlines()[lineno - 1].strip()
                hits.append((str(p.relative_to(ROOT)), lineno, line, name))
    return hits


def _section(text: str, start: str, level: str) -> str:
    """Slice from the heading line starting with `start` to the next heading
    matching `level` (e.g. r"^## " for h2). Empty if the heading is absent."""
    lines = text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if l.startswith(start)), None)
    if start_idx is None:
        return ""
    rest = lines[start_idx:]
    end_idx = len(rest)
    for i, l in enumerate(rest[1:], start=1):
        if re.match(level, l):
            end_idx = i
            break
    return "\n".join(rest[:end_idx])


_DELIVERY_HEADING = re.compile(r"^#{1,4}\s+.*[Dd]elivery.*TaskStop")


def _delivery_section(text: str) -> str:
    """The "Delivery = TaskStop" checklist section (D1), or '' if absent."""
    lines = text.splitlines()
    start_idx = next((i for i, l in enumerate(lines) if _DELIVERY_HEADING.match(l)), None)
    if start_idx is None:
        return ""
    rest = lines[start_idx:]
    end_idx = len(rest)
    for i, l in enumerate(rest[1:], start=1):
        if re.match(r"^#{1,4}\s+", l):
            end_idx = i
            break
    return "\n".join(rest[:end_idx])


# ---------------------------------------------------------------------------
# 1. repo-wide no-stale-Task-tool-reference grep
# ---------------------------------------------------------------------------

def test_no_stale_task_tool_references() -> None:
    """Agent is the only dispatch tool: 0 stale `Task`-tool references repo-wide."""
    hits = _scan_surface()
    assert not hits, (
        f"stale Task-tool references found ({len(hits)}):\n"
        + "\n".join(f"  {name}: {rel}:{ln}: {line}" for rel, ln, line, name in hits)
    )
    # Legitimate tokens are excluded by pattern design — prove it, and prove
    # they still exist on the surface (spec REQ-1: "SHALL remain untouched").
    for token in LEGIT_TOKENS:
        for name, pat in STALE_PATTERNS:
            assert not pat.search(token), f"pattern {name!r} would flag legit token {token!r}"
    surface_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in [SKILL]
        + [q for d in SCAN_DIRS for q in (ROOT / d).rglob("*") if q.is_file()]
        if "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    for token in LEGIT_TOKENS:
        assert token in surface_text, f"legit token {token!r} vanished from the contract surface"


# ---------------------------------------------------------------------------
# 2-4. isolation-first markers in the contract documents
# ---------------------------------------------------------------------------

def test_skill_dispatch_contract_isolation_first() -> None:
    """SKILL.md §1 (Tool-use boundary) AND §"The dispatch contract" both carry
    ALL FOUR isolation-first markers (spec REQ-2 scenario):
    (a) no-agent-team — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS never enabled /
        no teammates / no team setup,
    (b) workers-never-message-each-other,
    (c) SendMessage orchestrator↔worker ping ALLOWED (sanctioned channel),
    (d) TaskStop-on-delivery."""
    text = SKILL.read_text(encoding="utf-8")
    sections = {
        "§1 Tool-use boundary": _section(text, "### 1. Tool-use boundary", r"^### "),
        "The dispatch contract": _section(text, "## The dispatch contract", r"^## "),
    }
    assert all(sections.values()), f"SKILL.md sections not found: {[k for k, v in sections.items() if not v]}"
    for label, sec in sections.items():
        sec_norm = re.sub(r"\s+", " ", sec)  # phrase checks survive line wrapping
        # (a) no-agent-team statement
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in sec, (
            f"{label}: missing no-agent-team rule (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS)")
        assert ("teammate" in sec) or ("team setup" in sec), (
            f"{label}: missing teammates/team-setup prohibition")
        # (b) workers never message each other
        assert "never message each other" in sec_norm, (
            f"{label}: missing workers-never-message-each-other statement")
        # (c) SendMessage orchestrator↔worker ping ALLOWED (retained channel)
        assert "SendMessage" in sec, f"{label}: missing SendMessage ping statement"
        assert ("allowed" in sec) or ("retained" in sec) or ("sanctioned" in sec), (
            f"{label}: missing SendMessage-ping-allowed statement")
        # (d) TaskStop-on-delivery statement
        assert "TaskStop" in sec and re.search(r"\bdeliver", sec), (
            f"{label}: missing TaskStop-on-delivery statement")


def test_cold_start_contract_isolation_first() -> None:
    """references/cold-start-contract.md Phase 0 carries the isolation-first
    rule + the cautionary note: CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS was the
    removed 2026-08-12 machine-level root cause, SHALL NOT be re-enabled."""
    text = (ROOT / "references" / "cold-start-contract.md").read_text(encoding="utf-8")
    phase0 = _section(text, "## Phase 0", r"^## ")
    assert phase0, "references/cold-start-contract.md Phase 0 section not found"
    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in phase0, (
        "Phase 0: missing isolation-first rule (flag name)")
    assert "2026-08-12" in phase0, "Phase 0: missing 2026-08-12 root-cause date"
    assert "re-enable" in phase0, "Phase 0: missing SHALL-NOT-re-enable caution"


def test_operational_mechanics_isolation_first() -> None:
    """references/operational-mechanics.md: the heartbeat tick loop KEEPS the
    SendMessage ping step (orchestrator→worker), contains no agent-team
    instructions, and a "Delivery = TaskStop" checklist orders TaskStop on
    delivery confirmation (spec REQ-2/REQ-4 scenarios)."""
    text = (ROOT / "references" / "operational-mechanics.md").read_text(encoding="utf-8")
    # heartbeat tick loop (D2): SendMessage ping step retained, no team features
    tick = _section(text, "## Active workers heartbeat (the tick loop)", r"^### ")
    assert tick, "operational-mechanics.md tick loop section not found"
    assert "SendMessage" in tick, (
        "heartbeat tick loop must keep the SendMessage ping step (orchestrator→worker)")
    for marker in TEAM_MARKERS:
        assert marker not in tick, (
            f"heartbeat tick loop must not instruct agent-team features ({marker})")
    # delivery checklist (D1): TaskStop a worker whose delivery is confirmed
    delivery = _delivery_section(text)
    assert delivery, "missing 'Delivery = TaskStop' delivery checklist section"
    assert "TaskStop" in delivery and "verified" in delivery, (
        "delivery checklist must TaskStop a delivered worker (final status + verified artifacts)")


# ---------------------------------------------------------------------------
# 5. worker_pulse TASKSTOP-on-delivery reminder
# ---------------------------------------------------------------------------

def _make_worker_ws(path: Path, status: str = "done") -> Path:
    """Synthetic kunglao workspace mirroring the REAL PostToolUse fixture shape:
    claim-register.yaml + runs/worker-status-W-1.md + activated .hook_state.json."""
    path.mkdir(parents=True)
    (path / "runs").mkdir()
    (path / "claim-register.yaml").write_text(
        "claims:\n- id: C-203\n  status: OPEN\n", encoding="utf-8")
    line = ("[12:00] step: work done | status: done\n" if status == "done"
            else "[12:00] step: working | status: in-progress\n")
    (path / "runs" / "worker-status-W-1.md").write_text(line, encoding="utf-8")
    (path / ".hook_state.json").write_text(json.dumps({
        "tier": "none",
        "phase": "test",
        "expires_at": None,
        "active_hooks": ["worker_pulse"],
        "paused_hooks": [],
        "user_override": {},
    }), encoding="utf-8")
    return path


def _pulse_payload(ws: Path) -> dict:
    """Real PostToolUse(Agent) payload shape: cwd + tool_input.prompt carrying
    the kunglao dispatch prefix parsed by worker_pulse.DISPATCH_RE."""
    return {
        "hookEventName": "PostToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": "[T1 tools=basic] claim C-203: grep chemistry strings in main.main"},
    }


def _run_pulse(payload: dict) -> str:
    """Run hooks/worker_pulse.py exactly as wired (JSON payload on stdin)."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "worker_pulse.py")],
        input=json.dumps(payload), capture_output=True,
        encoding="utf-8", errors="replace",  # child output is UTF-8; never let locale break the capture
        env={"PYTHONIOENCODING": "utf-8", **os.environ},  # child prints UTF-8 regardless of runner locale
        cwd=str(ROOT), timeout=120,
    )
    return (r.stdout or "") + (r.stderr or "")


def test_worker_pulse_taskstop_reminder(tmp_path) -> None:
    """worker_pulse injects a TASKSTOP: reminder on a dispatch completion whose
    worker status file shows a final state (`status: done`); an in-progress
    worker produces no reminder (spec REQ-4 scenario)."""
    done_ws = _make_worker_ws(tmp_path / "done")
    out = _run_pulse(_pulse_payload(done_ws))
    assert "TASKSTOP:" in out, (
        "pulse output must carry a TASKSTOP: reminder for a delivered worker "
        f"(status: done). Got:\n{out}")
    assert "W-1" in out, f"TASKSTOP reminder must name the delivered worker. Got:\n{out}"
    # in-progress worker: no reminder
    live_ws = _make_worker_ws(tmp_path / "in-progress", status="in-progress")
    out2 = _run_pulse(_pulse_payload(live_ws))
    assert "TASKSTOP" not in out2, (
        "in-progress worker must NOT get a TASKSTOP reminder. Got:\n{out2}")


# ---------------------------------------------------------------------------
# 6-7. SendMessage ping retained in the heartbeat prompt / red-team agent
# ---------------------------------------------------------------------------

def test_heartbeat_prompt_sendmessage_allowed(tmp_path) -> None:
    """scripts/heartbeat_loop_prompt.py output KEEPS the SendMessage ping step
    (orchestrator→worker, smart-ping) with file-state accounting, and carries
    NO agent-team markers (spec REQ-3 scenario)."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "heartbeat_loop_prompt.py"), str(tmp_path / "ws")],
        capture_output=True, encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
        cwd=str(ROOT), timeout=60,
    )
    assert r.returncode == 0, f"heartbeat_loop_prompt.py failed: {r.stderr}"
    out = r.stdout or ""
    assert "SendMessage" in out, "heartbeat prompt must keep the SendMessage ping step"
    assert "ping" in out, "heartbeat prompt missing the ping step"
    assert ".ping-log.jsonl" in out, "heartbeat prompt missing file-state accounting (.ping-log.jsonl)"
    for marker in TEAM_MARKERS:
        assert marker not in out, f"heartbeat prompt must not carry agent-team markers ({marker})"


def test_redteam_agent_no_team_features() -> None:
    """agents/kunglao-redteam.md: no `- Task` disallowedTools entry and no
    agent-team wording; the verdict is delivered via the runs/ report file
    (dispatch return); SendMessage is neither instructed-to-remove nor banned
    (spec REQ-3 scenario)."""
    text = (ROOT / "agents" / "kunglao-redteam.md").read_text(encoding="utf-8")
    assert not re.search(r"^\s*-\s+Task\s*$", text, re.MULTILINE), (
        "kunglao-redteam must not carry a `- Task` disallowedTools entry")
    for bad in ("team setup", "teammate"):
        assert bad not in text, f"kunglao-redteam must not carry agent-team wording ({bad})"
    assert "runs/" in text, "kunglao-redteam must name its runs/ report file as the delivery channel"
    assert re.search(r"\bdeliver", text), (
        "kunglao-redteam must state the runs/ report file is the deliverable")
    assert "SendMessage is banned" not in text and "no SendMessage" not in text, (
        "kunglao-redteam must not ban SendMessage — it remains permitted, not instructed")


# ---------------------------------------------------------------------------
# 8. kunglao-monitor runs in the background, never blocking the tick
# ---------------------------------------------------------------------------

def test_monitor_background_note() -> None:
    """references/operational-mechanics.md states kunglao-monitor.py runs as a
    BACKGROUND process — it never blocks the loop's scheduled tick actions
    (re-dispatch / verify) (spec REQ-3 scenario)."""
    text = (ROOT / "references" / "operational-mechanics.md").read_text(encoding="utf-8")
    assert "kunglao-monitor" in text, (
        "operational-mechanics.md must name kunglao-monitor.py (background-process note)")
    assert "background" in text, (
        "operational-mechanics.md must state the monitor is a background process")
    assert "tick" in text, (
        "operational-mechanics.md must tie the background note to the loop tick")
    assert "never blocks" in text, (
        "the monitor note must state it never blocks the loop's scheduled tick actions")
