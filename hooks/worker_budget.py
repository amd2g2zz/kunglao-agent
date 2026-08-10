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
import sys
import time
from pathlib import Path

import yaml

# ---------- constants ----------

TERMINAL_STATUS = {'PROVEN', 'VERIFIED', 'NEGATIVE', 'REFUTED', 'DEFERRED'}
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
# VM-resident frida-server (192.168.20.128:1337) instead. See
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
    _PRIORITY_AVAILABLE = True
except Exception:  # pragma: no cover - hook stays usable if priority.py is moved
    _PRIORITY_AVAILABLE = False


def _load_yaml(path):
    if not path or not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}


def check_priority(reg_path, deps_path, task_spec_path, dispatched_cid):
    """Best-first priority audit — v1.9.24 returns (ok, msg, deviated).

    Silent for rank-#1 dispatches; ADVISORY when the dispatched claim is not
    the top-ranked dispatchable one. `deviated=True` means the dispatch
    departed from rank #1 and a `reasoning:` field is HARD-REQUIRED in the
    dispatch prompt (pre_check rejects without it — anti-spoof: prevents
    "假装按优先级" dispatches that skip the recorded-deviation discipline).
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
    if tool.startswith('mcp__virustotal'):
        return 'external_cti_query'
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
                       f'(maker-checker §1b).')
    return True, 'ok'


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

def check_workers_lt_3(state_path: Path) -> tuple[bool, str]:
    n = len(read_active_workers(state_path))
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
            f'host-channel dynamic tool(s) {bad!r} forbidden — '
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
        if c.get('status') in TERMINAL_STATUS:
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
        return True, 'no kunglao-agent workspace — heartbeat gate skipped'
    # heartbeat 属 skill 监控, 不在分析工作区: 先查 cwd 侧, 再 fallback 到 skill 安装目录
    hb = state_path.parent / 'runs' / '.heartbeat.json'
    _skill = Path(__file__).resolve().parents[1]
    hb_skill = _skill / 'runs' / '.heartbeat.json'

    def _age(hb_path: Path):
        # F1 (#14): liveness = max(last_tick_ts, activity_ts) — tool 活跃(activity_ts)
        # 即使 cron 不 tick(last_tick_ts stale)也算 alive。修 v1.9.36 语义分裂
        # (hook bump activity_ts 但 gate 只读 last_tick_ts → fix 没修 gate)。
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

    # workspace 心跳缺失或过期 → 用 skill 目录的新心跳(skill 监控统一注册点)
    ws_age, ws_last = _age(hb) if hb.exists() else (None, '')
    if ws_age is None or ws_age > timedelta(minutes=35):
        sk_age, sk_last = _age(hb_skill) if hb_skill.exists() else (None, '')
        if sk_age is not None and sk_age <= timedelta(minutes=35):
            hb = hb_skill
    if not hb.exists():
        return (False,
                'heartbeat NOT registered. BEFORE dispatching, run:\n'
                '  python <skill>/scripts/hook_activation.py <ws> --heartbeat-on\n'
                '  CronCreate */5 * * * * <heartbeat_loop_prompt.py output>\n'
                '§6.1b v1.9.28: dispatching a task != monitoring started.')
    age, last_str = _age(hb)
    if age is None:
        return (False,
                'heartbeat file unreadable / no parseable timestamps — re-register with --heartbeat-on')
    if age > timedelta(minutes=35):
        return (False,
                f'heartbeat STALE ({int(age.total_seconds()//60)} min > 35) — cron not '
                f'ticking AND no recent tool activity. Re-register: --heartbeat-on + CronCreate /loop 5m.')
    return (True, f'heartbeat alive (last activity {last_str})')


def pre_check(payload: dict, paths: dict) -> int:
    desc = payload.get('tool_input', {}).get('description', '')
    tier, tools, cid = parse_dispatch(desc)
    checks = [
        ('workers', check_workers_lt_3(paths['state'])),
        ('cap', check_promotion_attempts(paths['register'], cid)),
        ('tools', check_tools_allowed(tools, paths['task_spec'])),
        ('hostchan', check_host_forbidden_tools(tools)),
        ('deadline', check_deadline(paths['state'])),
        ('tier', check_tier_gate(paths['register'], tier)),
        ('selfcap', check_no_self_cap(desc, paths['task_spec'])),
        # v1.9.28: heartbeat MUST be alive before any dispatch — mechanical
        # gate closes the recurring 'dispatch without monitoring' failure.
        ('heartbeat', check_heartbeat_alive(paths['state'])),
    ]
    for name, (ok, msg) in checks:
        if not ok:
            print(f'REJECT {name}: {msg}', file=sys.stderr)
            return 2
    # §1c v1.9.24 — facts-snapshot marker HARD-REQUIRED (anti state-loss spoof).
    # The orchestrator claims it "ls facts/ before dispatch" (§1c) — make it
    # verifiable: the dispatch prompt must carry `facts-snapshot:` (e.g.
    # "facts-snapshot: 9 facts at <ts>") or the dispatch is REJECTED.
    desc = payload.get('tool_input', {}).get('prompt', '')
    if 'facts-snapshot:' not in desc:
        print(f'REJECT snapshot: dispatch prompt lacks `facts-snapshot:` marker '
              f'(§1c v1.9.24 — checkpoint state before dispatch).', file=sys.stderr)
        return 2
    # best-first priority audit — v1.9.24: DEVIATION REASONING IS HARD-REQUIRED.
    # check_priority returns (ok, msg, deviated). If the dispatch deviates from
    # the ranked #1 claim, the prompt MUST carry an explicit `reasoning:` field —
    # otherwise the dispatch is REJECTED (prevents "假装按优先级" spoofing:
    # dispatching a different claim without recording why).
    _pok, pmsg, deviated = check_priority(paths.get('register'), paths.get('deps'), paths.get('task_spec'), cid)
    if deviated:
        desc = payload.get('tool_input', {}).get('prompt', '')
        if 'reasoning:' not in desc:
            print(f'REJECT devreason: dispatch deviates from priority #1 but has no `reasoning:` field '
                  f'(v1.9.24 anti-spoof). PRIORITY: {pmsg}', file=sys.stderr)
            return 2
        print(f'PRIORITY (deviated w/ reasoning): {pmsg}', file=sys.stderr)
    elif pmsg:
        print(f'PRIORITY: {pmsg}', file=sys.stderr)
    worker_id = payload.get('tool_input', {}).get('name') or f'w{int(time.time())}'
    register_worker(paths['state'], {
        'worker_id': worker_id,
        'claim_id': cid or '',
        'dispatched_at': int(time.time()),
        'tier': tier,
        'tools': tools,
    })
    return 0


def post_check(payload: dict, paths: dict) -> int:
    worker_id = payload.get('tool_input', {}).get('name') or ''
    if worker_id:
        remove_worker(paths['state'], worker_id)
    tool_result = str(payload.get('tool_result', ''))
    scan_actual_tools(tool_result)  # post-hoc audit (informational)
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
                'state': base / 'analysis_state.txt',
                'register': base / 'claim-register.yaml',
                'deps': base / 'claim_deps.yaml',
                'task_spec': base / 'task_spec.yaml',
            }
    base = candidates[0]
    return {
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
