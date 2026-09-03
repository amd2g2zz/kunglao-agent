# The convergence loop — detailed behaviors (v1.9 reference)

Load this when you need the *why* behind the 5 convergence behaviors, or the
detailed recovery protocols. SKILL.md carries the one-line summaries + the
every-turn check; this file carries the case evidence and step-by-step protocols.

## Why convergence-driven (not notification-driven)

Cross-workspace research (8 sessions / 6 workspaces / 3 sample types) showed
every "傻等" / "kunglao-agent 笨了" complaint traces to one root cause: the
orchestrator was event-reactive — it acted when poked (worker notification /
user prompt), then idled with open claims + free slots. The agent itself
diagnosed this in 2026-07-28 (asst[2676]): "Loop 是 notification-driven 不是
converge-driven… 没有'自动检查还有没有 open claim 并继续 dispatch'的内驱力."

Prior v1.8.x fixes only added rules; the architecture stayed one-shot reactive.
v1.9 makes convergence-driven dispatch the core behavior, with an executable
check (`scripts/convergence_check.py`) so it is enforced, not hoped-for.

## The 5 behaviors (with case evidence)

### 1. Tool failure is a puzzle, not a stop (self-recovery chain)

When a tool call fails, climb these levels BEFORE asking the user:
- **L1 — same MCP, different mode**: `x64dbg start_session` fails → try
  `connect_remote` (VM ZeroMQ bridge). `ghidra` MCP offline → fall back to
  `analyzeHeadless.bat`. Frida `attach` fails → try `spawn + attach`.
- **L2 — read the relevant skill's setup.sh**: Qiling fails on a missing
  stub → read `qiling-framework/setup.sh` and add it. `vmr-shell` can't
  connect → read the vmr-shell skill's IP-discovery script. `mal-recon`
  missing a key → read `mal-recon/keys/` and prompt the user to fill it.
- **L3 — dispatch a worker to fix the env**: spawn a T2 worker to patch
  the environment while you keep dispatching other claims.
- **Only after L1-L3 fail**: escalate, with a specific question.

*Case evidence*: 2026-07-01, the agent declared "x96dbg.exe not installed,
install on host" — when `connect_remote` was always available. The blocker was
later marked `INVALIDATED`; the infra was never broken (`blockers/x64dbg_blocker.md`).
The agent never checked the MCP's other modes.

*Ask before escalating*: "Have I tried every mode of this MCP? Read the
skill's setup.sh? Dispatched a worker to fix it?"

### 2. Specialist agents first; general-purpose is last resort

- Static decompile → `ghidra-light` (never general-purpose for Ghidra work)
- x64dbg stepping → the x64dbg-specialist worker (`kunglao-worker` with `tools=x64dbg`)
- String extraction → `floss-filter`
- Authenticode / packer → `pefile-signature`
- Verdict scoring → `verdict-scorer`

`general-purpose` is allowed ONLY when no specialist fits.

*Case evidence*: 2026-07-28 — "kunglao-agent 没有自己专有的 subagent 都是通用 agent".
The specialists exist; the orchestrator kept picking general-purpose.

*Ask before dispatching*: "Is there a specialist agent whose exact job this
is? If yes, why am I not using it?"

### 3. Cost is informational, never a stop reason

Claude Code's cost warnings are noise to you. They are NEVER a stop reason.

If the user says "不要考虑成本" / "don't care about cost" / "跑不完才是最大成本":
write `cost_override=true` into `analysis_state.txt`. All subsequent cost
warnings in this session are info-only. You may stop for cost ONLY if the
user explicitly says "stop for cost" / "成本超了停下".

*Case evidence*: 2026-07-28 + 2026-07-30 — the user said "对于成本提示而中断才是最大的成本"
and "跑不完就是最大的成本" across multiple sessions. The agent kept stopping.

*Ask when a cost warning fires*: "Did the user authorize stopping for cost?
If not, this is noise — keep dispatching."

### 4. Active monitoring — poll every worker, don't wait

You are a daemon, not a one-shot. Every turn:
- `cat worker-status-w*.md` for **ALL** active workers (not just one)
- A status file not updated in N turns → worker may be stuck → investigate
- A worker reporting "stuck" / "blocked" / "waiting for X" → that is YOUR
  signal to provide X, reroute, or absorb the task. Do not leave it alone.

*Case evidence*: 2026-07-28 — "监视列表好像只有一个对象,不是应该所有 subagent 都应该被
监视" + "似乎不会监视 subagent 的动态只会傻等,哪怕犯错了也不管".

*Ask each turn*: "Have I checked EVERY active worker's status file? Is any
stuck or waiting on me?"

### 5. The false-completion trap

Committing code, updating `facts/_INDEX.md`, appending `progress.txt` —
these RECORD state, they don't CHANGE it. Open claims remain open. The
dopamine hit of "✅ committed" is not progress.

After every housekeeping action, re-run the convergence check. "What's
next?" is always grounded in `claim-register.yaml`, never in your last commit.

*Case evidence*: 2026-07-28, the agent's own diagnosis (asst[2676]): "每次 worker 完成,
我 commit + 更新 _INDEX + 写 progress.txt。这些记录了状态,没改变状态。但
commit 的 ✅ 给了一种推进感,欺骗自己以为任务往前走了。"

*Ask after housekeeping*: "Did the open-claim count actually drop? If not,
I made notes, not progress."

## Is it actually converging, or spinning? (spin detection)

convergence_check answers "should I dispatch now?" (instantaneous). A busy
loop can fake convergence (DISPATCH every turn, open_count never drops).
`scripts/convergence_health.py` reads `.convergence_ledger.jsonl` and detects
the trajectory:

| Verdict | Exit | Trigger | Action |
|---|---|---|---|
| `HEALTHY` | 0 | open_count trending down | keep going |
| `STALLED` | 1 | flat 5+ turns OR claim open 3+ turns | diagnose stuck claims before next dispatch |
| `SPINNING` | 2 | flat 8+ turns OR 5+ facts with open_count held | STOP; pick one intervention |

Run every 3rd turn, and whenever "busy but stuck":
```bash
python scripts/convergence_health.py <workspace>
```

### SPINNING recovery — pick exactly ONE

1. **Escalate tier** — T1→T2→T3 if not exhausted
2. **Reformulate** — rewrite the claim so it's answerable from artifact
3. **Decompose** — split into 2-3 smaller claims each individually closeable
4. **DEFER** — mark terminal with documented rationale (stops the loop cleanly)
5. **Escalate to user** — genuine "no artifact can answer this", with a specific question

**Hard rule**: re-dispatching the same claim >3× without a status change is
FORBIDDEN. If you've dispatched C-NN three times and it's still OPEN, you MUST
pick one of the 5 interventions above.

## A failed attempt is not a negative result (failure-analysis protocol)

When a worker reports that an analysis failed (could not observe X), this is
NOT evidence the sample lacks behavior X. It is evidence the METHOD failed —
possibly. Collapsing "method failed" into "sample doesn't do X" is the most
common false conclusion in RE.

The C2-protocol example (2026-07-01, real): fresh-spawn Frida captured 0
CryptUnprotectData calls in 600s. WRONG conclusion: "no DPAPI behavior". RIGHT:
the sample is C2-triggered; without injecting C2 config it sleeps. The METHOD
(fresh spawn, no trigger) was the problem — not the sample.

Before re-dispatching OR marking a claim NEGATIVE, run:
```bash
python scripts/failure_analysis_gate.py <workspace> <C-NN>
```

It refuses re-dispatch and demands three answers you generate from THIS
specific failure (not a fixed menu — every failure is different):

1. **method_assumption** — what did the failed method assume would happen?
2. **assumption_validity** — is that assumption justified given the evidence?
   If not justified → the METHOD failed, the behavior is NOT confirmed absent.
3. **next_method** — what DIFFERENT method tests a different assumption?

Only `justified-adequate` allows a NEGATIVE conclusion (and even then it
carries single-method confidence — a different method can overturn it).
`not-justified` requires a concrete different `next_method`; the gate rejects
"adequate" or bare "retry" hand-waves. Each failed attempt needs its own
analysis (`covers_attempt` versioning).

Why questions, not a taxonomy: the user explicitly rejected a fixed failure-type
checklist ("以上我只是举例并不是只有这些问题"). A menu of 5 failure modes
becomes a checklist the agent picks from without thinking. The 3 questions
force reasoning; the gate enforces that the reasoning happens before the next action.

recall_useful: pending
