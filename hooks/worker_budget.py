# -*- coding: utf-8 -*-
"""worker_budget — Pre+Post ToolUse hook on Agent (DESIGN §11).

Enforces 5 dispatch gates + worker accounting:
  (a) ≤3 concurrent workers (active_workers segment)
  (b) target claim promotion_attempts < 3 (per-claim cost cap)
  (c) intended_tools ⊆ task_spec.constraints (vm/cti forbidden checks)
  (d) now < deadline_ts (time budget)
  (e) tier gate (§8.5): tier=N needs all open claims at evidence_tier_attempted ≥ N-1

Functions take explicit paths so they are unit-testable with tmp_path.
The hook entry (main) reads stdin JSON from Claude Code's hook system.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

# ---------- constants ----------

MAX_WORKERS = 3
MAX_PROMOTION_ATTEMPTS = 3

PREFIX_RE = re.compile(r'^\[T(\d)\s+tools=([^\]]+)\]')
CLAIM_RE = re.compile(r'\bclaim\s+(C-\d+)')

VM_TOOLS = {'vmr-shell', 'rev-frida'}
KNOWN_TOOLS = ('vmr-shell', 'rev-frida', 'malware-framework')

# VM-only dynamic tools (per SKILL.md §Hard prohibitions #5).
# `mcp__x64dbg__start_session` and `mcp__x64dbg__connect_to_session` launch or bind a
# HOST x64dbg — the sample would execute on the host, bypassing
# `block_malware_exec` (which only matches Bash, not MCP). The VM-only path is
# `mcp__x64dbg__connect_remote(host=VM_IP, ...)`, after the VM-side x64dbg is
# launched via vmr-shell. `mcp__frida__spawn` / `mcp__frida__attach` if invoked
# with a host PID likewise run the sample on the host. Use rev-frida via the
# VM-resident frida-server (<VM_IP>:1337) instead. See
# `references/dynamic-re-tool-priority.md` for the launch sequence.
HOST_FORBIDDEN_TOOLS = (
    'mcp__x64dbg__start_session',
    'mcp__x64dbg__connect_to_session',
    'mcp__x64dbg__terminate_session',  # host-side cleanup; do not bind to host session in the first place
    'mcp__x64dbg__connect_to_instance',  # alias path
    'mcp__frida__spawn',
    'mcp__frida__attach',
)


# ---------- best-first priority advisory (imports scripts/priority.py) ----------
_SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))
try:
    from priority import rank_claims as _rank_claims, _weights as _priority_weights
    from status_defs import TERMINAL  # single source of truth (#34, #95)
    _PRIORITY_AVAILABLE = True
except Exception:  # pragma: no cover - hook stays usable if priority.py is moved
    _PRIORITY_AVAILABLE = False

# ---------- issue #310: specialist trigger table (imports route_capability) ----------
try:
    from route_capability import (
        load_specialist_table as _load_specialist_table,
        recommend_agent_type as _recommend_agent_type,
    )
    _AGENTTYPE_AVAILABLE = True
except Exception:  # pragma: no cover - hook stays usable if the router is moved
    _AGENTTYPE_AVAILABLE = False

GENERIC_WORK_AGENT = 'kunglao-worker'

# ---------- #475: tool_error_policy wiring (the missing consumer, #309 debt) ----------
# tool_error_policy.py (WARN=3 / DISABLE=5 hysteresis) had zero consumers —
# this import + post_check application is the mechanical wiring; the policy
# module stays the single sanctioned source (thresholds are never copied).
sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))
try:
    import tool_error_policy as _tep
    TOOL_ERROR_POLICY_LOADED = True
except Exception:  # pragma: no cover — hook stays usable if the policy moves
    _tep = None
    TOOL_ERROR_POLICY_LOADED = False

TOOL_ERRORS_FILE = 'runs/tool-errors.json'


def _load_yaml(path):
    if not path or not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}


def _run_py(args, cwd=None):
    """Run a skill script, fail-open: any subprocess failure -> None."""
    try:
        return subprocess.run(
            [sys.executable] + args,
            capture_output=True, text=True, timeout=20,
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return None


def check_plan_drift(paths):
    """v1.9.29: plan-drift gate wired into PreToolUse. FAIL_OPEN on any
    subprocess/workspace resolution failure — the hook stays usable."""
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([str(_SKILL_ROOT / 'scripts' / 'plan_drift_detector.py'),
                 str(ws), '--active-only'])
    if r is None:
        return True, ''
    if r.returncode == 0:
        return True, ''
    return False, f"plan drift detected (rc={r.returncode}): {(r.stderr or r.stdout or '')[:200]}"


def check_convergence_health(paths):
    """v1.9.29: STALLED/SPINNING gate wired into PreToolUse. FAIL_OPEN on any
    subprocess/workspace resolution failure."""
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([str(_SKILL_ROOT / 'scripts' / 'convergence_health.py'),
                 str(ws)])
    if r is None:
        return True, ''
    if r.returncode == 1:
        return False, "convergence STALLED - diagnose before dispatching"
    if r.returncode == 2:
        return False, "convergence SPINNING - STOP dispatching"
    return True, ''


def check_backtrack_gate(paths):
    """v1.9.29: stuck-worker backtrack gate wired into PreToolUse (#38).
    Mirrors check_plan_drift / check_convergence_health: runs the existing
    backtrack_gate.py via _run_py (20s timeout) and FAIL_OPEN on any
    subprocess/workspace resolution failure — the hook stays usable.

    backtrack_gate rc:
      0  -> clean (no stuck workers, or stuck-but-valid-backtrack)
      1  -> stuck worker(s) without a valid `## backtrack` block
      2  -> stuck >30m, decision != redispatch (stale un-actioned)
      other/None -> fail open (broken gate must not block dispatch)
    """
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([str(_SKILL_ROOT / 'scripts' / 'backtrack_gate.py'),
                 str(ws)])
    if r is None:
        return True, ''
    if r.returncode == 0:
        return True, ''
    if r.returncode == 1:
        return False, ("stuck worker(s) without a valid `## backtrack` block - "
                       "force a backtrack decision before dispatching")
    if r.returncode == 2:
        return False, ("stuck worker(s) with stale backtrack (>30m un-actioned, "
                       "decision != redispatch) - escalate or override to redispatch")
    return True, ''  # unknown rc -> fail open


def check_priority(reg_path, deps_path, task_spec_path, dispatched_cid):
    """Best-first priority audit — v1.9.24 returns (ok, msg, deviated).

    Silent for rank-#1 dispatches; ADVISORY when the dispatched claim is not
    the top-ranked dispatchable one. `deviated=True` means the dispatch
    departed from rank #1 and a `reasoning:` field is HARD-REQUIRED in the
    dispatch prompt (pre_check rejects without it — anti-spoof: prevents
    "pretend-priority" dispatches that skip the recorded-deviation discipline).
    """
    if not _PRIORITY_AVAILABLE or not dispatched_cid:
        return (True, '', False)
    reg = _load_yaml(reg_path)
    deps = _load_yaml(deps_path)
    rows = _rank_claims(reg, deps, _priority_weights(_load_yaml(task_spec_path)))
    if not rows:
        return (True, '', False)
    top = rows[0]
    if top['id'] == dispatched_cid:
        return (True, '', False)  # rank #1 - silent
    rank = next((i + 1 for i, r in enumerate(rows) if r['id'] == dispatched_cid), None)
    if rank is None:
        return (True, f'ADVISORY: {dispatched_cid} not in dispatchable set '
                      f'(rank #1 = {top["id"]} score {top["score"]}); '
                      f'blocked by deps/promotion, or already terminal?', False)
    return (True, f'ADVISORY: dispatched {dispatched_cid} rank #{rank} '
                  f'(score {rows[rank - 1]["score"]}); rank #1 is {top["id"]} '
                  f'(score {top["score"]}) - record a reasoning for the deviation.', True)


# ---------- parsing ----------

def parse_dispatch(description: str) -> tuple[int, list[str], str | None]:
    """Parse '[TN tools=a,b] claim C-NN ...' → (tier, tools, claim_id).

    Returns (0, [], None) if the prefix is absent.
    """
    m = PREFIX_RE.match(description)
    if not m:
        return (0, [], None)
    tier = int(m.group(1))
    tools = [t.strip() for t in m.group(2).split(',') if t.strip()]
    cm = CLAIM_RE.search(description)
    cid = cm.group(1) if cm else None
    return (tier, tools, cid)


# Self-cap detection patterns (sub-agents silently imposing time limits the
# orchestrator did not request). The contract per SKILL.md §3 + DESIGN §15 is
# "no time cap unless task_spec.time_budget_minutes is set"; a user-side change
# to "no budget until closed" runs must propagate as ZERO self-cap.
# Allowed escape: the dispatcher must explicitly say "no self-cap" or
# the orchestrator explicitly negates by including "no time cap" /
# "without time cap" in the same description.
_SELF_CAP_RE = re.compile(
    r'(?:'
    # Hard self-caps with explicit duration (keyword-then-number).
    # IMPORTANT: `cap` standalone needs \b; compound forms (hard cap, wall-clock cap)
    # need \s+ between components because `\bcap` fails to match inside `hard cap`
    # (no word boundary between the space and `cap`).
    # Bare `s` for "30s" abbreviation allowed, with word boundary on the trailing side
    # so "30 ships" doesn't false-positive.
    r'(?:\b(?:cap|max(?:imum)?|limit)|hard\s+cap|wall[- ]?clock\s+cap)[a-z ]{0,15}'
    r'\d+\s*(?:min(?:ute)?s?|sec(?:ond)?s?|hour|day)s?\b|'
    r'\d+\s*s\b'
    # Number-then-duration as a tail qualifier (e.g. "30s window", "5 min cap")
    # Allow 1-letter abbrev: "30s" / "5m" / "2h" / "1d"
    r'|\b\d+\s*(?:m|min(?:ute)?s?|s|sec(?:ond)?s?|h|hour|day)s?\s+(?:cap|window|timeout|budget|wall[- ]?clock|deadline|limit)'
    # Bare duration mentions
    r'|\b(?:run|execute|emulate|sleep|idle)\s+for\s+\d+\s*(?:s|min|sec|hour|day)\b'
    # Wall-time stoppage
    r'|\bstop\s+after\s+\d+\s*(?:s|min|sec|hour)\b'
    r')',
    re.IGNORECASE,
)


def detect_self_cap(description: str) -> tuple[bool, list[str]]:
    """Find self-imposed time caps in a dispatch description.

    The orchestrator contract is "don't add your own time limits unless the
    user authorised them via task_spec.time_budget_minutes > 0". A user who
    replies "no budget, until convergence" is explicit zero.

    Returns (found, offenders); offenders is the list of matched substrings.
    The caller (pre_check) decides whether to reject or just log.
    """
    # allowlist: explicit negation phrases
    negation = re.compile(r'\b(?:no\s+self[- ]?cap|no\s+time\s+cap|no\s+budget|without\s+(?:a\s+)?time\s+cap|drop\s+time\s+cap|until\s+(?:it[''’]?s\s+)?(?:closed|done)|don[''’]?t\s+stop\s+for)\b', re.IGNORECASE)
    if negation.search(description):
        # negation present — only flag if absolute duration numeric appears AFTER negation context
        # For simplicity in v1.8.1: a negation phrase anywhere in description suppresses all caps.
        return (False, [])
    matches = _SELF_CAP_RE.findall(description)
    return (len(matches) > 0, matches)


def tool_to_constraint(tool: str) -> str | None:
    """Map a tool name to the task_spec constraint key it requires, or None."""
    if tool in VM_TOOLS or tool.startswith('mcp__x64dbg'):
        return 'vm_detonation'
    return None


def scan_actual_tools(transcript: str) -> list[str]:
    """Extract tool names actually invoked by a worker (for PostToolUse audit)."""
    found = set(re.findall(r'mcp__[a-z0-9_]+', transcript))
    for name in KNOWN_TOOLS:
        if name in transcript:
            found.add(name)
    return sorted(found)


# ---------- active_workers segment IO ----------

def _format_worker(w: dict) -> str:
    tools = ','.join(w.get('tools', []) or [])
    return (
        f"worker_id={w['worker_id']} | claim_id={w.get('claim_id', '')} | "
        f"dispatched_at={w.get('dispatched_at', 0)} | tier={w.get('tier', 1)} | "
        f"tools={tools}"
    )


def _parse_worker_line(line: str) -> dict:
    entry = {}
    for part in line.split(' | '):
        k, _, v = part.partition('=')
        entry[k.strip()] = v.strip()
    entry['tier'] = int(entry.get('tier', 1))
    if 'dispatched_at' in entry:
        try:
            entry['dispatched_at'] = int(entry['dispatched_at'])
        except ValueError:
            pass
    raw = entry.get('tools', '')
    entry['tools'] = [t.strip() for t in raw.split(',') if t.strip()] if raw else []
    return entry


def read_active_workers(path: Path) -> list[dict]:
    if not path.exists():
        return []
    in_seg = False
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if s == '[active_workers]':
            in_seg = True
            continue
        if s == '[/active_workers]':
            break
        if in_seg and ' | ' in line:
            out.append(_parse_worker_line(line))
    return out


def _replace_segment(text: str, new_worker_lines: list[str]) -> str:
    lines = text.splitlines()
    out = []
    in_seg = False
    written = False
    for line in lines:
        s = line.strip()
        if s == '[active_workers]':
            in_seg = True
            out.append('[active_workers]')
            out.extend(new_worker_lines)
            written = True
            continue
        if s == '[/active_workers]':
            in_seg = False
            out.append('[/active_workers]')
            continue
        if not in_seg:
            out.append(line)
    if not written:
        if out and out[-1] != '':
            out.append('')
        out.append('[active_workers]')
        out.extend(new_worker_lines)
        out.append('[/active_workers]')
    return '\n'.join(out) + '\n'


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


# ---------- claim-status change guard (v1.9.29) ----------
# maker-checker: a WORKER (maker) must never self-promote a claim to PROVEN /
# NEGATIVE / REFUTED / DEFERRED (terminal statuses). Only the orchestrator may
# write terminal status, and only AFTER the kunglao-redteam adversarial pass.
# This hook rejects worker Write/Edit that flips a claim to terminal status.

TERMINAL_CLAIM_STATUSES = {'PROVEN', 'NEGATIVE', 'REFUTED', 'DEFERRED'}


def _claim_statuses(reg_path: Path) -> dict[str, str] | None:
    try:
        d = _load_yaml(reg_path)
        claims = d.get('claims') or []
        if isinstance(claims, dict):
            claims = list(claims.values())
        return {c.get('id'): c.get('status') for c in claims if c.get('id')}
    except Exception:
        return None


def check_claim_status_change(reg_path: Path, agent_name: str) -> tuple[bool, str]:
    """Reject worker self-promotion to terminal status via claim-register edits.

    Returns (ok, reason). ok=False means the Write/Edit must be blocked.
    """
    if not reg_path.exists():
        return True, 'no register'
    if not agent_name or agent_name in ('orchestrator', 'main', 'kunglao-orch'):
        return True, 'orchestrator exempt'
    before = _claim_statuses(reg_path)
    if before is None:
        return True, 'register unreadable'
    # determine changed file from cwd hint is not reliable here; instead, we
    # inspect the file that this hook fired for via tool_input. See post_check.
    return True, 'deferred-to-postcompare'


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
    """
    bad = [t for t in tools if t in HOST_FORBIDDEN_TOOLS]
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
        return (True, 'tool-catalog marker present')
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
            'Fix: add "reasoning: <why C-<NN> instead of the ranked #1 '
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
    """
    from datetime import datetime, timedelta, timezone
    if not state_path.exists():
        return True, 'no kunglao-agent workspace - heartbeat gate skipped'
    # the heartbeat belongs to skill-level monitoring, not the analysis workspace: check the cwd side first, then fall back to the skill install dir
    hb = state_path.parent / 'runs' / '.heartbeat.json'
    _skill = Path(__file__).resolve().parents[1]
    hb_skill = _skill / 'runs' / '.heartbeat.json'

    def _age(hb_path: Path):
        # F1 (#14): liveness = max(last_tick_ts, activity_ts) — tool activity
        # (activity_ts) counts as alive even when the cron does not tick
        # (last_tick_ts stale). Fixes the v1.9.36 semantic split (the hook
        # bumped activity_ts but the gate only read last_tick_ts → the fix
        # never reached the gate).
        try:
            data = json.loads(hb_path.read_text(encoding='utf-8'))
            parsed = []
            for k in ('last_tick_ts', 'activity_ts'):
                v = data.get(k, '')
                if v:
                    try:
                        parsed.append((datetime.fromisoformat(v.replace('Z', '+00:00')), v))
                    except ValueError:
                        pass
            if not parsed:
                return None, ''
            dt, s = max(parsed, key=lambda x: x[0])  # most recent = best liveness
            return (datetime.now(timezone.utc) - dt), s
        except Exception:
            return None, ''

    # workspace heartbeat missing or expired → use the fresh heartbeat from the skill dir (unified skill-monitoring registration point)
    ws_age, ws_last = _age(hb) if hb.exists() else (None, '')
    if ws_age is None or ws_age > timedelta(minutes=35):
        sk_age, sk_last = _age(hb_skill) if hb_skill.exists() else (None, '')
        if sk_age is not None and sk_age <= timedelta(minutes=35):
            hb = hb_skill
    if not hb.exists():
        return (False,
                'heartbeat NOT registered. BEFORE dispatching, run:\n'
                '  uv run --project <skill> <skill>/scripts/hook_activation.py <ws> --heartbeat-on\n'
                '  CronCreate */5 * * * * <heartbeat_loop_prompt.py output>\n'
                'S6.1b v1.9.28: dispatching a task != monitoring started.')
    age, last_str = _age(hb)
    if age is None:
        return (False,
                'heartbeat file unreadable / no parseable timestamps - re-register with --heartbeat-on')
    if age > timedelta(minutes=35):
        return (False,
                f'heartbeat STALE ({int(age.total_seconds()//60)} min > 35) - cron not '
                f'ticking AND no recent tool activity. Re-register: --heartbeat-on + CronCreate /loop 5m.')
    return (True, f'heartbeat alive (last activity {last_str})')


# v1.9.39 (#475): env-state freshness gate constants. TTL aligns with the
# tick cadence family (5-min cron / 35-min heartbeat ceiling): 30 min = one
# heartbeat TTL window of drift tolerance; 2x = the hard self-heal line.
ENV_STATE_TTL_MINUTES = 30
ENV_STATE_FILE = 'runs/env-state.json'
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


def pre_check(payload: dict, paths: dict) -> int:
    desc = payload.get('tool_input', {}).get('description', '')
    prompt = payload.get('tool_input', {}).get('prompt', '')
    agent_name = payload.get('tool_input', {}).get('name') or ''
    tier, tools, cid = parse_dispatch(desc)
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
        ('agenttype', check_agent_type(paths, desc, prompt, agent_name)),
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
    _pok, pmsg, deviated = check_priority(paths.get('register'), paths.get('deps'), paths.get('task_spec'), cid)
    if deviated:
        desc = payload.get('tool_input', {}).get('prompt', '')
        if 'reasoning:' not in desc:
            return _reject('devreason',
                           'dispatch deviates from priority #1 but has no '
                           '`reasoning:` field (v1.9.24 anti-spoof). '
                           f'PRIORITY: {pmsg}', paths)
        print(f'PRIORITY (deviated w/ reasoning): {pmsg}', file=sys.stderr)
    elif pmsg:
        print(f'PRIORITY: {pmsg}', file=sys.stderr)
    worker_id = agent_name or f'w{int(time.time())}'
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
    return 0


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
