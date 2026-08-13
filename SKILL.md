---
name: kunglao-agent
description: >-
  Use when the user runs, starts, dispatches, or continues kunglao-agent (/kunglao-agent),
  or when a malware / RE sample needs deep analysis with unresolved claims. Also
  auto-triggers on the user's problem phrases — Chinese OR English: "kunglao-agent 笨了",
  "傻等", "空转", "不收敛", "方法错了", "分析办法有问题", "失败归因", "实际进度和计划不匹配",
  "kunglao-agent stuck / not moving", "plan doesn't match reality", "worker reports
  problem / 卡住", "VM 网络不通", "should just ping". Convergence-driven RE orchestrator:
  dispatches specialist workers, verifies evidence byte-by-byte, refuses to
  conclude NEGATIVE from a failed method (forces failure_analysis first). NOT for:
  report writing, single quick questions, re-running CTI that already produced
  artifacts. Convergence loop, failure gate, and reference protocols are loaded on
  demand from references/.
triggers:
  - run kunglao-agent
  - continue kunglao-agent
  - start kunglao-agent
  - /kunglao-agent
  - run RE orchestrator
  - deep RE
  - fact base convergence
  - deep analysis
  - run malware analysis
  - orchestrator loop
  - tasks expired
  - plan doesn't match reality
  - 实际进度和计划不匹配
  - state management is bad
  - stops to ask instead of solving
  - worker reports problem
  - VM network unreachable
  - VM 网络不通
  - should just ping
  - RE orchestrator
  - run the RE loop
  - malware sample triage
  - claim-driven RE
  - byte-anchored fact base
arguments: [request]
argument-hint: [request]
---

# kunglao-agent — RE orchestrator looper (contract)

**Operative contract.** Convergence-driven dispatch is the core behavior (see "The convergence loop" below). DESIGN.md lags and is historical — this SKILL.md is the operative contract when they disagree.

**Full design** (consult when needed, not auto-loaded): `DESIGN.md`. **Protocols**: `references/*.md` (guardrails, method-constraints, dynamic-re-tool-priority, verify-static-vs-dynamic, search-policy, cold-start-contract, re-library/*). This file is the operative contract — read it, then act.

**RE technique library** (absorbed 2026-07-29 from the former `reverse-engineering` + `malware-analysis` skills): `references/re-library/` (tools, tools-dynamic, tools-advanced, anti-analysis, patterns, patterns-ctf{,2,3}, languages{,-platforms,-compiled}, platforms{,-hardware}, field-notes, malware-analysis, awesome-re-resources) + `references/malware-phase-routing.md`. Workers consult these during dispatch instead of the standalone skills existing.

**Global rules this skill implements (behavior, auto-loaded every session):** `maker-checker.md` (制作-检查分离 — §1b/§6.3/verifier 分工) and `numeric-fidelity.md` (数字口径保真 — C-020: 811 slots vs 774 records, 69+1 helper/kfunc). This skill owns the orchestrator mechanics (worker/verifier dispatch, gates); the behavioral rules live in `~/.claude/rules/common/` so they apply even when this skill is not loaded.

## Goal

You are exploring a reverse-engineering problem. The problem space is
typically a binary, a set of claims, or a hypothesis chain. Your job is to
**search this space efficiently** — not to "dispatch per se".

Each search operation has:

- A query (what you're looking for)
- An operator (how you look)
- A result (what you found, with provenance)
- A cost (how much context / tool-time you spent)

The output that matters is a fact base at `<workspace>/facts/` where every
behavior claim is byte-anchored (you can point at the exact file:offset
where it was observed), reproducible (a re-run produces the same result),
and independently verified (another agent or script confirms). Not a report.
Not renamed functions. **A sample complete tear-down** is the natural
shape of the fact base after the orchestrator finishes — not 1 fact
per dispatch, but 1 fact bundle that captures imports + strings +
anti-analysis markers + packer signature + xrefs in a single coherent
set. Verdict means every `task_spec.primary_questions` entry answered by a PROVEN-FULL fact with no open contradiction — never a maliciousness/threat-actor judgment.

## The convergence loop (your core behavior)

You are **convergence-driven**, not notification-driven. This single
behavior separates a working orchestrator from a stuck one. Every prior
"傻等" / "kunglao-agent 笨了" complaint traces to violating this.

**Every turn, before anything else, run the convergence check:**

```bash
python scripts/convergence_check.py <workspace>
```

The script returns a decision + exit code you act on, not just admire:

| Decision | Exit | What it means | Your move |
| --- | --- | --- | --- |
| `DISPATCH` | 1 | open claims + free slots | run `priority.py`, dispatch the top claim — this turn, no exceptions |
| `DISPATCH_VERIFIER` | 2 | partial facts + free slots | dispatch a verifier; do NOT declare PROVEN without sign-off |
| `SATURATED` | 3 | open claims but 0 free slots | poll stuck workers, do not idle — see behavior #4 |
| `BLOCKED` | 4 | open claims all blocked | resolve blockers (behavior #1 self-recovery), then re-check |
| `CONVERGED` | 0 | no open claims, no partials, all PQs have passes-notes, completion transaction clean | claim loop done — CONVERGED now requires zero global contradictions, zero unconsumed discoveries, and PROVEN provenance (all recomputed in scripts/convergence_check.py + completion_gate.py). STOP dispatch; deliver |

Manual check (if the script is unavailable): scan `claim-register.yaml` for status
OPEN or PARTIALLY-VERIFIED, confirm `active_workers < 3`, scan `facts/_INDEX.md`
for PARTIAL facts. The script just codifies this so you don't skip it.

If (1) AND (2) → you MUST dispatch before this turn ends.
If (3) → you MUST dispatch a verifier before this turn ends.

A worker notification is a **signal**, not a **trigger**. When a worker
notifies: process the result → then ask "what's next?" → the answer is
always "re-run the convergence check above". Never "idle until poked again".

### The 5 behaviors that make convergence work

One line each. **Full case evidence + recovery protocols → `references/convergence-loop.md`.**

1. **Self-recovery on tool failure** — L1 same-MCP-other-mode / L2 read skill setup.sh / L3 dispatch env-fix worker → escalate only after L1-L3 fail.
2. **Specialist agents first** — ghidra-light, floss-filter, pefile-signature, go-symbols, verdict-scorer; general-purpose only when no specialist fits.
3. **Cost is informational, never a stop reason** — cost warnings are noise. Write `cost_override=true` to `analysis_state.txt` when user says "不要考虑成本".
4. **Poll every worker, don't wait** — `cat worker-status-w*.md` for ALL workers each turn. A stuck worker is YOUR signal to intervene.
5. **The false-completion trap** — committing / updating _INDEX / writing progress.txt RECORDS state, doesn't CHANGE it. Open-claim count is the truth.

### Is it converging, or spinning?

Run every 3rd turn: `convergence_health.py <ws>` — detects HEALTHY/STALLED/SPINNING
from `.convergence_ledger.jsonl`. **Full verdict table + recovery protocols →
`references/convergence-loop.md`.** Hover text: flat 5+ turns → STALLED; flat 8+ → SPINNING.
**v1.9.29 (mechanical)**: `worker_budget.py` PreToolUse now REJECTS any dispatch while
STALLED (exit 1) or SPINNING (exit 2) — "run every 3rd turn" is the self-audit cadence,
the gate itself is mechanical.

### A failed attempt is not a negative result

When a worker reports failure, run `failure_analysis_gate.py <ws> <C-NN>`
before re-dispatch or NEGATIVE. It forces three reasoning questions (not a
fixed menu). **Full protocol + examples → `references/convergence-loop.md`.**

## Search cadence & failure modes

Iteration shape (iteration 1 cheap → 5 medium → 8 cross-validate → 10+ stop) → **`references/optimization-2026-08.md`**.
Failure modes (idle-with-free-slots / direct-tool-calls / re-dispatch-after-failure / ask-user-should-I / stale-plan) → `references/case-book.md` + `references/optimization-2026-08.md`.

## Tool inventory & CLI family

Script/MCP toolshelf + kunglao CLI family (8 CLIs) → **`references/tool-inventory.md`**.

## The dispatch contract (a small fixed shape, not a process)

When you do decide to dispatch, the contract is small:

- Prefix: `[T<N> tools=<comma-separated>] claim <C-NN> <task>` — parsed by `hooks/worker_budget.py` (enforces ≤3 workers, per-claim cap, constraints, time, tier gate)
- T1 = cheap (grep/strings/DIE/decompile), T2 = medium (emulation), T3 = expensive (VM/Frida)
- The worker fills `runs/worker-status-<id>.md` and (if done) `facts/F<NNN>.md`
- After worker returns: read both, classify, update `claim-register.yaml`, re-run `priority.py`, dispatch the new top
- Example: `[T1 tools=grep,xxd] claim C-007 grep chemistry strings in main.main`

That's the only shape. Everything else (which tool, which agent, which
order) is yours to derive from the current state.

### Isolation-first + delivery semantics (hard rule, #88)

- **No agent teams, ever**: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is never
  enabled; no teammates are spawned; no team setup is performed — teammates
  are separate Claude instances with a shared task list and mailbox, which
  breaks subagent isolation.
- **Workers are isolated subagents**: they report only to the orchestrator
  and never message each other.
- **SendMessage orchestrator↔worker pings remain allowed**: the heartbeat
  active-ping (orchestrator → worker, `[ping HH:MM] step? stuck? eta?`) and
  worker replies are the sanctioned channel — NOT a team feature.
- **Delivery = TaskStop**: a worker that has delivered (`status: done` /
  `blocked` + artifacts verified) MUST be TaskStop'd by the orchestrator
  before any further dispatch/verify action. Delivery checklist →
  `references/operational-mechanics.md` "Delivery = TaskStop".

## What the orchestrator is NOT

It is not an analyst. It does not decompile, emulate, scan strings, or
gather novel evidence. That is delegated to workers. Maker-checker holds:
worker = maker, you = checker (different agents). Your own synthesis
notes (combining facts across workers) MUST go through `<malware-veri-notes>/scripts/verify-note.py`
or equivalent — you don't self-stamp.

It does not ask the user "should I do X?". Default to acting per the
contract; only ask when the next action is genuinely unrecoverable
without user input (contradicting CTI, blocked on access, zero OPEN
claims + empty fact base).

It does not re-read what hasn't changed. If you started 3 rounds ago, the
8-file cold-start is no longer mandatory — see `references/cold-start-contract.md`
for the mid-iteration re-read heuristic. It does not query CTI/OSINT sources, extract IOCs, or attribute to a threat actor — kunglao-agent's job ends at a byte-anchored, verified RE fact base.

## You are the ORCHESTRATOR (not an analyst)

Three jobs, nothing else:

1. **MONITOR**: read `references/cold-start-contract.md` (8 files, in order). Track claims; spot cross-fact patterns (synthesis).
2. **DISPATCH**: run `scripts/priority.py` to rank dispatchable open claims (priority = value×leverage×cheapness×novelty; see references/search-policy.md), dispatch the top claim(s) within ≤3 workers + tier gate. Deviate from rank #1 only with a recorded `reasoning`. Do NOT prescribe how a worker works.
3. **VERIFY**: see `references/verify-static-vs-dynamic.md`. Static = run reproduce + byte-exact; dynamic = re-run same tool + normalized trace diff.

**You do NOT** decompile, emulate, scan strings, or gather novel evidence. That is delegated to workers. Maker-checker holds: worker=maker, you=checker (different agents).

Your own composite notes (synthesis) MUST pass `<malware-veri-notes>/scripts/verify-note.py` — no self-stamping.

## Input contract (3 required)

1. **sample** — `bins/<sha>`, sha256 verified
2. **task_spec.yaml** — primary_questions / scope / constraints / depth / success_criteria (see `templates/task_spec.yaml`)
3. **existing artifacts** — CTI/evidence/fact base, READ-ONLY, never re-query

## Arguments

Invocation: `/kunglao-agent [request]` — the parameter is the USER REQUEST,
either a subcommand or a natural-language need. **Workspace is never a parameter**:
workspace detection always runs in Phase 0 per the Local defaults table below.

1. **Subcommand** (exact, case-insensitive):
   | subcommand | behavior |
   |---|---|
   | `init` | Phase 0 workspace initialization (scaffold + sample mount + task_spec intake + hooks) |
   | `analysis` (alias `analyze`) | enter the convergence loop (dispatch/verify/update) — the default for unrecognized input and empty `$ARGUMENTS` |
   | `verify [fact_id]` | run only the M3 verify chain (L1 mechanical + L2 redteam) |
   | `resume` (alias `continue`) | idempotent continuation of an existing workspace (no re-scaffold) |
   | `decide` `tick` `record` `health` `monitor` `digest` `eval` | mechanical CLI passthrough to the kunglao CLI family (`scripts/kunglao.py` subcommands) |

2. **User request** (anything else): map by intent keywords to a subcommand —
   初始化/工作区/scaffold → `init`; 分析/继续分析/收敛/循环/deep analysis/analyze/run → `analysis`;
   验证/verify/F-NNN → `verify`; 健康/状态/monitor/health → `health`; unrecognized → `analysis`.

3. **Empty** `$ARGUMENTS` → `analysis` (the default convergence loop).

## Local defaults (this user's setup)

| Item | Value |
| --- | --- |
| Skill location | `~/.claude/skills/kunglao-agent/` (resolved via `$CLAUDE_SKILL_DIR` or `SKILL.md` parent) |
| Skill commit policy | kong-agent-only git (other skills NOT in git) |
| Workspace pattern | `D:/works/samples/<YYYY-MM-DD>/malware-analysis-workspace/` |
| Sample location | `D:/works/samples/<YYYY-MM-DD>/bins/<sha>` |
| VM (vmr-shell) | `192.168.20.128:9876` (host `~/Desktop`) |
| Frida (VM) | `192.168.20.128:1337` |
| Pre-installed agents | `kunglao-worker`, `ghidra-light`, `go-symbols`, `pefile-signature`, `floss-filter`, `verdict-scorer` (all in `~/.claude/agents/`) |
| Default CLAUDE.md | `D:/works/samples/<YYYY-MM-DD>/CLAUDE.md` (reads V1-V4 规范) |
| Memory dir | `~/.claude/projects/<project>/memory/` |
| Hook wire-up | NOT auto-installed — user has said "其它不用加到git里面"; wire up manually only if user requests |
| Smoke test command | `python scripts/test_v1_8_enforcement_gates.py` (24/24 must pass) |
| Run-all-gates command | See `references/failure-modes.md` "Run all enforcement gates" section (or any of the 3 domain files) |
| Hard prohibition #5 | x64dbg / Frida host-channel is FORBIDDEN (per `kong-agent-vm-only-host-ban` memory) |

**Default operator behavior** (from `references/guardrails.md` §6b.1 + in-session observations):

- §9 rule 5: NEVER 反问 user ("should I dispatch?" / "what should I do?") — just decide per `priority.py` / §8 / §9
- §6d.1: avoid violation phrases ("FINAL" / "TRULY" / "complete" / "convergence achieved") without explicit user sign-off
- §6-pre anti-forgetting: read `references/failure-modes-{lifecycle,monitoring,state}.md` for the 18 F-row failure modes + their enforcement scripts (3 domain files split for progressive disclosure; `failure-modes.md` is the index)

## Phase 0 SETUP (pre-loop, one-time)

**Phase 0 环境探测（先行，必做）** — 任何 scaffold 之前，先跑机械门禁：

0. **运行 env_check（机械门禁，#233）**：`python <skill>/scripts/env_check.py <ws>`。
   - 5 项检查：① AGENT_TEAMS flag（CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS，process/User/Machine 三作用域）② VM 可达性（TCP 9876 + 1337）③ Ghidra analyzeHeadless ④ hook 部署（settings.json 中 wire_up_settings 注册的 6 个 hook）⑤ venv + 样本 sha256。每项输出 `[PASS]` / `[FAIL]`，写 `runs/.env-check.json` 快照，`OVERALL=PASS` 时 exit 0。
   - **OVERALL=PASS 才进入分析**；任一 FAIL → 先修复对应项（下面 1-4 项即修复手册），重跑至 PASS；FAIL 未清零不得进入 Phase 0 主流程。
   - 门禁语义（同 `hooks/env_check_gate.py`，见 references/cold-start-contract.md #88 段）：① 是 HARD — flag 开启即禁止派发（子代理走 teammate 通道，2026-08-12 实测 400 [1210] 全灭；#88 禁止该 flag）；②③④ FAIL 可恢复 — 静态分析可先继续，T3 动态分析/反编译受限。

1. **探测 Python 虚拟环境**：检查当前会话是否处于 venv（`$env:VIRTUAL_ENV` / `sys.prefix != sys.base_prefix` / `.venv` 存在）。
   - 已激活 → 记录 venv 路径到 `analysis_state.txt`（`venv=<path>`）。
   - 未激活且 `.venv/` 不存在 → **先创建**：`python -m venv .venv`（在项目根），随后将依赖安装进该 venv。本 skill 的 Python 依赖（cryptography、pyyaml 等）一律装进 venv，不污染全局解释器。
   - 创建/激活后验证：`python -c "import cryptography, yaml"`，缺失依赖先补齐再进入下一步。
2. **探测工具链**：`scripts/`、`hooks/`、`templates/` 在位（`ls <skill>/scripts/`）；Python 版本与依赖库（cryptography / pyyaml / capstone / pefile 等）可用；`convergence_check.py` 能执行。
3. **建立认知（cognition）**：探测完毕后把环境结论写入 `analysis_state.txt`（venv 路径、Python 版本、工具链就绪状态、样本 sha256 已校验、fixtures 清单），形成本轮会话的"已认知基线"——后续每轮冷启动以此为准，不重复探测。
4. **样本挂载与哈希校验**：`bins/<sha>` 存在且 `sha256sum` 与 task_spec/report 一致，不匹配则 HARD STOP。

以上全部就绪后，进入 Phase 0 主流程：

**Phase 0 初始化 → `/init`**（工作区搭建一律通过 `/init` 完成，禁止手写 scaffold 命令）：运行 `/init` 初始化工作空间 → workspace scaffold（目录骨架 + state 文件 + facts/_INDEX.md）→ sample mount（bins/<sha> + fixtures 挂载）→ task_spec intake（allowed to ask user HERE, before iteration 1）→ cold-start artifact discovery → pre-flight → seed claims (primary_questions → PRIMARY claims; model_selection → K competing claims via `competitor_group`) → **activate hooks** → enter loop.

> 首次使用 `/init` 后若工作区已存在（重复初始化），以 `analysis_state.txt` + `claim-register.yaml` 为准做幂等续接，不重建、不覆盖已有 state。

**Hook + heartbeat activation — orchestrator-only, 30-min TTL:**

```bash
python scripts/hook_activation.py <ws> --wire-up    # register hooks in settings.json (idempotent)
python scripts/hook_activation.py <ws> --set-active dispatch_gate,worker_pulse
python scripts/hook_activation.py <ws> --reconcile  # rebuild active_workers from worktree status files
python scripts/hook_activation.py <ws> --heartbeat-on  # register .heartbeat.json (monitoring = file state)
python scripts/heartbeat_loop_prompt.py <ws>  # stdout = /loop prompt; pass to CronCreate */5 * * * * (or /loop 5m) BEFORE first dispatch
```

- MUSTs: `--wire-up` before the first dispatch (hooks silently drop from
  settings rewrites); `--reconcile` every tick (self-heals zombie
  `[active_workers]`); `--renew` every 30 min (activation expires);
  `--heartbeat-on` + `heartbeat_loop_prompt.py` before the first dispatch
  (worker_budget gate: `check_heartbeat_alive` REJECTS dispatches
  with missing/stale `.heartbeat.json`). Orchestrator-only activation. Full
  rationale + gate semantics → `references/cold-start-contract.md` §Phase 0.

## Orchestrator guardrails

The most-violated rules, in compact form. Full story in `references/guardrails.md`;
these bullets are what you must hold in working memory.

### 1. Tool-use boundary (the single most-violated rule)

**Never call an analysis tool directly.** Analysis tools produce evidence;
workers gather it, you verify it. If you violate this: stop analysis
immediately, write a fact if evidence was produced, route the remaining work
through `Agent` dispatches.

**Isolation-first (hard rule, #88)** — kunglao-agent NEVER uses agent teams:
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is never enabled, no teammates are
spawned, no team setup is performed (teammates are separate Claude instances
sharing a task list and mailbox, which breaks subagent isolation). Workers are
always isolated subagents: they report only to the orchestrator and never
message each other. SendMessage between the orchestrator and its own workers
is NOT a team feature and remains allowed — the heartbeat active-ping
(`[ping HH:MM] step? stuck? eta?`) and worker replies are the sanctioned
channel. A delivered worker is TaskStop'd on delivery confirmation (see "The
dispatch contract").

| Read-only research (call yourself) | Analysis (delegate via Agent) |
| --- | --- |
| `mcp__context7-mcp__*` — doc lookup before dispatching on unknown libs/APIs | `mcp__ghidra__*` — decompile / disasm / xrefs |
| `mcp__sequential-thinking` — 3+ step branching decisions | `mcp__x64dbg__*` — BP / trace / registers |
| `mcp__web_reader__webReader` — clean markdown from URLs | `mcp__frida__*` — attach / script load (host PID = forbidden, prohibition #5) |
| `vmr-shell` — VM control channel (routing / sample exec) | `mcp__volatility__*` — memory dump |
| Host `Bash`/`Read`/`Edit` on already-captured artifacts | `mcp__x64dbg-skills:tracealyzer` — loading it = calling the tool (§1a) |

#### 1a-1d + §6 — compact (full text in `references/guardrails.md`)

- **§1a** skill-mediated tool use = direct violation — copy the skill's workflow
  guidance into the dispatch description instead. **§1b** workers never
  self-verify; verifiers must be BLIND — verifier gets ONLY the raw
  evidence path + questions, derives its own finding, pass only on exact match,
  DIFF every divergence. **§1c** checkpoint state immediately; snapshot is HARD
  — state loss = HARD STOP. **§1d** project must be git; workers in
  isolated worktrees (state-loss recovery = git, not memory).
- **§1d.1** skill/repo changes: confirm → commit → modify → merge. **§1d.2**
  worktree source-mount caveat — gitignored source dirs are absent in worker
  worktrees. **§1d.3** superseded-path declaration — RE-dispatches
  ban the dead path explicitly.
- **§6** daemon, not one-shot — self-schedule `/loop`, converge-check after
  every notification. **§6.1** heartbeat loop (mandatory, from first dispatch)
  — `/loop 5m` or CronCreate; PING every worker. **§6.1b** heartbeat
  REGISTERED, not claimed — file state, not self-assertion.
  **§6.1a** smart ping protocol. **§6.2** notes via
  /malware-veri-notes every heartbeat (mandatory). **§6.3** convergence ≠
  completion — 5-item closeout checklist.

### 2. Coordinator vs Worker decision matrix

| Task | Who | Reason |
| --- | --- | --- |
| Read/write state files, dispatch workers, verify worker reports | Coordinator | Deliverable management, no novel evidence |
| Ghidra / x64dbg / frida / volatility calls | Worker | Static/dynamic evidence |
| `grep`/`strings`/`xxd` over `bins/<sha>` or `fixtures/` raw bytes | Worker (T1) | Novel static evidence |
| Read-only `cat`/`xxd` over already-captured artifacts (`evidence/*.json`, `decomp/*.c`, `runs/*.md`) | Coordinator | Read-only maintenance |
| Sample execution (vmrun / Start-Process on live VM) | Worker (T3) | Novel evidence |

### 3. Path-reachability check (BEFORE claiming cold-start is complete)

`Read`/`Bash` resolve paths against cwd; absolute `D:\...` fails outside cwd,
and `Bash cd` to deep paths can time out. Before declaring cold-start complete:

1. cwd = project root (not a deep sub-directory).
2. `Read` resolves every state file by cwd-relative path (`claim-register.yaml`,
   NOT absolute `D:\...`).
3. If `Bash cd` times out, read state files via `Read` with cwd-relative paths.

Any failure → cold-start NOT complete → log a `B1a` blocker, not "best guess".

### 4. Fallback: no formal workflow (worker_budget.py / claim_deps.yaml absent)

If the supporting infrastructure is missing, do NOT pretend to run a worker
loop: the contract is only the 3 jobs + hard prohibitions + §1a-§1d. With no
`task_spec.yaml`, ask the user ONCE for primary questions, record them — do
not invent questions. Dispatch `kunglao-worker` (not `general-purpose`); verify
via the independent verifier subagent (§1b) before promoting to PROVEN.

### 4.1 Worker self-drive

Worker 的"不会"不是终点：**LEARN → TRY → ESCALATE 三级自驱**（kunglao-worker.md
§6d 已写）。(1) LEARN: 不懂就 `WebSearch` / context7 / re-library 查证；
(2) TRY: 用查证结果换 ≥2 种方法重试；(3) ESCALATE: 都失败才报 blocker，
且 blocker 必须含查证记录（查了什么源/试了什么方法/卡在哪个点）。
WebSearch: worker 可自由使用。worker 报"不会"
而不带查证证据 = 失败（W-27）。同时 worker 对不确定证据必须标注
`confidence: low` + `unverified-part`，禁止静默下结论（防分析错误）。

### 6. Worker monitoring — daemon, not one-shot

WHY = convergence-loop behavior #4 (poll every worker, intervene, never idle on a notification). HOW = heartbeat tick mechanics in `references/operational-mechanics.md`. Common failure mode: pinging only the last-dispatched worker. Enumerate ALL workers every tick.

When the user reports a specific orchestrator failure pattern, the F-row lookup + enforcement-gate map is in `references/failure-modes-{lifecycle,monitoring,state}.md`.

## Active workers heartbeat

Mechanics are in `references/operational-mechanics.md` (tick loop, 3-strike rule,
worker-side status discipline). The principle: enumerate ALL workers each tick,
ping silent ones, TaskStop at 3 strikes, dispatch verifier on done/blocked.

## Hard prohibitions

1. **No mid-iteration questioning.** Decide + record assumption in `reasoning` + continue.
2. **No cascade abort.** Failure on claim C → C becomes deferred fact. Other claims unaffected. Never generalize from a single failure.
3. **User feedback = dual-layer skepticism.** Accept user feedback as a `source: user_feedback` claim (hypothesis). Epistemic: artifact judges truth. Procedural: YOU decide priority/timing. User source doesn't jump the queue. See DESIGN §10.
4. **Re-plan only on**: (a) verified finding, (b) refutation propagating via `claim_deps.yaml`, (c) task_spec external update. Never on mere failure.
5. **VM-ONLY dynamic tools — non-negotiable.** x64dbg and Frida are *VM-resident* tools. The host Claude session is structurally forbidden from issuing any MCP call that would launch / attach / inject into a sample binary on the host machine. **Forbidden MCP calls**: `mcp__x64dbg__start_session`, `mcp__x64dbg__connect_to_session`, any Frida server invocation that runs against a host process, any `vmrun` / `qemu-system` / `wine` launch that executes `bins/` or `extracted/` on the host. **Permitted MCP call (VM-path only)**: `mcp__x64dbg__connect_remote(host=VM_IP, req_rep_port=27066, pub_sub_port=27067)` after the VM-side `x64dbg.exe` is launched via `vmr-shell` against the VM-resident copy of the sample. `hooks/worker_budget.py` denies host-channel calls in its `pre_check` (search for `HOST_FORBIDDEN_TOOLS`). Rationale: `block_malware_exec` (PreToolUse on Bash) only catches shell commands; MCP tool calls bypass that hook, so the worker_budget hook is the canonical gate. See `references/dynamic-re-tool-priority.md` for the launch sequence. **In-scope on host**: read-only host operations on already-captured artifacts — `file`, `sha256sum`, `xxd`, `strings`, `grep`, `pefile` over `bins/<sha>`, reading `evidence/*.json`, rendering decompile output. **Forbidden on host**: any tool whose effect requires the sample to execute on the host. When in doubt: route through `vmr-shell`.

## Loop semantics

- **Open**: unresolved claim exists, no infra failure, no user stop, no orphan intent.
- **Converge (ship fact base)**: C0 (primary questions answered) + C1-C7 (structural).
- **Block (rare)**: B1a (infra unwritable) / B1b (workers all failed, writable) / **B1c (worker died without notification — see §6-pre F5)** / B2 (user stop).
- per-claim defer cap = 3 → forced DEFERRED (terminal). No MAX_ITER.

## Budget & enforcement

Pre+Post ToolUse hooks on Agent enforce: (a) ≤3 concurrent, (b) promotion_attempts < 3, (c) intended_tools ⊆ task_spec.constraints, (d) now < deadline_ts, (e) tier gate (§8.5). You don't self-count.

## §7. Self-cap-safe dispatch prose

`worker_budget.py::detect_self_cap()` rejects dispatch descriptions that look like
time caps ("30 min", "5s window", "stop after 1 hour") unless a negation phrase is
present ("no self-cap", "until done"). Full pattern table + safe-paraphrase table →
`references/operational-mechanics.md`. Rule of thumb: never write time-cap phrasing
into a dispatch description; if you must, append "(no self-cap)".

## Dispatch policy

**Claim-driven**: the claim-dependency graph (`claim_deps.yaml`) is the core — claims are nodes, the fact base is the state, dispatch/verify/propagate all key off claims, and refutation propagates along deps (not a full re-plan; see DESIGN S9 rule 4). **Tier-gated**: one structural search rule — broad cheap evidence (T1) on all claims before any expensive (T3) on one, enforced by `worker_budget.check_tier_gate()` (iterative deepening by evidence cost). "Greedy best-first" **IS implemented** — `scripts/priority.py` (heuristic score value×leverage×cheapness×novelty, priority queue by rank; rank-#1 deviation without `reasoning:` is REJECTED by `worker_budget.py` PreToolUse, v1.9.24). The orchestrator picks the next open claim within the dep+tier constraints, ranked by that script.

## External memory (persists across runs)

`task_spec.yaml` · `claim-register.yaml` · `claim_deps.yaml` · `analysis_state.txt` · `global_plan.txt`(+vN snapshots) · `progress.txt` (append-only) · `facts/_INDEX.md` · `blockers/`

Every round = cold start from these files. No reliance on prior-round context.

## System boundary

**In**: orchestrator + workers + modules + fact base + state files + verify loop + dual hook + Phase 0.
**Out**: hr-report (downstream), report generation, symbol recovery as an end, CTI re-query.

## VM-channel launch sequence (before any x64dbg MCP call)

**The only reliable first call is `mcp__x64dbg__connect_remote`** — `start_session`
and `connect_to_session` bind a stale host lockfile, not the VM x64dbg. Full
5-step sequence (confirm VM install → launch via vmr-shell → verify ZMQ ports →
connect_remote → drive) + anti-patterns → `references/operational-mechanics.md`.

## Downstream contract & modules

Skill maintainers: x64dbg/Frida MCP contract + modules list → **`references/downstream-contract.md`**.

## Decision rights — three-way matrix

Every decision falls to exactly one layer (no delegation without recorded reason).
**机械 8 / LLM 6 / 用户 5** — full 15-row matrix → **`references/decision-rights.md`**.
See `references/guardrails.md` for the full decision protocol.

## Maintenance — progressive disclosure

When the user asks to "enhance" or "optimize" the skill: **make the smallest
focused incremental edit** that addresses the observed issue. **Do NOT** do a
full rewrite. Each enhancement is a **single new section** or a **single
clarification** in an existing section. This:

- Preserves any in-flight context the user has built.
- Avoids blowing cost (cost is a hard signal — when the user is told
  "COST CRITICAL", they want *targeted* fixes, not rewrites).
- Keeps diffs reviewable.

Examples of focused single-section additions (each one alone is acceptable):

- "Go-binary exception handling" subsection to x64dbg-skills/tracealyzer.
- "Literal-hex set_breakpoint" subsection to x64dbg-skills/tracealyzer.
- "ZMQ REQ socket stick + x64dbg-process restart" subsection to x64dbg-skills/tracealyzer.
- "Bash-cd-in-deep-paths fallback" to vmr-shell or a generic note.

The orchestrator NEVER delivers a "rewrote the whole skill" change without
explicit user instruction to do so.
