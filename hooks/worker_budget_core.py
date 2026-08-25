# -*- coding: utf-8 -*-
from __future__ import annotations
"""worker_budget_core — constants, IO, parsing, claim-register primitives.

#568: extracted from worker_budget.py (was 1847L > 800L limit). This module
holds the cross-cutting primitives the gates / sinks modules import from."""



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

# v0.1.3 (#604): worker-level silent-failure retry counter. Distinct from
# MAX_PROMOTION_ATTEMPTS (#520) which tracks claim-level PROVEN attempts.
# MAX_RETRIES tracks WORKER-level silent-failure retries on the same
# (worker_id, claim_id): when a worker silently dies/hangs and gets
# re-dispatched 3 times on the same claim, the gate escalates to BLOCKED +
# failure-analysis artifact. The two counters are independent — a claim can
# have promotion_attempts=2 while a worker simultaneously has retries=2 on it.
MAX_RETRIES = 3

RETRY_COUNTER_FILE = 'runs/.retry-counter.yaml'

# v1.9.39 (#475): env-state freshness gate constants. TTL aligns with the
# scripts/kunglao-monitor.py advisory (drift detection uses the same value).
# #597: the TTL VALUE is single-sourced in scripts/liveness_policy.py (THE
# liveness-minutes source; hooks/ and scripts/ ship together, #444 posture).
ENV_STATE_FILE = 'runs/env-state.json'
_scripts_dir = str(Path(__file__).resolve().parent.parent / 'scripts')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from liveness_policy import ENV_STATE_TTL_MINUTES  # noqa: E402

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


# ---------- best-first priority advisory (imports scripts/priority_ratio.py) ----------
# #499: priority_ratio is THE sanctioned next-claim scorer (specs/phase-4/
# contract.md §1 — the DECIDE ranker, issue #2 VoI proxy). The legacy
# weighted ranker is deprecated (retirement: #446).
_SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))
try:
    from priority_ratio import priority_ratio as _ratio_rank, EvidenceView as _EvidenceView
    from retract_claim import RETRACTED  # retracted = terminal (#331)
    from status_defs import TERMINAL  # single source of truth (#34, #95)
    _PRIORITY_AVAILABLE = True
except Exception:  # pragma: no cover - hook stays usable if the scorer moves
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

# ---------- #461: dispatch linkage (hook_activation renewal entry reuse) ----------
# The four lifecycle effects a PASSING dispatch must have (issue #461 core
# claim: spawn IS a lifecycle event). Reuses hook_activation's existing
# primitives (dispatch_linkage = update_state/write_state/renew) and the
# existing unified event log (kunglao_log.emit -> runs/logs/kunglao-*.jsonl,
# the #459 target) — no new activation mechanism, no fourth liveness
# representation (#446 F-class red line). Import-guarded fail-open: a hook
# must stay usable even if the scripts/ modules move.
sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))
try:
    import hook_activation as _ha_link
except Exception:  # pragma: no cover - hook stays usable if the module moves
    _ha_link = None
try:
    import kunglao_log as _klog
except Exception:  # pragma: no cover - logging must never break the hook
    _klog = None


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


def check_priority(reg_path, deps_path, task_spec_path, dispatched_cid, ws=None):
    """Best-first priority audit — v1.9.24 returns (ok, msg, deviated). #499:
    ranks by the authoritative VoI scorer (priority_ratio.py — specs/phase-4/
    contract.md §1), NOT the deprecated weighted module.

    Silent for rank-#1 dispatches; ADVISORY when the dispatched claim is not
    the top-ranked dispatchable one. `deviated=True` means the dispatch
    departed from rank #1 and a `reasoning:` field is HARD-REQUIRED in the
    dispatch prompt (pre_check rejects without it — anti-spoof: prevents
    "pretend-priority" dispatches that skip the recorded-deviation discipline).

    task_spec_path is kept for signature stability only — the VoI weights are
    spec-frozen (0.45/0.30/0.25); the old priority_weights/PRIORITY_WEIGHTS
    override does not apply to the authority scorer.

    Caller-side filtering is the caller's job (contract §1 — the pure function
    takes no ws): failure-blocked claims (failed attempt, no current
    failure_analysis) are excluded so this audit never contradicts
    convergence_check, and RETRACTED counts as terminal (#331), matching the
    convergence truth face. The filter stays MINIMAL on purpose (injection
    M4 guard): RETRACTED is the one status ratio.is_open misses
    (status_defs.TERMINAL is frozen without it), so it is removed here;
    DEFERRED/STALE/PROVEN/... terminal rows STAY in the list handed to
    _ratio_rank — is_open already excludes them from candidacy, and their
    rows feed the novelty derivation (_fact_count_by_category keys terminal
    facts to claims by id); over-filtering silently drops their categories
    from novelty counting.
    """
    if not _PRIORITY_AVAILABLE or not dispatched_cid:
        return (True, '', False)
    reg = _load_yaml(reg_path)
    deps = _load_yaml(deps_path)
    claims = [c for c in (reg.get('claims') or []) if c.get('id')]
    evidence = _EvidenceView()
    if ws:
        ws_path = Path(ws)
        try:
            import failure_analysis_gate as fag
            blocked_ids = {b['claim_id'] for b in fag.scan_workspace(ws_path)
                           if b.get('state') == 'BLOCKED'}
            claims = [c for c in claims if c.get('id') not in blocked_ids]
        except Exception:  # pragma: no cover - the audit stays usable, fail-open
            pass
        evidence = _EvidenceView.from_workspace(ws_path)
    # RETRACTED is terminal (#331) — ratio.is_open keys off status_defs.TERMINAL
    # (frozen without RETRACTED), so THIS caller removes it. Every other
    # terminal-status row is kept: is_open already excludes it from candidacy,
    # and its row feeds the novelty fact counting (M4 guard).
    claims = [c for c in claims if (c.get('status') or '').upper() != RETRACTED]
    actions = _ratio_rank(claims, deps, evidence)
    if not actions:
        return (True, '', False)
    top = actions[0]
    if top.claim_id == dispatched_cid:
        return (True, '', False)  # rank #1 - silent
    rank = next((i + 1 for i, a in enumerate(actions) if a.claim_id == dispatched_cid), None)
    if rank is None:
        return (True, f'ADVISORY: {dispatched_cid} not in dispatchable set '
                      f'(rank #1 = {top.claim_id} score {top.score}); '
                      f'blocked by deps/promotion, or already terminal?', False)
    return (True, f'ADVISORY: dispatched {dispatched_cid} rank #{rank} '
                  f'(score {actions[rank - 1].score}); rank #1 is {top.claim_id} '
                  f'(score {top.score}) - record a reasoning for the deviation.', True)


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
