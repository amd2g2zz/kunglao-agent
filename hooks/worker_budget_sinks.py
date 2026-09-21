# -*- coding: utf-8 -*-
from __future__ import annotations



# issue 275 batch-3: fail-open handlers keep their liveness posture (never
# raise, never change the return shape) but must leave ONE trace - a stderr
# WARN naming the operation + reason, rate-limited to once per op until the
# reason changes (the _zof_warn pattern of issue 276; one ws per process,
# so op is the key).
import sys
_B3_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _B3_WARN_LAST.get(op) == reason:
        return
    _B3_WARN_LAST[op] = reason
    print(f"[kunglao-agent] worker_budget_sinks WARN (fail-open): "
          f"{op}: {reason}",
          file=sys.stderr)
from worker_budget_core import (  # noqa: F401 — broad re-export surface:
    # worker_budget.py aggregator + tests consume these via module attrs
    MAX_WORKERS, MAX_PROMOTION_ATTEMPTS, ENV_STATE_FILE, ENV_STATE_TTL_MINUTES,
    HOST_FORBIDDEN_TOOLS, TOOL_ERRORS_FILE, _SKILL_ROOT,
    VM_TOOLS, KNOWN_TOOLS,
    check_priority, check_plan_drift, check_convergence_health, check_backtrack_gate,
    parse_dispatch, detect_self_cap, scan_actual_tools,
    load_hooks_lib,
    _ratio_rank, _EvidenceView, _PRIORITY_AVAILABLE,
    _tep, TOOL_ERROR_POLICY_LOADED, _ha_link, _klog,
    _load_yaml, _run_py, _atomic_write, read_active_workers,
)  # noqa: E402,F401
from worker_budget_core import check_claim_status_change  # noqa: E402,F401
from worker_budget_gates import (
    check_workers_lt_3, check_promotion_attempts, check_tools_allowed,
    check_host_forbidden_tools, check_deadline, check_tier_gate,
    check_no_self_cap, check_worker_plan, check_tool_first, check_agent_type,
    check_claim_granularity,  # #241: plan-size / domain-span gate
    check_tool_search_citation,  # issue 243: tool-search citation beat (plan-check point)
    check_handroll_floor,  # issue 243: >50-line script vs available-CLI WARN floor
    record_tool_search_citations,  # issue 243: cited --find results -> provenance rows
    compare_register_change,  # noqa: F401 — re-exported to worker_budget aggregator
    compare_register_change_proven_gate,
    check_zero_output_circuit,  # #256: A4 thrash breaker in the production battery
    register_worker, remove_worker,
    stamp_dispatch_anchor,  # #57 gate 3: per-dispatch nonce at the approval point
    toolfirst_pass_record,  # #880 approval-point pass face + operation label
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

# #55 XML injection standard: gate verdicts are producer-attributed — the
# guidance text is wrapped in <gate-verdict>...</gate-verdict> at the
# emission site (_reject) so the agent can tell a kunglao gate verdict from
# third-party tool output (references/contracts/xml-injection-standard.md). Tags mark,
# they never gate: rc and payload shape unchanged; stderr stays untagged.
GATE_VERDICT_TAG = "gate-verdict"


def _gate_verdict(text: str) -> str:
    """Wrap one gate verdict face in the #55 producer tag."""
    return f"<{GATE_VERDICT_TAG}>\n{text}\n</{GATE_VERDICT_TAG}>"


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
            'and re-check before re-dispatching. The gate verifies the '
            'amendment (issue-281): the same drift persisting 3 detection '
            'rounds emits a plan_repair_overdue escalation.'
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
    'zerooutput': {
        'additionalContext': (
            'zero-output circuit tripped (v1.9.40, #256): the dispatch '
            'would repeat a same-family action fingerprint that hit N '
            'consecutive checkpoints with no belief change on THIS claim '
            '(facts/_INDEX.md + claim-register.yaml content). Fix: run '
            'uv run --project <skill> <skill>/scripts/failure_analysis_gate.py <ws> <claim> '
            '(answer the 3 questions), record the next method — the '
            'block clears itself once the workspace belief moves (the '
            'gate re-checks freshness every dispatch), or remove '
            'runs/zero-output-fingerprint.json as the last-resort escape '
            'hatch — then re-dispatch a DIFFERENT action family.'
        ),
    },
    'plan': {
        'additionalContext': (
            'plan-first gate (#239 v2: dispatch carries intent, not a plan — '
            'planning is the worker\'s first act of execution). This is a '
            'RE-dispatch: the claim already had an approved dispatch, so it '
            'needs its plan reference. Fix: let the WORKER author '
            'runs/plan-C<NN>.md (goal / preflight / steps / fallback) in its '
            'own session — its first sanctioned write — citing its '
            'per-dispatch anchor with a `dispatch-anchor: <dispatch_ts from '
            'the KUNGLAO_DISPATCH_CONTEXT block>` line (worker-authored '
            'provenance, #57 gate 3), or reference the worker-authored plan '
            'path in the dispatch prompt (re-dispatch continuity only) - '
            'then re-dispatch.'
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
    'granularity': {
        'additionalContext': (
            'granularity gate (#241: claim granularity discipline). This '
            'claim\'s worker-authored plan is monolithic — exceeds '
            'GRANULARITY_MAX_STEPS=8 enumerated steps or spans multiple '
            'mechanism domains (a monolithic claim degrades every downstream '
            'channel: spawn-recall, evidence verification, per-unit '
            'settlement, TS pricing). Fix: run '
            'uv run --project <skill> <skill>/scripts/claim_granularity.py '
            '<ws> --split <C-NN> (the #234 fan-out at creation time: mints '
            'domain sub-claims with depends_on edges + domain_family tags, '
            'each unit under K steps; the parent is marked SUPERSEDED with '
            'superseded_by = the sub-claim ids so the sub-claims enter the '
            'dispatchable pool), then dispatch the SUB-claims. The stderr '
            'message names the observed split (which steps belong to which '
            'family).'
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
    hookSpecificOutput.additionalContext. Exit 2 semantics unchanged.

    #55: the guidance lands in agent context wrapped in
    <gate-verdict>...</gate-verdict> — verdict + repair path read as one
    producer-attributed unit (references/contracts/xml-injection-standard.md). The
    tag is applied HERE, at the emission site, so the REJECT_FIXES table
    and the stderr summary stay raw. Tags mark, never gate: rc=2 unchanged.
    """
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
            'additionalContext': _gate_verdict(
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


def _declared_trace_id(prompt: str) -> str | None:
    """#879: the v1 envelope's optional `trace_id` (meta passthrough), or
    None. Format-invalid declarations degrade to None (the dispatch row stays
    un-attributed — honest; dispatch_gate's WARN face covers the drift)."""
    try:
        lib = load_hooks_lib()
        meta = lib.parse_dispatch_json(prompt or "")[3]
        v = meta.get("trace_id") if isinstance(meta, dict) else None
        if isinstance(v, str):
            if _klog is not None:
                return v if _klog.TRACE_ID_RE.match(v) else None
            import re as _re
            return v if _re.match(r"^tr-[a-z0-9][a-z0-9._-]*-\d+$", v) else None
    except Exception:  # noqa: BLE001 - linkage never blocks dispatch
        return None
    return None


def _dispatch_lifecycle(paths: dict, tier: int, tools: list[str],
                        cid: str | None, agent_name: str,
                        prompt: str = '') -> None:
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
                trace_id=_declared_trace_id(prompt),
                detail=f'tier={tier} tools={",".join(tools)} '
                       f'agent={agent_name or "?"} (#461 linkage: renew + '
                       f'arm + phase=DISPATCH)')
    except Exception as exc:  # noqa: BLE001 - linkage never blocks dispatch
        print(f'[kunglao-agent] dispatch linkage WARN (fail-open): '
              f'{type(exc).__name__}: {exc}', file=sys.stderr)


def _resolve_dispatch_agent(payload: dict, prompt_text: str) -> str | None:
    """#237 H1: agent resolver single-sourced with dispatch_gate's D2 face
    (lib_kunglao.resolve_dispatch_agent, all payload shapes). The #461
    corroboration row must name the same agent the pass-through faces
    resolved, or plan_drift_detector's D3 marker check can never
    corroborate the dispatch (subagent_type-shaped dispatches used to
    resolve to `agent=?` here)."""
    try:
        return load_hooks_lib().resolve_dispatch_agent(payload, prompt_text)
    except Exception:  # noqa: BLE001 - identity best-effort, row stays ?-marked
        return None


def _is_verifier_remediation_dispatch(ws, claim_id: str, payload: dict,
                                      prompt_text: str) -> bool:
    """#237 D2: same predicate as dispatch_gate's drift pass-through (lib
    single source). worker_budget's own pre_check drift gate rides the SAME
    dispatch and must reach the identical verdict, or the honest remediation
    path deadlocks at the second hook. Lib outage -> False (legacy drift
    gate applies — an unavailable resolver must not newly open the gate)."""
    try:
        return load_hooks_lib().is_verifier_remediation_dispatch(
            ws, claim_id, payload, prompt_text)
    except Exception:  # noqa: BLE001 — degraded copy: legacy gate applies
        return False


def pre_check(payload: dict, paths: dict) -> int:
    desc = payload.get('tool_input', {}).get('description', '')
    prompt = payload.get('tool_input', {}).get('prompt', '')
    agent_name = payload.get('tool_input', {}).get('name') or ''
    # #237 H1: the #461 corroboration row's agent identity is resolved by
    # the shared resolver (all payload shapes), NOT by the legacy name-only
    # read above — that split left subagent_type-shaped dispatches with
    # `agent=?` in the row, so D3's marker check never corroborated them
    # and the deadlock survived the pass-through for that shape. The gate
    # inputs (agenttype / worker_id) keep the legacy value: their contracts
    # are unchanged by this card.
    row_agent = _resolve_dispatch_agent(payload, prompt) or agent_name or '?'
    verifier_remediation = False  # set after the dispatch parse (needs cid)
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
    # #237 D2: verifier pass-through — a kunglao-redteam / verdict-scorer
    # dispatch for a PROVEN claim IS the flagged UNVERIFIED_EVIDENCE set's
    # remediation; this hook's own drift gate must allow it too (the
    # dispatch_gate face alone left the honest path blocked here, and the
    # #461 corroboration row could never be written through a rejected
    # dispatch).
    verifier_remediation = _is_verifier_remediation_dispatch(
        paths.get('workspace'), cid, payload, prompt)
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
        # #237 D2: skipped for verifier-remediation dispatches (verifier +
        # PROVEN claim) — this gate must not reject the remediation it
        # exists to demand.
        ('drift', (True, '') if verifier_remediation
         else check_plan_drift(paths)),
        # #249: the dispatch context rides along so the STALLED rc=1 face
        # can admit the gate's own prescribed remedy (mirror of the D2
        # drift skip above — same dispatch, both faces must agree). The
        # exemption is INSIDE the rc=1 face: SPINNING/crash faces are
        # untouched, and every other gate below still applies to a remedy
        # dispatch.
        ('health', check_convergence_health(paths, cid, payload, prompt)),
        # v1.9.39 (#475): env-state freshness gate — a dispatch whose tier/
        # tools need a drifted environment capability is REJECTED; missing/
        # stale-beyond-2xTTL state follows the FAIL_OPEN/self-heal split
        # (see check_env_fresh). Pure file read (<5ms), no subprocess.
        ('envfresh', check_env_fresh(paths, tier, tools)),
        # v1.9.29 (#38): stuck-worker backtrack gate — closes the
        # built-but-not-wired gap (backtrack_gate.py existed but was never
        # called from pre_check). FAIL_OPEN; rc 1/2 -> REJECT.
        ('backtrack', check_backtrack_gate(paths)),
        # v1.9.40 (#256): zero-output circuit — the A4 thrash breaker
        # graduates from shadow to the production battery (the canary
        # graduation its own module promised). A tripped fingerprint (>=
        # ZERO_OUTPUT_N same-family actions, no belief change) REJECTs a
        # dispatch that would REPEAT that (claim, tool-family) — other
        # claims/families pass. The gate derives belief freshness ITSELF
        # (stale ledger = reset), so a moved workspace can never stay
        # blocked; missing/unreadable state FAILS OPEN. post_check feeds
        # the streaks it reads (see _record_zero_output_fingerprint).
        ('zerooutput', check_zero_output_circuit(paths.get('workspace'),
                                                 cid, tools)),
        # v1.9.31 (#239): plan-to-execute gate — CONTRACT v2 (owner ruling):
        # dispatch carries intent, not a plan. The FIRST dispatch of a claim
        # passes without any pre-existing plan (planning is the worker's
        # first act of execution); a RE-dispatch beyond the planning round
        # requires the plan reference — the worker-authored plan on disk
        # (content + #57 gate 3 provenance) or the claim's plan path in the
        # dispatch prompt (re-dispatch continuity).
        ('plan', check_worker_plan(paths, cid, prompt)),
        # #241: claim granularity — plan-size / domain-span at the SAME
        # plan-check point (NOT first dispatch: post-#239 the worker has
        # authored no plan yet, so the gate arms on the approval-point log
        # exactly like the plan gate and fires from the NEXT dispatch on).
        # A monolithic plan REJECTS with the mechanical split directive
        # (mint_split_claims fan-out, issue 234 operator at creation time).
        ('granularity', check_claim_granularity(paths, cid, prompt)),
        # v1.9.32 (#294): tool-first gate — a dispatch whose text matches a
        # registered tools/_INDEX.yaml keyword must cite it (`tool-catalog:`)
        # or explicitly opt out with reasoning. Closes the Swiss-army-test gap
        # where a passing plan gate still let a worker hand-roll a script
        # instead of trying crypto-tool.py for a crypto-decode task.
        ('toolfirst', check_tool_first(paths, desc, prompt)),
        # issue #243: the tool-search BEAT at the SAME plan-check point — a
        # plan proposing to WRITE a new script must cite the --find result it
        # compared against (`tool-search: <keywords> -> <hit|none>`); the
        # standing make-vs-reuse value comparison the wbtest loop skipped.
        ('toolsearch', check_tool_search_citation(paths, cid, prompt)),
        # issue #243 WARN floor: a >50-line workspace script whose capability
        # words match an available CLI/toolbox name ("readelf exists") —
        # WARN, never REJECT; the same standing pass carries `promotion:`
        # notes into the lesson/settlement channel (ladder completion).
        ('handroll', check_handroll_floor(paths, cid, prompt)),
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
    # #880: the toolfirst PASS face fires here (approval point) with the
    # (keyword->tool) attribution payload, and a MATCHED evaluation persists
    # the claim attributes (operation: / operation_tool:). Gates that reject
    # above keep the dispatch lifecycle-silent (#754); the toolfirst gate's
    # own REJECT face already emitted from check_tool_first.
    # NOTE: use the ORIGINAL description channel — the local `desc` was
    # reassigned to the prompt by the facts-snapshot check above.
    toolfirst_pass_record(paths, cid,
                          payload.get('tool_input', {}).get('description', ''),
                          prompt)
    # issue #243: every cited tool-search --find result in the worker's plan
    # is ONE toolfirst_search provenance row (keywords + result) — the
    # make-vs-reuse value comparison lands in the ledger, not just in prose.
    record_tool_search_citations(paths, cid, prompt)
    # #461: a PASSING dispatch is a lifecycle event — renew TTL / complete
    # the activation set / flip phase to DISPATCH / log the dispatch event
    # (fail-open inside; rejected dispatches above never reach this line).
    # #237 H1: the row carries the shared-resolver identity (row_agent), so
    # a subagent_type-shaped verifier dispatch lands `agent=kunglao-redteam`
    # — the marker plan_drift_detector's D3 corroboration matches.
    _dispatch_lifecycle(paths, tier, tools, cid, row_agent, prompt=prompt)
    # #57 gate 3: stamp the per-dispatch nonce (dispatch anchor) at the
    # approval point — it is what arms the plan-author gate on this claim's
    # NEXT dispatch, so a pre-written plan can no longer pass as worker work.
    # Fail-open; after the lifecycle line the dispatch is already approved.
    stamp_dispatch_anchor(paths, cid, prompt, agent_name)
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
    except OSError as exc:
        warn("_apply_tool_error_policy", f"{type(exc).__name__}: {exc}")


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
    except OSError as exc:
        warn("_mark_env_capability_failed", f"{type(exc).__name__}: {exc}")


def _emit_tool_calls(paths: dict, payload: dict, tool_result: str) -> None:
    """#880 RC1: `tool_call` gets a REAL emitter — the Agent PostToolUse face.

    Claim-granularity v1 (explicitly allowed by the card): the subagent's
    transcript arrives only at completion, so per-tool timing is not
    observable — one tool_call row per actually-invoked tool (scan_actual_tools
    over the result), carrying claim / tool / trace_id. duration_ms stays null
    here (fabricating per-tool durations would lie; the claim duration belongs
    to the claim_settled settlement row). Fail-open: the worker entry is gone
    or the log write fails -> no rows, never a crash.
    """
    ws = paths.get('workspace')
    if not ws:
        return
    worker_id = payload.get('tool_input', {}).get('name') or ''
    try:
        entry = next((w for w in read_active_workers(paths['state'])
                      if w.get('worker_id') == worker_id), None)
    except Exception:  # noqa: BLE001 — liveness IO is best-effort
        entry = None
    if not entry or not entry.get('claim_id'):
        return
    tools = scan_actual_tools(tool_result)
    if not tools or _klog is None:
        return
    cid = entry['claim_id']
    trace_id = _declared_trace_id(payload.get('tool_input', {}).get('prompt', ''))
    try:
        for tool in tools:
            _klog.emit(Path(ws), 'hook:worker_budget', 'tool_call', claim=cid,
                       tool=tool, trace_id=trace_id,
                       detail='claim-granularity v1 (#880): tool observed in '
                              'the completed worker transcript')
    except Exception as exc:  # noqa: BLE001 — logging never breaks post_check
        print(f'[kunglao-agent] tool_call emit WARN (fail-open): '
              f'{type(exc).__name__}: {exc}', file=sys.stderr)


def _scan_invoked_tools(transcript: str) -> list[str]:
    """#256 review round 2: actually-invoked-only scan for the thrash
    recorder. Same vocabulary as scan_actual_tools (mcp__ names + the
    KNOWN_TOOLS set) but word-boundary anchored, so a tool name merely
    MENTIONED inside another word ("ripgrep" mentioning grep) does not
    count as an invocation against the fingerprint."""
    found: set[str] = set()
    for m in re.finditer(r'\bmcp__[a-z0-9_]+\b', transcript):
        found.add(m.group(0))
    for name in KNOWN_TOOLS:
        if re.search(rf'\b{re.escape(name)}\b', transcript):
            found.add(name)
    return sorted(found)


# ws -> last WARN reason (rate limit: one WARN per ws until the reason
# changes; a persistently wedged recorder must not print per completion)
_ZOF_WARN_LAST: dict[str, str] = {}


def _zof_warn(ws: str, reason: str) -> None:
    if _ZOF_WARN_LAST.get(ws) == reason:
        return
    _ZOF_WARN_LAST[ws] = reason
    print(f'[kunglao-agent] zero-output fingerprint recorder WARN '
          f'(fail-open): {reason}', file=sys.stderr)


def _record_zero_output_fingerprint(paths: dict, payload: dict,
                                    tool_result: str) -> None:
    """#256: the A4 thrash recorder gets its production trigger.

    post_check IS the "worker action completed" face: every tool the
    completed dispatched worker actually invoked is counted against its
    (tool-family, claim_id) fingerprint (claim-granularity v1 — the same
    discriminator and the same limits as _emit_tool_calls above: only
    workers with an [active_workers] entry carrying a claim_id record,
    so orchestrator-side Agent calls never touch the state).

    Visible fail-open (the #256 asymmetry): liveness first — a recorder
    fault NEVER breaks post_check (rc stays 0) — but the fault is not
    silently swallowed either: a crash AND a no-op recorder (record_action
    returning without a streak payload) both land a stderr WARN, rate-
    limited to once per ws+reason until the reason changes. A PARTIAL
    recording (some tools landed before a fault) says so — it never
    misreports a partial as a total failure. Enforcement is the SEPARATE
    zerooutput pre_check gate, which derives belief freshness itself.
    """
    ws = paths.get('workspace')
    if not ws:
        return
    worker_id = payload.get('tool_input', {}).get('name') or ''
    if not worker_id:
        return
    try:
        entry = next((w for w in read_active_workers(paths['state'])
                      if w.get('worker_id') == worker_id), None)
        if not entry or not entry.get('claim_id'):
            return  # not a dispatched worker completion — out of scope
        invoked = _scan_invoked_tools(tool_result)
        if not invoked:
            return
        import zero_output_fingerprint  # scripts/ on path (#671 authority)
        cid = entry['claim_id']
        landed: list[str] = []
        for tool in invoked:
            try:
                result = zero_output_fingerprint.record_action(
                    Path(ws), tool, cid)
            except Exception as exc:  # noqa: BLE001 - per-tool isolation
                _zof_warn(
                    ws, f'{type(exc).__name__}: {exc} (at tool={tool}); '
                    f'{len(landed)}/{len(invoked)} tools recorded, tools '
                    f'from {tool} on not counted this completion')
                return
            if not isinstance(result, dict) or 'streak' not in result:
                # A no-op recorder must not pass for a healthy one.
                _zof_warn(
                    ws, f'no-op recorder: record_action returned '
                    f'{type(result).__name__} without a streak payload '
                    f'(at tool={tool}); {len(landed)}/{len(invoked)} '
                    f'tools recorded, tools from {tool} on not counted '
                    f'this completion')
                return
            landed.append(tool)
    except Exception as exc:  # noqa: BLE001 - liveness first, fault visible
        _zof_warn(ws, f'{type(exc).__name__}: {exc}')


# Worker terminal statuses that mean the DISPATCH FAILED (#234). Subset of
# lib_kunglao.TERMINAL_WORKER_STATUSES minus done (delivered) — a done
# worker never accrues a strike.
DISPATCH_FAILURE_STATUSES = frozenset({"failed", "blocked", "error"})


def _worker_final_status(ws: str, worker_id: str, tool_result: str) -> str | None:
    """The finished worker's liveness token (#444 single parse point).

    Ground truth is runs/worker-status-<worker>.md (reconcile_workers reads
    the same file). Only when that file is missing/empty does the completed
    transcript serve, and even then ONLY its closing status line (F5): the
    last non-empty line must carry the protocol's `status:` line shape, and
    the token itself is parsed by the CANONICAL parser
    (lib_kunglao.parse_worker_status_tokens — #444 AC-1: no hand-rolled
    status-token regex outside the owner). Anything else yields None —
    absence of a strike, never a guessed one; quoted/echoed `status:`
    fragments elsewhere in the transcript (log excerpts, register quotes)
    can never burn a false strike.
    """
    lib = load_hooks_lib()
    p = Path(ws) / 'runs' / f'worker-status-{worker_id}.md'
    text = ''
    if p.exists():
        text = p.read_text(encoding='utf-8', errors='replace')
    if not text.strip():
        for line in reversed((tool_result or '').splitlines()):
            s = line.strip()
            if not s:
                continue
            if not s.lower().startswith('status:'):
                return None  # the transcript does not CLOSE with a status line
            tokens = lib.parse_worker_status_tokens(s)
            return tokens[-1] if tokens else None
    return lib.parse_worker_status(text)


def _record_dispatch_failure(paths: dict, worker_id: str,
                             tool_result: str, description: str = '') -> None:
    """#234: the dispatch-failure 3-strike face of the Agent PostToolUse sink.

    A finished worker whose terminal status is failed/blocked/error counts
    one promotion attempt against its claim
    (dead_letter.record_dispatch_failure — the live writer the family
    lacked); at 3 strikes the claim escalates to the charter must-ask lane
    (review F6 — the status flip stays an explicit dead_letter --mark
    decision). Fail-open by contract: a missing entry, an unreadable
    register, or a broken import must never break post_check — warnings go
    to stderr, the hook's own rc is untouched. The entry-missing starvation
    path WARNS when a claim dispatch was actually expected (the dispatch
    prompt carries a claim id) and stays silent for non-claim Agent calls
    (F5): a systematic miss must be audible, an unrelated verifier
    completion must not spam.
    """
    ws = paths.get('workspace')
    if not ws or not worker_id:
        return
    try:
        try:
            entry = next((w for w in read_active_workers(paths['state'])
                          if w.get('worker_id') == worker_id), None)
        except Exception:  # noqa: BLE001 — liveness IO is best-effort
            entry = None
        claim_id = (entry or {}).get('claim_id') or ''
        if not claim_id:
            try:
                _tier, _tools, expected = parse_dispatch(description or '')
            except Exception:  # noqa: BLE001 — unparseable prompt: not a claim dispatch
                expected = None
            if expected:
                print(f'[kunglao-agent] #234 dispatch-failure WARN: claim '
                      f'{expected} was dispatched but worker {worker_id} has '
                      f'no [active_workers] entry — strike not recorded '
                      f'(reconcile runs/.kunglao-state)', file=sys.stderr)
            return
        final = _worker_final_status(ws, worker_id, tool_result)
        if final not in DISPATCH_FAILURE_STATUSES:
            return
        from _path_hygiene import scripts_on_path
        with scripts_on_path():  # #671 scoped membership (worker_pulse face)
            import dead_letter as _dl
        r = _dl.record_dispatch_failure(Path(ws), claim_id)
        if r.get('incremented'):
            if int(r.get('attempts') or 0) >= _dl.DLQ_ATTEMPTS:
                escalation = r.get('must_ask') or {}
                if escalation.get('escalated'):
                    print(f'[kunglao-agent] MUST-ASK: {claim_id} hit '
                          f'{r["attempts"]} failed dispatches — charter '
                          f'exhaustion row '
                          f'(blockers/must-ask-{claim_id}.md, status '
                          f'untouched); DEAD stays an explicit '
                          f'dead_letter --mark decision', file=sys.stderr)
                else:
                    # review r2 LOW: the artifact write can fail — the
                    # strike counted, but the escalation surface did not
                    # land; say so instead of pointing at a missing file.
                    print(f'[kunglao-agent] #234 must-ask escalation WARN '
                          f'on {claim_id}: '
                          f'{escalation.get("reason")}', file=sys.stderr)
            else:
                print(f'[kunglao-agent] #234: dispatch failure recorded on '
                      f'{claim_id} (promotion_attempts={r["attempts"]})',
                      file=sys.stderr)
        else:
            print(f'[kunglao-agent] #234 dispatch failure not recorded: '
                  f'{r.get("reason")}', file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — fail-open, never break the hook
        print(f'[kunglao-agent] #234 dispatch-failure WARN (fail-open): '
              f'{type(exc).__name__}: {exc}', file=sys.stderr)


def post_check(payload: dict, paths: dict) -> int:
    worker_id = payload.get('tool_input', {}).get('name') or ''
    tool_result = str(payload.get('tool_result', ''))
    # #880: BEFORE remove_worker — the [active_workers] entry carries the
    # claim_id the tool_call rows attribute to.
    _emit_tool_calls(paths, payload, tool_result)
    # #256: same discriminator, same granularity — count the completed
    # worker's actual tools against their (tool, claim) fingerprints so
    # repeated no-progress actions trip the zero-output circuit (enforced
    # by the zerooutput pre_check gate on the NEXT dispatch).
    _record_zero_output_fingerprint(paths, payload, tool_result)
    # #234: same window — the dispatch-failure 3-strike face (fail-open).
    _record_dispatch_failure(
        paths, worker_id, tool_result,
        description=payload.get('tool_input', {}).get('description') or '')
    if worker_id:
        remove_worker(paths['state'], worker_id)
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
    except Exception as exc:  # noqa: BLE001 - logging never breaks enforcement
        warn("_emit_gate_event", f"{type(exc).__name__}: {exc}")


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
