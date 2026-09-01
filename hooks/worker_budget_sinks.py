# -*- coding: utf-8 -*-
from __future__ import annotations

from worker_budget_core import (
    MAX_WORKERS, MAX_PROMOTION_ATTEMPTS, ENV_STATE_FILE, ENV_STATE_TTL_MINUTES,
    HOST_FORBIDDEN_TOOLS, TOOL_ERRORS_FILE, _SKILL_ROOT,
    VM_TOOLS, KNOWN_TOOLS,
    check_priority, check_plan_drift, check_convergence_health, check_backtrack_gate,
    parse_dispatch, detect_self_cap, scan_actual_tools,
    _ratio_rank, _EvidenceView, _PRIORITY_AVAILABLE,
    _tep, TOOL_ERROR_POLICY_LOADED, _ha_link, _klog,
    _load_yaml, _run_py, _atomic_write, read_active_workers,
)  # noqa: E402,F401
from worker_budget_core import check_claim_status_change  # noqa: E402,F401
from worker_budget_gates import (
    check_workers_lt_3, check_promotion_attempts, check_tools_allowed,
    check_host_forbidden_tools, check_deadline, check_tier_gate,
    check_no_self_cap, check_worker_plan, check_tool_first, check_agent_type,
    compare_register_change, compare_register_change_proven_gate,
    register_worker, remove_worker,
)  # noqa: E402,F401

import json
import re
import sys
import time
from pathlib import Path

"""worker_budget_sinks — Pre+Post ToolUse entry points (pre_check / post_check / main).

#568: extracted from worker_budget.py. Sinks orchestrate the gates over
Claude Code's hook payload and emit REJECT guidance via
hookSpecificOutput.additionalContext (#270)."""

# #235 added corrective guidance to env_check_gate only; worker_budget's 12
# pre_check gates (+ snapshot + devreason) REJECTed bare — `print REJECT + exit
# 2` with no hint on how to fix, and the user reported "the hook still just
# rejects outright without giving any hint" (原文 Chinese, 2026-08-13).
# Every REJECT now ALSO emits a
# hookSpecificOutput.additionalContext JSON on stdout with a concrete fix path
# (same dual channel as dispatch_gate.py:137-151 / env_check_gate.py:104-113).
# REJECT semantics are unchanged: exit 2 + stderr `REJECT <name>` summary.
# additionalContext is per-check, concrete and executable — never boilerplate.

REJECT_FIXES: dict[str, dict[str, str]] = {
    'workers': {
        'additionalContext': (
            'active workers >= MAX_WORKERS (3) - slot-full, the loop has no '
            'capacity for another worker. Fix: wait for an active worker to '
            'finish (runs/worker-status-*.md last status line = done), or '
            'TaskStop the stuck/retired worker to release a slot, then '
            're-dispatch.'
        ),
    },
    'cap': {
        'additionalContext': (
            'per-claim cost cap reached: promotion_attempts >= 3. Fix: STOP '
            're-dispatching this claim - re-dispatch keeps rejecting by design. '
            'Run uv run --project <skill> <skill>/scripts/failure_analysis_gate.py <ws> <claim> '
            '(answer the 3 questions), record the next method, then re-dispatch '
            '- or mark the claim DEFERRED / supersede it.'
        ),
    },
    'tools': {
        'additionalContext': (
            'a dispatched tool requires a task_spec constraint that is '
            'forbidden. Fix: dispatch with tools whose constraints are allowed '
            'only - vm_detonation=forbidden means static tools '
            '(grep / xxd / mcp__ghidra__*) and NO vmr-shell / rev-frida / '
            'mcp__x64dbg__*. To use VM tools, get user authorisation and set '
            'task_spec.constraints.vm_detonation: allowed first, then re-dispatch.'
        ),
    },
    'hostchan': {
        'additionalContext': (
            'host-channel dynamic tool forbidden (SKILL.md hard-prohibitions '
            '#5 - sample must never execute on the host). Fix: only '
            'mcp__x64dbg__connect_remote(host=192.168.20.128) is allowed - launch the '
            'VM-side x64dbg via vmr-shell first, then connect_remote; or '
            'rev-frida against the VM frida-server (192.168.20.128:1337). '
            'Never start_session / connect_to_session / connect_to_instance / '
            'terminate_session / frida spawn / frida attach.'
        ),
    },
    'deadline': {
        'additionalContext': (
            'time budget exhausted (now >= deadline_ts). Fix: the run is over '
            'budget - either close the run out (write closeout, mark claims '
            'accordingly), or get user approval to extend: write a new '
            'deadline_ts in analysis_state.txt (or raise '
            'task_spec.time_budget_minutes) and re-dispatch after the '
            'extension is in place.'
        ),
    },
    'tier': {
        'additionalContext': (
            'tier gate: tier=N dispatch requires every open claim at '
            'evidence_tier_attempted >= N-1. Fix: complete the lower-tier '
            'evidence first - raise the open claim\'s evidence_tier_attempted '
            'in claim-register.yaml by doing that tier\'s work (static/CTI '
            'before VM), then re-dispatch the tier=N claim.'
        ),
    },
    'selfcap': {
        'additionalContext': (
            'self-imposed time cap in the dispatch description but '
            'task_spec.time_budget_minutes=0/unset (contract: no budget until '
            'convergence). Fix: remove the cap wording from the dispatch '
            'description ("no self-cap" / "until closed"), or set '
            'task_spec.time_budget_minutes > 0 to authorise a ceiling - '
            'then re-dispatch.'
        ),
    },
    'heartbeat': {
        'additionalContext': (
            'heartbeat NOT registered / STALE - dispatching without monitoring '
            'is the #1 recurring failure. Fix BEFORE dispatching: run '
            'uv run --project <skill> <skill>/scripts/hook_activation.py <ws> --heartbeat-on, '
            'then register the cron (CronCreate */5 * * * * with the heartbeat '
            'loop prompt, or /loop 5m) so monitoring ticks before the worker '
            'starts.'
        ),
    },
    'drift': {
        'additionalContext': (
            'plan drift detected (plan files lag reality). Fix: run '
            'uv run --project <skill> <skill>/scripts/plan_drift_detector.py <ws> --active-only '
            'to list the drifted items, then update global_plan.txt and/or '
            'runs/plan-C*.md to match what the run actually does (new claim, '
            'dropped step, superseded plan) - record the deviation reasoning - '
            'and re-check before re-dispatching.'
        ),
    },
    'health': {
        'additionalContext': (
            'convergence loop unhealthy (STALLED / SPINNING). Fix: run '
            'uv run --project <skill> <skill>/scripts/convergence_health.py <ws> for the '
            'diagnostic - STALLED: re-prime the loop (workers/heartbeat alive? '
            'claim actually in progress?); SPINNING: STOP dispatching and '
            'reconcile what is being re-done (usually a missing '
            'verify/promote step) - collapse the spin, then resume.'
        ),
    },
    'backtrack': {
        'additionalContext': (
            'stuck worker(s) without a valid backtrack decision. Fix: append a '
            '"## backtrack" block to the stuck worker\'s '
            'runs/worker-status-*.md (decision: redispatch / escalate / '
            'retry_different + reason + new_approach), or resolve the stall '
            'directly, then re-run uv run --project <skill> <skill>/scripts/backtrack_gate.py '
            '<ws> to confirm clean before re-dispatching.'
        ),
    },
    'plan': {
        'additionalContext': (
            'plan-first gate (kunglao-worker.md golden rule #3: PLAN FIRST, '
            'execute second). Fix: write runs/plan-C<NN>.md '
            '(goal / preflight / steps / fallback) for claim C-<NN> BEFORE '
            'dispatching, or reference the plan path in the dispatch prompt '
            'when writing it in the same turn - then re-dispatch.'
        ),
    },
    'toolfirst': {
        'additionalContext': (
            'tool-first gate (#294): the dispatch text matches a registered '
            'tools/_INDEX.yaml entry but carries no `tool-catalog:` marker. '
            'Fix: read <skill>/tools/_INDEX.md -> pick the matching '
            '_index-<category>.md entry -> add `tool-catalog: <tool-name>` to '
            'the dispatch prompt (or `tool-catalog: none (reasoning: <why '
            'not>)` if the registered tool genuinely does not apply) - then '
            're-dispatch.'
        ),
    },
    'agenttype': {
        'additionalContext': (
            'specialist-first gate (#310): route_capability recommends a '
            'specialist agent for this claim (claim task domain x sample '
            'features vs the mechanical trigger table in agents/*.md '
            'frontmatter) but the dispatch sends a different work agent. Fix: '
            'run uv run --project <skill> <skill>/scripts/route_capability.py --features-file '
            '<probe.json> --claim <C-NN> --workspace <ws> --json, dispatch the '
            'recommended agent_type (ghidra-light / go-symbols / floss-filter '
            '/ pefile-signature / verdict-scorer), or add '
            '`agent-reasoning: <why this agent instead of the recommended '
            'specialist>` to the dispatch prompt - the deviation must be '
            'recorded, not silently mixed - then re-dispatch.'
        ),
    },
    'snapshot': {
        'additionalContext': (
            'anti state-loss marker missing (S1c v1.9.24). Fix: count facts/ '
            'first, then start the dispatch prompt with '
            '"facts-snapshot: N facts at <ts>" (e.g. '
            '"facts-snapshot: 9 facts at 2026-08-13T00:00Z") - the marker '
            'makes the pre-dispatch checkpoint verifiable - then re-dispatch.'
        ),
    },
    'devreason': {
        'additionalContext': (
            'priority deviation without justification (anti-spoof v1.9.24). '
            'Fix: add "agent-reasoning: <why C-<NN> instead of the ranked #1 '
            'C-<MM>>" to the dispatch prompt, or dispatch the top-ranked claim '
            'instead - the deviation must be recorded, not silently skipped.'
        ),
    },
    'envfresh': {
        'additionalContext': (
            'environment drift (v1.9.39, #475): a capability this dispatch '
            'needs is FAILED or STALE in runs/env-state.json (written by '
            'heartbeat_tick step 9). Fix in order: (1) L1 deterministic '
            'repair: uv run --project <skill> <skill>/scripts/env_repair_l1.py '
            '<ws> --all (idempotent; safe no-op without the device); (2) if '
            'STALE: run one heartbeat_tick to refresh the snapshot, then '
            're-dispatch; (3) if L1 cannot repair (VM lease gone), fix the '
            'root cause (re-lease the VM / re-attach the device) and re-init.'
        ),
    },
}


def _reject(name: str, msg: str, paths: dict) -> int:
    """REJECT with guidance (issue #270): stderr summary + stdout JSON
    hookSpecificOutput.additionalContext. Exit 2 semantics unchanged."""
    print(f'REJECT {name}: {msg}', file=sys.stderr)
    entry = REJECT_FIXES.get(name)
    if not entry:
        return 2
    fix = entry['additionalContext']
    fix = fix.replace('<skill>', str(_SKILL_ROOT)).replace('<ws>',
                                                           paths.get('workspace') or '<ws>')
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'additionalContext': (
                f'worker_budget REJECT {name}: {msg}\n\n'
                f'How to fix:\n{fix}'
            ),
        },
    }, ensure_ascii=False))
    return 2


# ---------- hook entry ----------

def check_heartbeat_alive(state_path: Path) -> tuple[bool, str]:
    """v1.9.28: a dispatch REQUIRES a live heartbeat (mechanical gate).

    The #1 recurring failure (2026-08-03/04, third recurrence across
    v1.9.12/13/18/25/26): orchestrator dispatches a worker/verifier but
    forgets to register the /loop heartbeat cron -> monitoring never starts
    -> 'slots empty, no monitoring' user report. Every prior fix was a SOFT
    constraint ('orchestrator should self-schedule', 'Phase 0 generates the
    prompt') — soft constraints lose to context-forgetting every time (new
    session / CONVERGED / closeout phase). This is the MECHANICAL gate: a
    dispatch with no live .heartbeat.json is REJECTED, forcing the
    orchestrator to register monitoring BEFORE dispatch. Closes the
    soft-constraint gap that prior versions could not.

    #754 E2: 'alive' is now CONTINUITY-based via the shared evaluator
    (scripts/heartbeat.py::evaluate_tick_continuity): >= 2 ticks, adjacent
    gaps <= 2x interval_min, newest <= 35 min. The live-run incident (#754)
    proved single-tick liveness blind: last_tick_ts == started_ts for the
    whole session life with no cron behind it still passed inside the
    window. #533 F-H2 semantics kept: TICK data only — activity_ts stays
    the kicker's signal; and no cross-workspace masking beyond the original
    cwd-side -> skill-install-dir probe (F-H3 posture).
    """
    from _path_hygiene import ensure_scripts_path  # #671 sys.path authority
    ensure_scripts_path()
    from heartbeat import evaluate_tick_continuity  # noqa: E402

    if not state_path.exists():
        return True, 'no kunglao-agent workspace - heartbeat gate skipped'
    hb = state_path.parent / 'runs' / '.heartbeat.json'
    hb_skill = Path(__file__).resolve().parents[1] / 'runs' / '.heartbeat.json'

    def _load(hb_path: Path):
        try:
            return json.loads(hb_path.read_text(encoding='utf-8'))
        except Exception:
            return None

    data = _load(hb) if hb.exists() else None
    ws_log = hb.parent / '.heartbeat.log'
    ws_alive, ws_detail = (evaluate_tick_continuity(data, log_path=ws_log)
                           if data else (False, ''))
    if ws_alive:
        return (True, f'heartbeat alive ({ws_detail})')
    if hb_skill.exists():
        sk_data = _load(hb_skill)
        if sk_data:
            sk_alive, sk_detail = evaluate_tick_continuity(
                sk_data, log_path=hb_skill.parent / '.heartbeat.log')
            if sk_alive:
                return (True, f'heartbeat alive ({sk_detail})')
            ws_detail = ws_detail or sk_detail
        elif ws_detail == '':
            ws_detail = f'skill-side {hb_skill.name} unreadable'
    if data is None and not hb.exists() and not hb_skill.exists():
        return (False,
                'heartbeat NOT registered. BEFORE dispatching, run:\n'
                '  uv run --project <skill> <skill>/scripts/hook_activation.py <ws> --heartbeat-on\n'
                '  CronCreate */5 * * * * <heartbeat_loop_prompt.py output>\n'
                '#754: register it DURABLE (<ws>/.claude/scheduled_tasks.json via '
                '/kunglao-agent:init or loop_scheduler.py) - session-only crons '
                'die with the process.')
    detail = ws_detail or ('heartbeat file unreadable / no parseable timestamps - '
                           're-register with hook_activation.py <ws> --heartbeat-on')
    return (False, f'#754 continuous-tick liveness REJECT - {detail}')


# module-level timedelta for the gate (datetime itself stays local-import,
# same convention as check_heartbeat_alive)
from datetime import timedelta as _env_timedelta  # noqa: E402

# which env capabilities a dispatch actually needs: VM-channel tools and any
# tier>=2 dynamic work (T2/T3 run in the VM / on-device per the tier ladder).
_ENV_CAP_FOR_TOOL_PREFIX = (
    'mcp__ghidra__',      # decompiler MCP — bridge liveness
    'mcp__x64dbg__',      # remote debugger — VM channel
)


def _env_caps_needed(tier: int, tools: list[str]) -> set[str]:
    """Env capabilities this dispatch depends on (vm_reachable for VM-channel
    tools / tier>=2; mcp_bridge for MCP decompiler tools)."""
    caps: set[str] = set()
    if tier >= 2:
        caps.add('vm_reachable')
    for t in tools:
        if t in VM_TOOLS or t.startswith('mcp__x64dbg'):
            caps.add('vm_reachable')
        if t.startswith(_ENV_CAP_FOR_TOOL_PREFIX[0]) or t.startswith('mcp__ida'):
            caps.add('mcp_bridge')
        # #474 follow-up: jdb/jdwp-driving tools gate on the jdwp capability
        if 'jdwp' in t or 'jdb' in t:
            caps.add('jdwp_debug')
    return caps


def check_env_fresh(paths: dict, tier: int = 0, tools: list[str] | None = None) -> tuple[bool, str]:
    """#475: three-state env-state freshness gate — PURE FILE READ (<5ms).

    Missing/corrupt env-state.json -> FAIL_OPEN + hint (env freshness is
    new; pre-existing workspaces must not start failing). Explicit FAIL on a
    capability this dispatch needs -> REJECT with L1 repair guidance. Any
    needed entry older than 2x TTL -> REJECT with the self-heal hint (run
    one heartbeat_tick — step 9 refreshes the snapshot by construction).
    """
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    from datetime import datetime, timezone
    p = Path(ws) / ENV_STATE_FILE
    if not p.exists():
        return True, ('no runs/env-state.json — env freshness unverified; '
                      'one heartbeat_tick (step 9) writes it, or re-init')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        # #475 review HIGH-1: valid JSON of the WRONG SHAPE (list top-level,
        # string entries) parses fine then crashes on .get — guard both.
        if not isinstance(data, dict):
            raise ValueError('env-state.json top level is not an object')
        per = data.get('per_capability') or {}
        if not isinstance(per, dict):
            raise ValueError('per_capability is not an object')
    except (OSError, ValueError, json.JSONDecodeError):
        return True, 'env-state.json unreadable/malformed — fail open (run a heartbeat_tick to rewrite)'
    needed = _env_caps_needed(tier, tools or [])
    if not needed:
        return True, ''
    now = datetime.now(timezone.utc)
    stale_line = _env_timedelta(minutes=ENV_STATE_TTL_MINUTES * 2)
    for cap in sorted(needed):
        entry = per.get(cap)
        if not entry or not isinstance(entry, dict):
            continue  # unprobed or wrong-shape — not evidence, fail open
        if entry.get('status') == 'fail':
            return (False,
                    f'env drift: {cap} FAIL ({(entry.get("detail") or "")[:120]}) - '
                    f'run L1 repair: uv run --project <skill> <skill>/scripts/env_repair_l1.py <ws> --all')
        ts = entry.get('last_probe_ts', '')
        try:
            age = now - datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except ValueError:
            continue  # unparseable ts — not evidence of drift; fail open
        if age > stale_line:
            return (False,
                    f'env-state STALE: {cap} last probe {int(age.total_seconds()//60)} min ago '
                    f'(> {ENV_STATE_TTL_MINUTES * 2}) - run one heartbeat_tick to refresh, then re-dispatch')
    return True, ''


def _dispatch_lifecycle(paths: dict, tier: int, tools: list[str],
                        cid: str | None, agent_name: str) -> None:
    """#461: apply the dispatch linkage at the approval point — renew the
    activation TTL (auto --renew), complete the active set, flip phase to
    DISPATCH (via hook_activation.dispatch_linkage), and append the
    dispatch event to the unified log (kunglao_log.emit, #459 target).

    Fail-open with a stderr WARN: linkage is liveness/observability and
    must not block an already-approved dispatch. The fail-CLOSED side is
    the TTL itself — if the linkage stops working, the activation expires
    within 30 min and the sleeping hooks reject further dispatches.
    """
    ws = paths.get('workspace')
    if not ws:
        return
    ws_path = Path(ws)
    try:
        if _ha_link is not None:
            _ha_link.dispatch_linkage(ws_path)
        if _klog is not None:
            _klog.emit(
                ws_path, 'hook:worker_budget', 'dispatch', claim=cid,
                detail=f'tier={tier} tools={",".join(tools)} '
                       f'agent={agent_name or "?"} (#461 linkage: renew + '
                       f'arm + phase=DISPATCH)')
    except Exception as exc:  # noqa: BLE001 - linkage never blocks dispatch
        print(f'[kunglao-agent] dispatch linkage WARN (fail-open): '
              f'{type(exc).__name__}: {exc}', file=sys.stderr)


def pre_check(payload: dict, paths: dict) -> int:
    desc = payload.get('tool_input', {}).get('description', '')
    prompt = payload.get('tool_input', {}).get('prompt', '')
    agent_name = payload.get('tool_input', {}).get('name') or ''
    # #862: the dispatch shape belongs to the contract channel (prompt,
    # protocol v1 JSON envelope; v1-first per #861 single-source). The
    # description channel is deprecated replay-only — a shape found there
    # is exactly the B4 silent-dead-gates posture -> fail-closed.
    tier, tools, cid = parse_dispatch(prompt)
    if (tier, tools, cid) == (0, [], None):
        _d_tier, _d_tools, d_cid = parse_dispatch(desc)
        if d_cid:
            return _reject('devchannel',
                           'dispatch shape found in the deprecated '
                           'description channel - protocol v1 requires the '
                           'kunglao_dispatch JSON envelope in the prompt '
                           '(B4/#862).', paths)
    checks = [
        ('workers', check_workers_lt_3(paths)),
        ('cap', check_promotion_attempts(paths['register'], cid)),
        ('tools', check_tools_allowed(tools, paths['task_spec'])),
        ('hostchan', check_host_forbidden_tools(tools)),
        ('deadline', check_deadline(paths['state'])),
        ('tier', check_tier_gate(paths['register'], tier)),
        ('selfcap', check_no_self_cap(desc, paths['task_spec'])),
        # v1.9.28: heartbeat MUST be alive before any dispatch — mechanical
        # gate closes the recurring 'dispatch without monitoring' failure.
        ('heartbeat', check_heartbeat_alive(paths['state'])),
        # v1.9.29: plan drift + convergence health wired in as mechanical
        # gates (historical research-tree r3, R1/R3). FAIL_OPEN inside the checks.
        ('drift', check_plan_drift(paths)),
        ('health', check_convergence_health(paths)),
        # v1.9.39 (#475): env-state freshness gate — a dispatch whose tier/
        # tools need a drifted environment capability is REJECTED; missing/
        # stale-beyond-2xTTL state follows the FAIL_OPEN/self-heal split
        # (see check_env_fresh). Pure file read (<5ms), no subprocess.
        ('envfresh', check_env_fresh(paths, tier, tools)),
        # v1.9.29 (#38): stuck-worker backtrack gate — closes the
        # built-but-not-wired gap (backtrack_gate.py existed but was never
        # called from pre_check). FAIL_OPEN; rc 1/2 -> REJECT.
        ('backtrack', check_backtrack_gate(paths)),
        # v1.9.31 (#239): plan-to-execute gate — a claim dispatch REQUIRES
        # runs/plan-C<NN>*.md on disk OR a plan path for that claim in the
        # dispatch prompt (timing relaxation). Closes the 2026-08-12
        # F006-F008 accident: inference written as facts — the plan phase
        # exposes it before execution.
        ('plan', check_worker_plan(paths, cid, prompt)),
        # v1.9.32 (#294): tool-first gate — a dispatch whose text matches a
        # registered tools/_INDEX.yaml keyword must cite it (`tool-catalog:`)
        # or explicitly opt out with reasoning. Closes the Swiss-army-test gap
        # where a passing plan gate still let a worker hand-roll a script
        # instead of trying crypto-tool.py for a crypto-decode task.
        ('toolfirst', check_tool_first(paths, desc, prompt)),
        # v1.9.33 (#310): agenttype gate — specialist-first as a mechanical
        # check. route_capability recommends the specialist for the claim
        # (task domain x sample features); a deviating dispatch REJECTS
        # without `agent-reasoning:` (same anti-spoof shape as devreason).
        ('agenttype', check_agent_type(paths, cid, prompt, agent_name)),
    ]
    for name, (ok, msg) in checks:
        if not ok:
            return _reject(name, msg, paths)
    # §1c v1.9.24 — facts-snapshot marker HARD-REQUIRED (anti state-loss spoof).
    # The orchestrator claims it "ls facts/ before dispatch" (§1c) — make it
    # verifiable: the dispatch prompt must carry `facts-snapshot:` (e.g.
    # "facts-snapshot: 9 facts at <ts>") or the dispatch is REJECTED.
    desc = payload.get('tool_input', {}).get('prompt', '')
    if 'facts-snapshot:' not in desc:
        return _reject('snapshot',
                       'dispatch prompt lacks `facts-snapshot:` marker '
                       '(S1c v1.9.24 - checkpoint state before dispatch).', paths)
    # best-first priority audit — v1.9.24: DEVIATION REASONING IS HARD-REQUIRED.
    # check_priority returns (ok, msg, deviated). If the dispatch deviates from
    # the ranked #1 claim, the prompt MUST carry an explicit `reasoning:` field —
    # otherwise the dispatch is REJECTED (prevents "pretend-priority" spoofing:
    # dispatching a different claim without recording why).
    _pok, pmsg, deviated = check_priority(paths.get('register'), paths.get('deps'), paths.get('task_spec'), cid, paths.get('workspace'))
    if deviated:
        desc = payload.get('tool_input', {}).get('prompt', '')
        if 'agent-reasoning:' not in prompt:
            return _reject('devreason',
                           'dispatch deviates from priority #1 but has no '
                           '`agent-reasoning:` field (v1.9.24 anti-spoof). '
                           f'PRIORITY: {pmsg}', paths)
        print(f'PRIORITY (deviated w/ reasoning): {pmsg}', file=sys.stderr)
    elif pmsg:
        print(f'PRIORITY: {pmsg}', file=sys.stderr)
    worker_id = agent_name or f'w{int(time.time())}'
    # #461: a PASSING dispatch is a lifecycle event — renew TTL / complete
    # the activation set / flip phase to DISPATCH / log the dispatch event
    # (fail-open inside; rejected dispatches above never reach this line).
    _dispatch_lifecycle(paths, tier, tools, cid, agent_name)
    register_worker(paths['state'], {
        'worker_id': worker_id,
        'claim_id': cid or '',
        'dispatched_at': int(time.time()),
        'tier': tier,
        'tools': tools,
    })
    return 0


def _apply_tool_error_policy(paths: dict, tool_result: str) -> None:
    """#475: count per-tool consecutive failures in the worker transcript
    result and apply the hysteresis policy (single source: tool_error_policy).

    Detection: an `mcp__<name>__<op> ...: Error: ...` line = one failing
    invocation of that tool; a line naming the tool without an Error marker =
    success (streak reset). State persists in runs/tool-errors.json. WARN →
    stderr advisory; disable_escalate → stderr escalation + the env-state
    entry for the tool's capability is marked failed (repair-ladder input).
    All IO failures fail open (policy must not break post_check).
    """
    if _tep is None:
        return
    ws = paths.get('workspace')
    if not ws:
        return
    runs = Path(ws) / 'runs'
    state_path = runs / 'tool-errors.json'
    try:
        state = json.loads(state_path.read_text(encoding='utf-8')) \
            if state_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    events = []
    for line in tool_result.splitlines():
        low = line.strip()
        m = re.match(r'((?:mcp__)?[a-z0-9_\-]+)', low)
        if not m:
            continue
        tool = m.group(1)
        # only actual tool invocations count — an mcp__ name or a KNOWN_TOOLS
        # entry; a generic word starting an error line must not build a
        # phantom streak ("attempt 3: Error: ..." ≠ tool 'attempt').
        if not (tool.startswith('mcp__') or tool in KNOWN_TOOLS):
            continue
        events.append((tool, 'error' in low.lower() and ':' in low))
    for tool, failed in events:
        rec = state.get(tool) or {'consecutive_failures': 0}
        rec['consecutive_failures'] = 0 if not failed else rec['consecutive_failures'] + 1
        state[tool] = rec
        if not failed:
            continue
        r = _tep.evaluate_streak(rec['consecutive_failures'], tool=tool)
        if r['action'] == 'warn':
            print(f'[kunglao-agent] tool-error WARN: {r["message"]} — switch '
                  f'approach or repair the environment', file=sys.stderr)
        elif r['action'] == 'disable_escalate':
            print(f'[kunglao-agent] tool-error DISABLE: {r["message"]} '
                  f'({r.get("blocker_note", "")})', file=sys.stderr)
            _mark_env_capability_failed(runs, tool)
    try:
        runs.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except OSError:
        pass  # persistence failure: this tick's advisory already went to stderr


def _mark_env_capability_failed(runs: Path, tool: str) -> None:
    """disable_escalate side effect: flip the env-state entry for the tool's
    capability to fail, so check_env_fresh + env_drift_watch + env_repair_l1
    all see the drift through the single env-state source."""
    env_path = runs / 'env-state.json'
    # tool name → env capability (same vocabulary as check_env_fresh /
    # env_state_probe): decompiler MCPs hit mcp_bridge, VM-channel tools hit
    # vm_reachable, anything else records under the tool itself so the
    # disable is at least visible in env-state.
    if tool.startswith(('mcp__ghidra', 'mcp__ida')):
        cap = 'mcp_bridge'
    elif tool in VM_TOOLS or tool.startswith('mcp__x64dbg'):
        cap = 'vm_reachable'
    else:
        cap = f'tool:{tool}'
    try:
        data = json.loads(env_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return  # no env-state: the tick will write one; nothing to flip
    import datetime as _dt
    entry = data.setdefault('per_capability', {}).setdefault(cap, {})
    entry.update({
        'status': 'fail',
        'last_probe_ts': _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec='seconds').replace('+00:00', 'Z'),
        'detail': f'tool {tool} disabled after consecutive errors (hysteresis)',
    })
    try:
        env_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except OSError:
        pass


def post_check(payload: dict, paths: dict) -> int:
    worker_id = payload.get('tool_input', {}).get('name') or ''
    if worker_id:
        remove_worker(paths['state'], worker_id)
    tool_result = str(payload.get('tool_result', ''))
    scan_actual_tools(tool_result)  # post-hoc audit (informational)
    # #475: same-tool consecutive-error hysteresis — the #309 policy's first
    # mechanical consumer (warn at 3, disable+escalate at 5, success resets).
    _apply_tool_error_policy(paths, tool_result)
    # ---- v1.9.29 claim-status guard: block worker self-promotion ----
    # A worker must NOT flip a claim to terminal status (PROVEN / NEGATIVE /
    # REFUTED / DEFERRED) — only the orchestrator promotes after the
    # kunglao-redteam adversarial pass. Detect here by checking the dispatched
    # claim's status: if a worker completed and the register shows its claim
    # in a terminal status without a redteam record, that is a self-promotion.
    reg = paths['register']
    agent_name = payload.get('tool_input', {}).get('name') or ''
    if agent_name and reg.exists():
        ok, reason = check_claim_status_change(reg, agent_name)
        if not ok:
            # Log only — the write already happened; the orchestrator's
            # convergence loop treats terminal-without-redteam as STAMP.
            print(f'[kunglao-agent] {reason}', file=sys.stderr)
        # F-B3 (#532): the PROVEN backstop stops being dead code. Unlike
        # check_claim_status_change (log-only, orchestrator-exempt), this
        # gate applies to ALL actors: a newly-PROVEN claim needs BLIND
        # sign-off, period. It is the LAST line of defense behind
        # write_guard — an agent that edits claim-register.yaml through a
        # path the PreToolUse matcher never saw still lands here on the
        # PostToolUse face. The before-snapshot comes from the payload's
        # register_before (populated by the write-guard shadow pipeline /
        # the orchestrator's own pre-dispatch record) or, absent that, the
        # LAST recorded statuses — before=None is the gate's no-op branch,
        # not its happy path, so a real before is always preferred.
        before = payload.get('register_before')
        if before is None:
            before = _register_before_from_state(paths)
        facts_dir = Path(paths.get('workspace') or reg.parent) / 'facts'
        proven_ok, proven_reason = compare_register_change_proven_gate(
            reg, before, agent_name, facts_dir)
        if not proven_ok:
            print(proven_reason, file=sys.stderr)
            _emit_gate_event(paths, 'write_blocked',
                             detail=proven_reason, exit=2)
            return 2
    return 0


def _register_before_from_state(paths: dict) -> dict[str, str] | None:
    """F-B3 (#532) before-snapshot fallback: the LAST record of each claim's
    status that is not the register's CURRENT content — i.e. what a prior
    pre_check/post_check snapshot stashed in runs/.register-snapshot.json.

    Returns None when no prior snapshot exists (the gate's no-before branch:
    the promotion comparison cannot run without a baseline; write_guard's
    shadow pipeline supplies the real one on the write face)."""
    ws = paths.get('workspace')
    if not ws:
        return None
    snap = Path(ws) / 'runs' / '.register-snapshot.json'
    if not snap.exists():
        return None
    try:
        return json.loads(snap.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _emit_gate_event(paths: dict, action: str, *, detail: str, exit: int) -> None:
    """#532 item 5: gate refusals in this hook are observable too.

    Never raises — logging must never break enforcement (kunglao_log.emit
    itself degrades to a stderr warning on write failure)."""
    ws = paths.get('workspace')
    if not ws:
        return
    try:
        import kunglao_log
        kunglao_log.emit(Path(ws), actor='hook', action=action,
                         exit=exit, detail=str(detail)[:2000])
    except Exception:  # noqa: BLE001 - logging never breaks enforcement
        pass


def _resolve_paths(payload: dict) -> dict:
    ws = Path(payload.get('cwd') or payload.get('workspace') or '.')
    candidates = [ws / 'malware-analysis-workspace', ws]
    for base in candidates:
        if (base / 'analysis_state.txt').exists():
            return {
                'workspace': str(base),
                'state': base / 'analysis_state.txt',
                'register': base / 'claim-register.yaml',
                'deps': base / 'claim_deps.yaml',
                'task_spec': base / 'task_spec.yaml',
            }
    base = candidates[0]
    return {
        'workspace': str(base),
        'state': base / 'analysis_state.txt',
        'register': base / 'claim-register.yaml',
        'deps': base / 'claim_deps.yaml',
        'task_spec': base / 'task_spec.yaml',
    }


def main() -> int:
    payload = json.load(sys.stdin)
    paths = _resolve_paths(payload)
    event = payload.get('hook_event') or payload.get('hook_event_name', '')
    if 'Post' in event:
        return post_check(payload, paths)
    return pre_check(payload, paths)


if __name__ == '__main__':
    sys.exit(main())
