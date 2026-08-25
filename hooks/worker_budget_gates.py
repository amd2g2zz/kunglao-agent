# -*- coding: utf-8 -*-
from __future__ import annotations

from worker_budget_core import (
    MAX_WORKERS, MAX_PROMOTION_ATTEMPTS, MAX_RETRIES, RETRY_COUNTER_FILE,
    ENV_STATE_FILE, ENV_STATE_TTL_MINUTES,
    PREFIX_RE, CLAIM_RE, VM_TOOLS, KNOWN_TOOLS, HOST_FORBIDDEN_TOOLS,
    TOOL_ERRORS_FILE, GENERIC_WORK_AGENT, _SKILL_ROOT,
    _ratio_rank, _EvidenceView, _PRIORITY_AVAILABLE,
    _load_specialist_table, _recommend_agent_type, _AGENTTYPE_AVAILABLE,
    _tep, TOOL_ERROR_POLICY_LOADED, _ha_link, _klog,
    _load_yaml, _run_py, _format_worker, _parse_worker_line,
    read_active_workers, _replace_segment, _atomic_write,
    TERMINAL_CLAIM_STATUSES, _claim_statuses,
    parse_dispatch, scan_actual_tools, detect_self_cap, tool_to_constraint,
)  # noqa: E402,F401

import json
import re
import sys
import time
from pathlib import Path

import yaml  # noqa: E402

from status_defs import TERMINAL  # noqa: E402,F401  # single source (#34, #95)

"""worker_budget_gates — dispatch admission checks (5 dispatch + 3 advisory + PROVEN/claim-status gates).

#568: extracted from worker_budget.py. Gates here are MECHANICAL checks
(≤3 workers, promotion_attempts<3, tools ⊆ task_spec.constraints, deadline,
tier, self-cap, plan-to-execute, tool-first, agent-type, PROVEN/claim-status)
plus the BLIND verifier gate for PROVEN promotions."""

def compare_register_change(reg_path: Path, before: dict[str, str] | None,
                            agent_name: str) -> tuple[bool, str]:
    """Compare a pre-snapshot of claim statuses against the current file."""
    if before is None:
        return True, 'no-before'
    if not agent_name or agent_name in ('orchestrator', 'main', 'kunglao-orch'):
        return True, 'orchestrator exempt'
    after = _claim_statuses(reg_path)
    if after is None:
        return True, 'register unreadable'
    promoted = []
    for cid, st in after.items():
        b = before.get(cid)
        if b is not None and b != st and st in TERMINAL_CLAIM_STATUSES:
            promoted.append(f'{cid}:{b}->{st}')
    if promoted:
        return False, (f'WORKER SELF-PROMOTION BLOCKED: {agent_name} flipped '
                       f'claim(s) to terminal status {promoted}. Only the '
                       f'orchestrator promotes after kunglao-redteam passes '
                       f'(maker-checker S1b).')
    return True, 'ok'


# ---------- BLIND verifier gate for PROVEN (issue #15 / PRD M1) ----------
# Even the orchestrator cannot write PROVEN to a claim whose fact file lacks
# a valid verifier_sign_off block. This catches orchestrator bypasses (direct
# register edits that skip claim_migrator). The formal gate lives in
# scripts/blind_gate.py; this function is the hook-side backstop.

def compare_register_change_proven_gate(
    reg_path: Path, before: dict[str, str] | None,
    agent_name: str, facts_dir: Path
) -> tuple[bool, str]:
    """Check that any newly-PROVEN claim has independent BLIND sign-off.

    Unlike compare_register_change (which exempts the orchestrator from the
    worker self-promotion guard), this gate applies to ALL actors including
    the orchestrator: PROVEN requires verifier_sign_off, period.

    #78 fail-closed: the BLIND / contradiction / inference gates are REQUIRED
    for the PROVEN promotion (same policy as claim_migrator's
    REQUIRED_FOR_TERMINAL_STATE). An unreadable register (with a
    before-snapshot), an unavailable gate module, or a raising checker blocks
    the write — no alternate direct-edit promotion route stays fail-open.
    """
    if before is None:
        return True, 'no-before snapshot'
    after = _claim_statuses(reg_path)
    if after is None:
        # fail closed: a promotion may have been written and cannot be
        # verified — block rather than permit an unverified PROVEN.
        return False, ('PROMOTION GATE: claim-register.yaml unreadable after '
                       'write - cannot verify PROVEN gate (fail closed); '
                       'fix or restore the register and retry')
    # find claims that became PROVEN
    newly_proven = [cid for cid, st in after.items()
                    if before.get(cid) != st and st == 'PROVEN']
    if not newly_proven:
        return True, 'no PROVEN promotions'
    # check BLIND gate for each — required, fail closed (#78)
    try:
        sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))
        from blind_gate import check_proven_gate
    except Exception as exc:
        return False, (f'PROMOTION GATE: blind_gate unavailable (fail closed) '
                       f'- {type(exc).__name__}: {exc}')
    # contradiction gate (#47): PROVEN also requires no same-topic CONFLICT —
    # same-topic multi-PROVEN facts with differing conclusions need a
    # supersedes/superseded_by link, else the write is blocked.
    try:
        from fact_contradiction_gate import check_proven_contradiction
    except Exception as exc:
        return False, (f'PROMOTION GATE: fact_contradiction_gate unavailable '
                       f'(fail closed) - {type(exc).__name__}: {exc}')
    # inference-scope gate (#48): inferential/routing claims need independent
    # static sign-off coverage — byte anchors / orchestrator-captured evidence
    # do not cover the inference (a2b5e25c problem 2, F040).
    try:
        from blind_gate import check_inference_blind_scope
    except Exception as exc:
        return False, (f'PROMOTION GATE: blind_gate.check_inference_blind_scope '
                       f'unavailable (fail closed) - {type(exc).__name__}: {exc}')
    register_text = reg_path.read_text(encoding='utf-8', errors='replace')
    import re as _re
    violations = []
    try:
        for cid in newly_proven:
            worker_id = None
            m = _re.search(rf"- id:\s*{_re.escape(cid)}\b(.*?)(?=\n-\s*id:|\Z)",
                           register_text, _re.DOTALL)
            if m:
                for key in ('worker_id', 'last_dispatched_worker'):
                    wm = _re.search(rf"\b{key}:\s*(\S+)", m.group(1))
                    if wm and wm.group(1).strip().lower() not in ('null', 'none', '~'):
                        worker_id = wm.group(1).strip().strip("'\"")
                        break
            allowed, effective, reason = check_proven_gate(cid, facts_dir, worker_id=worker_id)
            if not allowed:
                violations.append(f'{cid}: {reason}')
            c_ok, c_reason = check_proven_contradiction(cid, facts_dir)
            if not c_ok:
                violations.append(f'{cid}: {c_reason}')
            i_ok, _, i_reason = check_inference_blind_scope(
                cid, facts_dir, register_text, worker_id=worker_id)
            if not i_ok:
                violations.append(f'{cid}: {i_reason}')
    except ImportError as exc:
        # Infrastructure failure (should not happen after import above, but
        # defensive) — fail closed: code must be complete.
        return False, (f'PROMOTION GATE: checker raised while verifying PROVEN '
                       f'({type(exc).__name__}: {exc}) - fail closed')
    except Exception as exc:
        # #98 (D6/F15): runtime verifier error (timeout/resource limit) —
        # degrade to STAMP guidance instead of hard fail-closed block.
        # The PROVEN promotion is still blocked (cannot be PROVEN without
        # verification), but the message guides to STAMP downgrade rather
        # than demanding infrastructure repair.
        for cid in newly_proven:
            violations.append(
                f'{cid}: VERIFIER RUNTIME ERROR '
                f'({type(exc).__name__}: {exc}) - '
                f'degrade to STAMP (guardrails SS1b self_caveat allowed)')
    if violations:
        return False, (f'PROMOTION GATE: PROVEN rejected - '
                       f'{"; ".join(violations)}. Downgrade to STAMP or resolve the blockers.')
    return True, f'{len(newly_proven)} PROVEN promotion(s) with valid BLIND sign-off'


def register_worker(path: Path, entry: dict) -> None:
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    workers = read_active_workers(path) + [entry]
    new_lines = [_format_worker(w) for w in workers]
    _atomic_write(path, _replace_segment(text, new_lines))


def remove_worker(path: Path, worker_id: str) -> dict | None:
    workers = read_active_workers(path)
    remaining = []
    removed = None
    for w in workers:
        if w['worker_id'] == worker_id:
            removed = w
        else:
            remaining.append(w)
    if removed is None:
        return None
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    new_lines = [_format_worker(w) for w in remaining]
    _atomic_write(path, _replace_segment(text, new_lines))
    return removed


# ---------- claim register ----------

def read_claim(path: Path, claim_id: str) -> dict | None:
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    for c in data.get('claims', []) or []:
        if c.get('id') == claim_id:
            return c
    return None


def _read_all_claims(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return data.get('claims', []) or []


# ---------- checks ----------

def check_workers_lt_3(paths: dict) -> tuple[bool, str]:
    """Single source of truth (issue #37): count ACTIVE workers from status files
    (lib_kunglao.scan_active_workers), NOT the analysis_state.txt [active_workers]
    cache — reconcile can clear or leave that cache stale, so reading it made the
    gate and convergence_check disagree on the active count.

    FAIL_OPEN: workspace key missing or scan raises -> allow (a hook must never
    block dispatch on its own scan failure; that would deadlock the loop).
    """
    ws = paths.get('workspace') if isinstance(paths, dict) else None
    if not ws:
        return True, ''
    try:
        sys.path.insert(0, str(_SKILL_ROOT / 'hooks'))
        from lib_kunglao import scan_active_workers
        n, _stuck = scan_active_workers(Path(ws))
    except Exception:
        return True, ''  # FAIL_OPEN — never block dispatch on scan failure
    if n >= MAX_WORKERS:
        return (False, f'active_workers={n} >= {MAX_WORKERS}')
    return (True, f'active_workers={n}')


def check_promotion_attempts(reg_path: Path, claim_id: str | None) -> tuple[bool, str]:
    if not claim_id:
        return (True, 'no target claim')
    c = read_claim(reg_path, claim_id)
    if c is None:
        return (True, f'claim {claim_id} not in register (cannot check, allow)')
    pa = int(c.get('promotion_attempts', 0))
    if pa >= MAX_PROMOTION_ATTEMPTS:
        return (False, f'claim {claim_id} promotion_attempts={pa} >= {MAX_PROMOTION_ATTEMPTS}')
    return (True, f'promotion_attempts={pa}')


# ---------- #604: MAX_RETRIES circuit breaker for silent worker failures ----------
# Distinct from MAX_PROMOTION_ATTEMPTS (#520): #520 only counts PROVEN
# promotion attempts on a claim. #604 counts WORKER-level silent-failure
# re-dispatches on the same (worker_id, claim_id). When a worker silently
# dies / hangs and the orchestrator re-dispatches it 3 times on the same
# claim, this gate escalates to BLOCKED and requires a failure-analysis
# artifact before any further re-dispatch.
#
# The counter lives in <workspace>/runs/.retry-counter.yaml with shape:
#   counters:
#     "<worker_id>:<claim_id>": <int>
# `record_retry` is called by the orchestrator after detecting a silent
# failure (worker hung / no progress / heartbeat STALE on a dispatched
# worker). `reset_retry_counter` is called ONLY on PROVEN completion
# (claim finishes successfully — partial completion does NOT reset).
# The counter file is fail-open (unreadable / missing → allow).

def _retry_key(worker_id: str, claim_id: str) -> str:
    return f'{worker_id}:{claim_id}'


def read_retry_counter(workspace: str | Path) -> dict[str, int]:
    """Read the {key: count} map from runs/.retry-counter.yaml.

    Returns {} when the file is absent, unreadable, or malformed. Missing
    `runs/` directory also returns {} (the counter file is created lazily
    by `record_retry`).
    """
    if not workspace:
        return {}
    p = Path(workspace) / 'runs' / '.retry-counter.yaml'
    if not p.exists():
        return {}
    try:
        import yaml as _y
        data = _y.safe_load(p.read_text(encoding='utf-8')) or {}
    except Exception:
        return {}
    raw = data.get('counters') or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _write_retry_counter(workspace: Path, counters: dict[str, int]) -> None:
    """Atomically write the counter file. Creates runs/ if missing.

    The atomic-write primitive is borrowed from worker_budget_core
    (_atomic_write via tempfile + replace) so a crash mid-write cannot leave
    a half-written YAML that the gate would then mis-read.
    """
    import yaml as _y
    runs = workspace / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / '.retry-counter.yaml'
    text = _y.safe_dump({'counters': counters}, allow_unicode=True, sort_keys=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(p)


def record_retry(workspace: str | Path, worker_id: str, claim_id: str) -> int:
    """Increment the silent-failure retry counter for (worker_id, claim_id).

    Returns the new count. Creates the counter file if absent. NOOP on a
    missing workspace (fail-open — a broken orchestrator path must not be
    able to corrupt the gate's counter; if we cannot write, the counter
    stays at the previous value, and the next check_max_retries call will
    pass since no counter file means count=0).

    The increment is intentionally atomic (read-modify-write under
    _atomic_write): two concurrent silent-failure detections on the same
    worker must each count (the worst case is one lost increment on a
    race, which is acceptable — the gate fires at threshold, not exact).
    """
    if not workspace or not worker_id or not claim_id:
        return 0
    counters = read_retry_counter(workspace)
    key = _retry_key(worker_id, claim_id)
    counters[key] = int(counters.get(key, 0)) + 1
    try:
        _write_retry_counter(Path(workspace), counters)
    except Exception:
        # Fail-open: do not propagate — the gate will still pass since
        # the on-disk counter is the source of truth (just possibly stale).
        pass
    return counters[key]


def reset_retry_counter(workspace: str | Path, worker_id: str, claim_id: str) -> bool:
    """Clear the retry counter for (worker_id, claim_id).

    Intended for PROVEN-completion callers ONLY (claim finishes
    successfully — the worker did its job, future dispatches are fresh).
    Partial completion (status: in_progress / done-only-output) MUST NOT
    call this — partial success does not prove the worker's failure mode
    is resolved; the next dispatch on the same worker_id could hit the
    same silent failure again.

    Returns True if a counter was removed, False otherwise.
    """
    if not workspace or not worker_id or not claim_id:
        return False
    counters = read_retry_counter(workspace)
    key = _retry_key(worker_id, claim_id)
    if key not in counters:
        return False
    del counters[key]
    try:
        _write_retry_counter(Path(workspace), counters)
    except Exception:
        return False
    return True


def check_max_retries(workspace: str | Path, worker_id: str,
                      claim_id: str) -> tuple[bool, str]:
    """Issue #604: cap silent-failure retry loops at MAX_RETRIES.

    When the same worker_id has been silently-failed and re-dispatched
    MAX_RETRIES (3) times on the same claim_id, REJECT the dispatch and
    escalate to BLOCKED. The REJECT message requests a failure-analysis
    artifact — the orchestrator must record WHY the worker keeps silently
    failing (env broken? wrong tool? capability gap?) before another
    re-dispatch is allowed.

    FAIL_OPEN semantics: a missing counter file, an unreadable workspace,
    or a missing worker_id/claim_id lets the gate pass (returns True).
    This matches the gate's FAIL_OPEN stance on scan failures — a broken
    gate must not block dispatch, that would deadlock the loop.

    Returns (ok, reason). ok=False means REJECT the dispatch.
    """
    if not workspace or not worker_id or not claim_id:
        return (True, 'no workspace/worker_id/claim_id - max-retries skipped')
    counters = read_retry_counter(workspace)
    key = _retry_key(worker_id, claim_id)
    count = int(counters.get(key, 0))
    if count >= MAX_RETRIES:
        return (False, (
            f'BLOCKED: worker {worker_id} retry_count={count} >= {MAX_RETRIES} '
            f'on claim {claim_id} (silent-failure circuit breaker, #604). '
            f'A failure-analysis artifact (runs/failure-analysis-{claim_id}.md) '
            f'is REQUIRED before further re-dispatch — record WHY the worker '
            f'keeps silently failing (env / tool / capability gap) and reset '
            f'the counter via reset_retry_counter(worker_id, claim_id) once the '
            f'root cause is addressed or claim is PROVEN.'
        ))
    return (True, f'retry={count}')


def check_tools_allowed(tools: list[str], task_spec_path: Path) -> tuple[bool, str]:
    if not task_spec_path.exists():
        return (True, 'no task_spec (allow)')
    ts = yaml.safe_load(task_spec_path.read_text(encoding='utf-8')) or {}
    constraints = ts.get('constraints', {}) or {}
    for t in tools:
        c = tool_to_constraint(t)
        if c and constraints.get(c) == 'forbidden':
            return (False, f'tool {t!r} requires {c}=allowed but task_spec forbids it')
    return (True, 'tools allowed')


def check_host_forbidden_tools(tools: list[str]) -> tuple[bool, str]:
    """Deny host-channel dynamic tools per SKILL.md §Hard prohibitions #5.

    Unconditional (no task_spec gating): VM-only is absolute. The canonical
    VM-channel x64dbg entry is `mcp__x64dbg__connect_remote`; the host-channel
    `start_session` / `connect_to_session` are forbidden regardless of
    `task_spec.constraints.vm_detonation` because they would execute the
    sample on the host, bypassing the workspace `block_malware_exec` PreToolUse
    hook (which matches Bash only, not MCP).

    #515 (c) wildcard coverage: intended_tools may carry explicit wildcard
    forms (`mcp__<server>__*`). A wildcard that COVERS a host-forbidden name
    is rejected with the same semantics — the worker could then legally pick
    the covered name (e.g. `mcp__frida__*` covers spawn/attach,
    `mcp__x64dbg__*` covers all four x64dbg host channels). Exact-name
    membership is unchanged (zero loosening); only explicit wildcard forms
    are additionally evaluated for coverage. Benign wildcards
    (`mcp__camoufox__*`) and concrete VM-channel names pass.
    """
    bad = []
    for t in tools:
        if t in HOST_FORBIDDEN_TOOLS:
            bad.append(t)
            continue
        if t.endswith('*'):
            prefix = t[:-1]
            covered = sorted(f for f in HOST_FORBIDDEN_TOOLS
                             if f.startswith(prefix))
            if covered:
                bad.append(f"{t} (covers {', '.join(covered)})")
    if bad:
        return (False, (
            f'host-channel dynamic tool(s) {bad!r} forbidden - '
            f'use mcp__x64dbg__connect_remote (VM path) / rev-frida via VM '
            f'frida-server. See kunglao-agent/references/dynamic-re-tool-priority.md'
        ))
    return (True, 'no host-channel dynamic tools')


def check_deadline(state_path: Path) -> tuple[bool, str]:
    if not state_path.exists():
        return (True, 'no state file')
    for line in state_path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if s.startswith('deadline_ts:'):
            try:
                dl = int(s.split(':', 1)[1].strip())
            except ValueError:
                return (True, 'deadline_ts unparseable (allow)')
            if time.time() >= dl:
                return (False, f'now >= deadline_ts {dl}')
            return (True, f'deadline_ts={dl}')
    return (True, 'no deadline_ts set')


def check_tier_gate(reg_path: Path, tier: int) -> tuple[bool, str]:
    if tier <= 1:
        return (True, 'tier 1 ungated')
    threshold = tier - 1
    for c in _read_all_claims(reg_path):
        if c.get('status') in TERMINAL:
            continue
        eta = int(c.get('evidence_tier_attempted', 0))
        if eta < threshold:
            return (False, f'open claim {c.get("id")} at evidence_tier={eta} < {threshold}')
    return (True, f'all open claims at evidence_tier >= {threshold}')


def check_no_self_cap(description: str, task_spec_path: Path) -> tuple[bool, str]:
    """Reject dispatch descriptions that smuggle a self-imposed time cap.

    Contract: orchestrator-level time budget comes ONLY from
    `task_spec.time_budget_minutes`. When the user sets that to 0 (or omits
    it) the run is "no budget, until convergence". A sub-agent that adds its
    own "30 s" / "5 min" / "cap it at" violates the user's contract and
    shortens the loop prematurely.

    Returns (ok, reason). ok=False means REJECT the dispatch.
    """
    # Read task_spec to learn the user-authorised posture.
    if task_spec_path.exists():
        ts = yaml.safe_load(task_spec_path.read_text(encoding='utf-8')) or {}
    else:
        ts = {}
    # Per SKILL.md §3 + DESIGN §15: budget sits under `constraints` or top-level.
    ts_budget = ts.get('time_budget_minutes', None)
    if ts_budget is None:
        ts_budget = (ts.get('constraints') or {}).get('time_budget_minutes', None)

    # If user authorised >0 minutes, sub-agents may add caps up to that ceiling.
    # If 0 (or unset), reject any self-cap.
    allowed_minutes: float | None
    if ts_budget is None or ts_budget == 0:
        allowed_minutes = None  # zero budget = no self-cap allowed
    else:
        try:
            allowed_minutes = float(ts_budget)
        except (TypeError, ValueError):
            allowed_minutes = None

    found, offenders = detect_self_cap(description)
    if not found:
        return (True, 'no self-cap detected')
    # Found. If budget is 0/None → reject.
    if allowed_minutes in (None, 0):
        return (False, (
            f'self-cap detected in dispatch ({offenders!r}) but '
            f'task_spec.time_budget_minutes={ts_budget!r} (no budget authorised). '
            f'Remove the self-cap or set time_budget_minutes > 0 first.'
        ))
    # budget > 0: accept only if the offender mentions a duration not exceeding budget.
    # Parse the first numeric + unit to compare.
    m = re.search(r'(\d+)\s*(min(?:ute)?s?|sec(?:ond)?s?|hour|day)s?', offenders[0], re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        mins = n if unit.startswith('min') else (n * 60 if unit.startswith('sec') else (n * 60 if unit.startswith('hour') else n * 60 * 24))
        if mins > allowed_minutes:
            return (False, (
                f'self-cap {n}{unit} exceeds task_spec.time_budget_minutes={allowed_minutes}'
            ))
    return (True, f'self-cap within budget {allowed_minutes} min')


# ---------- plan-to-execute gate (issue #239) ----------
# kunglao-worker.md golden rule #3 (PLAN FIRST, execute second) existed but
# had ZERO mechanical enforcement: pre_check never required a plan and
# reconcile_workers only recognized plan-redteam-*.md. 2026-08-12 accident:
# F006-F008 were callgraph INFERENCES written as facts — a mandatory plan
# forces the inference to be declared in the plan phase, before execution,
# where the orchestrator can catch it.

# #294: the plan-first gate (#239) only checked file EXISTENCE — an empty-shell
# template (goal:/preflight:/steps:/fallback: with every field bare, no content)
# passed the gate. The Swiss-army test (C-022, 2026-08-13) showed workers can
# satisfy `check_worker_plan` with a shell plan and then hand-roll scripts
# instead of discovering tools/_INDEX. This regex matches a field label with
# NOTHING after the colon (whitespace-only rest of line) — used to detect the
# all-fields-bare shape without penalizing plans that just leave ONE field
# terse (goal: decode strings / preflight: (empty) is still real intent).
_BARE_FIELD_RE = re.compile(
    r'^\s*(goal|preflight|steps|fallback)\s*:\s*$', re.IGNORECASE | re.MULTILINE,
)


def _plan_is_empty_shell(text: str) -> bool:
    """#294: True iff the plan file has NO content beyond bare field labels.

    Strips every `goal:`/`preflight:`/`steps:`/`fallback:` line that has
    nothing after the colon, then strips blank lines. If anything survives
    (a filled-in field, extra prose, a step description), the plan is real.
    """
    # H1 (#294): a UTF-8 BOM (PowerShell/Notepad utf8 output) before `goal:`
    # would make `﻿goal:` look like content — strip it explicitly in
    # addition to the utf-8-sig read in check_worker_plan.
    text = text.lstrip('﻿')
    remaining = []
    for line in text.splitlines():
        if _BARE_FIELD_RE.match(line):
            continue
        if line.strip():
            remaining.append(line)
    return not remaining


def check_worker_plan(paths: dict, cid: str | None, prompt: str = '') -> tuple[bool, str]:
    """Issue #239/#294: a claim dispatch REQUIRES its worker plan, WITH CONTENT.

    The dispatched claim C-NN must already have `runs/plan-C<NN>*.md` on disk
    (orchestrator wrote it pre-dispatch — real-world naming is plan-c005.md,
    claim only, no suffix), OR the dispatch prompt must reference a plan path
    for THAT claim (timing relaxation: the plan may be written in the same
    turn, e.g. "write runs/plan-C001-strings.md first, then execute"). A plan
    path for a DIFFERENT claim in the prompt does NOT relax.

    #294: an on-disk plan that is an empty-shell template (every field label
    present but bare — `goal:\\npreflight:\\nsteps:\\nfallback:` with nothing
    filled in) does NOT satisfy the gate — it is existence without content.
    The prompt-relaxation path is unaffected (the file may not exist yet).

    Returns (ok, reason). ok=False means REJECT the dispatch.
    """
    if not cid:
        return (True, 'no target claim')
    ws = paths.get('workspace') if isinstance(paths, dict) else None
    if not ws:
        return (True, '')  # FAIL_OPEN — mirrors check_workers_lt_3
    key = cid.replace('-', '')  # C-001 -> C001 (claim key inside plan names)
    runs = Path(ws) / 'runs'
    if runs.is_dir():
        # uppercase + lowercase variants (Windows globs are case-insensitive,
        # POSIX are not — cover both so the gate is portable)
        hits = []
        for pat in (f'plan-{key}.md', f'plan-{key}-*.md',
                    f'plan-{key.lower()}.md', f'plan-{key.lower()}-*.md'):
            hits.extend(sorted(runs.glob(pat)))
        if hits:
            plan_path = hits[0]
            try:
                # utf-8-sig: strips a UTF-8 BOM so a PowerShell/Notepad-written
                # template cannot smuggle '﻿goal:' past the empty-shell check.
                plan_text = plan_path.read_text(encoding='utf-8-sig', errors='replace')
            except OSError:
                # unreadable (locked / directory shadowing the name) — fail
                # OPEN with an honest note; a misleading empty-shell reject
                # would blame the worker for a system error.
                return (True, f'plan file exists (unreadable, content not '
                              f'verified): {plan_path.name}')
            if _plan_is_empty_shell(plan_text):
                return (False, (
                    f'{plan_path.name} is an empty-shell template (goal/preflight/'
                    f'steps/fallback all bare, no content) - fill in the plan '
                    f'FIRST (kunglao-worker.md golden rule #3), then re-dispatch'
                ))
            return (True, f'plan file exists: {plan_path.name}')
    if prompt:
        m = re.search(
            rf'plan-[{key[0]}{key[0].lower()}]{re.escape(key[1:])}'
            r'(?:\.md|[-_][A-Za-z0-9._-]*\.md)',
            prompt,
        )
        if m:
            return (True, f'plan path referenced in dispatch prompt: {m.group(0)}')
    return (False, (f'no runs/plan-{key}*.md for claim {cid} and the dispatch '
                    f'prompt does not reference a plan path for it - write the '
                    f'plan FIRST (kunglao-worker.md golden rule #3: PLAN FIRST, '
                    f'execute second)'))


# ---------- tool-first gate (issue #294) ----------
# The plan-to-execute gate (#239, hardened above) only forced a PLAN to exist —
# it never checked that the plan actually looked for a registered tool before
# committing to hand-written logic. The Swiss-army test (C-022, 2026-08-13)
# showed a worker with a passing plan gate still wrote its own crypto-decode
# script instead of trying tools/crypto/crypto-tool.py, because nothing in the
# dispatch contract required it to check tools/_INDEX.yaml first. This gate
# closes that gap MECHANICALLY: if the dispatch text (description + prompt)
# contains a keyword that maps to a registered tool's category/capability, the
# dispatch must carry a `tool-catalog: <name>` marker (or an explicit
# `tool-catalog: none (reasoning: ...)` opt-out) — otherwise REJECT. No keyword
# match -> silent pass (avoids false positives on unrelated claims).

# H2 (#294): generic category/capability words are routine prose too
# ('static overview of imports' is an adjective, not a disasm tool) — they
# would false-positive REJECT normal dispatches. Stopworded out of the trigger
# set; the remaining keywords (crypto/ghidra/recon/decompile/vtable/...) are
# distinctive enough to be safe signals.
# #340: category ids renamed aux→auxiliary / pipeline→pipelines (id == dir
# name); _load_tool_index_keywords derives keywords from those ids, so the
# plural forms joined the trigger set — a dispatch citing the REAL paths
# (tools/pipelines/build_evidence_index.py, tools/auxiliary/...) would
# REJECT without a marker. Both plural forms stopworded; the legacy
# singulars stay (capability domains aux:*/pipeline:* still emit them).
_TOOLFIRST_STOPWORDS = frozenset(
    {'static', 'pipeline', 'pipelines', 'aux', 'auxiliary',
     'annotate', 'decode'})

# One-off diagnostic exemption: CJK phrases are substring-matched (no word
# concept to bound), ASCII phrases are word-bounded so 'one-off' inside a
# longer word cannot trigger, and BOTH are negation-aware — "not a one-off
# diagnostic" must NOT count as an exemption (reviewer r1-294 finding).
_TOOLFIRST_DIAGNOSTIC_SUBSTRINGS = ('一次性诊断', '一次性')
_TOOLFIRST_DIAGNOSTIC_RE = re.compile(
    r'\bone-off\b|\bone shot\b|\bdiagnostic only\b|\bdiagnostic-only\b',
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r'\b(?:not|no)\b|不是|非')

# H2/CJK (#294): ASCII-only word boundaries, not `\b` — Python's \b treats CJK
# chars as word chars, so a CJK-attached phrase like "decode-the-crypto-layer" (解码crypto层) would silently bypass the gate; and
# 'crypto' inside 'cryptography' must NOT match. (?<![A-Za-z0-9_])…(?![A-Za-z0-9_])
# gives exactly that.
_ASCII_BOUNDARY = r'(?<![A-Za-z0-9_]){kw}(?![A-Za-z0-9_])'


def _load_tool_index_keywords(skill_root: Path) -> dict[str, str]:
    """#294: map a lowercase keyword -> tool name, from tools/_INDEX.yaml.

    Keywords are the category and the two halves of `capability` ("<domain>:
    <operation>") for every registered tool — e.g. crypto-tool contributes
    {'crypto': 'crypto-tool', 'decode': 'crypto-tool'}. Multiple tools sharing
    a keyword keep the first-registered tool (informational only; the gate
    only needs ONE candidate name to cite in its REJECT message).
    """
    index_path = skill_root / 'tools' / '_INDEX.yaml'
    if not index_path.exists():
        return {}
    try:
        data = yaml.safe_load(index_path.read_text(encoding='utf-8')) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, str] = {}
    for entry in (data.get('tools') or []):
        if not isinstance(entry, dict):
            continue
        name = entry.get('name')
        if not name:
            continue
        category = str(entry.get('category') or '').strip().lower()
        if category and category not in out:
            out[category] = name
        capability = str(entry.get('capability') or '')
        domain, _, op = capability.partition(':')
        for kw in (domain.strip().lower(), op.strip().lower()):
            if kw and kw not in out:
                out[kw] = name
    return out


def _is_diagnostic_exempt(text: str) -> bool:
    """#294: True iff the text declares a one-off diagnostic (case-insensitive,
    word-bounded for ASCII, negation-aware: 'not a one-off diagnostic' is NOT
    an exemption)."""
    for marker in _TOOLFIRST_DIAGNOSTIC_SUBSTRINGS:
        if marker in text:
            # CJK negation (不是一次性 — "not one-off") in the 16 chars before the marker
            idx = text.find(marker)
            prev = text[max(0, idx - 16):idx]
            if not _NEGATION_RE.search(prev):
                return True
    for m in _TOOLFIRST_DIAGNOSTIC_RE.finditer(text):
        prev = text[max(0, m.start() - 16):m.start()]
        if not _NEGATION_RE.search(prev):
            return True
    return False


def check_tool_first(paths: dict, desc: str, prompt: str) -> tuple[bool, str]:
    """Issue #294: a dispatch touching a registered tool's domain must cite it.

    Scans `desc + prompt` for tools/_INDEX.yaml category/capability keywords
    (ASCII-bounded, case-insensitive, stopworded). No match -> pass silently
    (FAIL_OPEN on ambiguity — this gate only fires on a positive keyword hit).
    A one-off diagnostic declaration exempts the dispatch. Otherwise the text
    MUST contain `tool-catalog:` (either naming the matched tool or an
    explicit `none (reasoning: ...)` opt-out) or the dispatch is REJECTED.

    Returns (ok, reason). ok=False means REJECT the dispatch.
    """
    text = f'{desc}\n{prompt}'
    text_lower = text.lower()
    if 'tool-catalog:' in text_lower:
        # #630: the marker must be HONEST — `none (reasoning: ...)` is the
        # explicit opt-out; otherwise the named tool must be one the keyword
        # scan would actually match (a bare marker or an unrelated name is
        # self-attestation, which was the hole).
        import re as _re630
        m = _re630.search(r'tool-catalog:\s*(.+)', text_lower)
        cited = (m.group(1).strip() if m else '')
        if cited.startswith('none'):
            return (True, 'tool-catalog: none (explicit opt-out)')
        keywords = _load_tool_index_keywords(_SKILL_ROOT)
        if not keywords:
            return (True, 'no tools/_INDEX.yaml keywords to match - tool-first skipped')
        matched_tools = set()
        for kw, tool_name in keywords.items():
            if kw in _TOOLFIRST_STOPWORDS:
                continue
            if _re630.search(_ASCII_BOUNDARY.format(kw=_re630.escape(kw)), text_lower):
                matched_tools.add(tool_name)
        for tool in matched_tools:
            if tool and tool.lower() in cited:
                return (True, f'tool-catalog: {tool} (matched)')
        return (False, (
            "`tool-catalog:` marker names a tool the dispatch text does not "
            "actually match (self-attestation, #630). Cite the tool your text "
            "references, or `tool-catalog: none (reasoning: <why not>)`."
        ))
    if _is_diagnostic_exempt(text):
        return (True, 'one-off diagnostic - tool-first exempt')
    keywords = _load_tool_index_keywords(_SKILL_ROOT)
    if not keywords:
        return (True, 'no tools/_INDEX.yaml keywords to match - tool-first skipped')
    for kw, tool_name in keywords.items():
        if kw in _TOOLFIRST_STOPWORDS:
            continue
        if re.search(_ASCII_BOUNDARY.format(kw=re.escape(kw)), text_lower):
            return (False, (
                f"dispatch text matches registered tool '{tool_name}' "
                f"(keyword '{kw}') but carries no `tool-catalog:` marker. Add "
                f"`tool-catalog: {tool_name}` if you will try it, or "
                f"`tool-catalog: none (reasoning: <why not>)` if it genuinely "
                f"does not apply, then re-dispatch."
            ))
    return (True, 'no tool-catalog keyword match')


def verify_tool_catalog(ws) -> list:
    """#630 post-side companion: a done worker's cited tool must EXIST.

    A PreToolUse gate structurally cannot observe execution — the proof tier
    here is #474's LIVENESS proxy: every `tool-catalog: <name>` cited in a
    done worker's status file must resolve to a name the tools/_INDEX.yaml
    keyword table knows. Fail-open when the index is absent (fixture/legacy
    workspaces). Returns a list of {worker, cited} violations."""
    import re as _re
    from pathlib import Path as _P
    ws = _P(ws)
    runs = ws / "runs"
    if not runs.is_dir():
        return []
    keywords = _load_tool_index_keywords(_SKILL_ROOT)
    if not keywords:
        return []  # no index → nothing to resolve against (fail-open)
    known = {t.lower() for t in keywords.values()}
    violations = []
    for p in sorted(runs.glob("worker-status-*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "status: done" not in text:
            continue
        for m in _re.finditer(r"tool-catalog:\s*([^\n]+)", text, _re.IGNORECASE):
            cited = m.group(1).strip()
            if not cited or cited.lower().startswith("none"):
                continue
            if not any(k in cited.lower() for k in known):
                violations.append({"worker": p.stem, "cited": cited})
    return violations


# ---------- issue #310: agenttype gate (specialist-first as a MECHANICAL check) ----------
# Behavior #2 "specialist-first" was an orchestrator soft constraint: a
# kunglao-worker could silently take a ghidra-type claim (route_capability has
# a specialist recommendation for it) and complete it with the full tool rack
# — no failure signal, the specialist's dedicated prompt/strategy/evidence
# format diluted. Same anti-spoof shape as devreason (v1.9.24): dispatch agent
# type != route recommendation -> REJECT unless the prompt records
# `agent-reasoning:`; deviation-with-reasoning passes and is logged. No
# specialist fits -> silent (kunglao-worker allowed). Role agents
# (kunglao-redteam / kunglao-init-worker) are dispatched by protocol position,
# not claim routing -> silent. FAIL_OPEN whenever the router/register/table is
# unavailable — a broken gate must not block dispatch.

_FEATURE_PROBE_RELS = ('runs/feature-probe.json', 'evidence/feature-probe.json')
_DIE_LANGUAGE_MARKERS = ('go', 'rust', 'c++', '.net', 'c#', 'delphi')


def _scan_die_language_values(data: dict) -> str | None:
    """DIE JSON shape detects[].values[].name — first known language token."""
    detects = data.get('detects')
    if not isinstance(detects, list):
        return None
    for det in detects:
        if not isinstance(det, dict):
            continue
        for v in det.get('values') or []:
            if not isinstance(v, dict):
                continue
            name = str(v.get('name') or '').lower()
            for marker in _DIE_LANGUAGE_MARKERS:
                if marker in name:
                    return marker
    return None


def _load_workspace_features(ws) -> dict:
    """#310: sample features for the router — a captured feature_probe JSON
    (runs/ or evidence/feature-probe.json) or the language field of
    evidence/die.json. {} when absent/unreadable (routing falls back to claim
    intent alone; never raises)."""
    if not ws:
        return {}
    ws = Path(ws)
    for rel in _FEATURE_PROBE_RELS:
        p = ws / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    die = ws / 'evidence' / 'die.json'
    if not die.is_file():
        return {}
    try:
        data = json.loads(die.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    lang = data.get('language')
    if not lang:
        detect = data.get('detect')
        if isinstance(detect, dict):
            lang = detect.get('language')
    if not lang:
        lang = _scan_die_language_values(data)
    return {'language': lang} if lang else {}


def check_agent_type(paths: dict, desc: str, prompt: str,
                     agent_name: str) -> tuple[bool, str]:
    """Issue #310: dispatch agent type vs route_capability recommendation.

    Returns (ok, reason). ok=False means REJECT the dispatch — the claim's
    task domain (statement) x sample features recommend a specialist agent
    that the dispatched agent is not, and the prompt records no
    `agent-reasoning:` deviation.
    """
    _, _, cid = parse_dispatch(desc)
    if not cid or not agent_name:
        return (True, 'no claim id or no agent name - agenttype skipped')
    if not _AGENTTYPE_AVAILABLE:
        return (True, 'route_capability unavailable - agenttype skipped')
    specialists = _load_specialist_table()
    if not specialists:
        return (True, 'no specialist table - agenttype skipped')
    specialist_names = {s['name'] for s in specialists}
    if agent_name not in specialist_names and agent_name != GENERIC_WORK_AGENT:
        return (True, f'{agent_name} is a role agent - claim routing not applied')
    register = paths.get('register')
    if not register:
        return (True, 'no register path - agenttype skipped')
    claim = read_claim(Path(register), cid)
    if not claim or not claim.get('statement'):
        return (True, f'claim {cid} not in register - agenttype skipped')
    features = _load_workspace_features(paths.get('workspace'))
    rec, _rationale = _recommend_agent_type(
        features, claim.get('statement', ''), specialists)
    if rec is None:
        return (True, 'no specialist fits - kunglao-worker allowed')
    if agent_name == rec:
        return (True, f'agent_type matches recommended specialist {rec}')
    if 'agent-reasoning:' in (prompt or '').lower():
        print(f'AGENTTYPE (deviation recorded): {agent_name} dispatched for '
              f'claim {cid}; route_capability recommends {rec} '
              f'(agent-reasoning present)', file=sys.stderr)
        return (True, f'deviation from {rec} recorded via agent-reasoning')
    return (False, (
        f'specialist-first violation (#310): route_capability recommends '
        f'{rec} for claim {cid} but the dispatch sends {agent_name}. Add '
        f'`agent-reasoning: <why {agent_name} instead of {rec}>` to the '
        f'dispatch prompt, or dispatch {rec} - the deviation must be '
        f'recorded, not silently mixed.'
    ))


# ---------- issue #270: REJECT guidance via hookSpecificOutput.additionalContext ----------
