# Loop Engineering — kunglao main-loop research (2026-08-10, consolidated + refined)

> Two research rounds (LangChain/DSD + the cobusgreyling repo) + 4-subagent
> multi-perspective refinement + code-level root-cause verification.
> The VoI-scoring research landed in `archive/design-spec.md` §3.2; this file
> is the final **loop-layer** research.

## 1. Scope and method

**Problem**: does the kunglao-agent main loop (convergence loop) need
improvement? What exactly?
**Method**: framework mapping (LangChain 4-loop / DSD 10 patterns /
cobusgreyling 5-block) → kunglao comparison → 4-subagent multi-perspective
refinement (framework expert / reliability ×2 / YAGNI) → code-level root-cause
verification.
**Output**: 1 must-do (heartbeat cycle-lock, a correctness bug) + 1 evaluation
(triage quality) + a cut/defer list.

## 2. The loop-engineering thesis

The 2026 paradigm: shift from "prompt a single agent" to "design the control
system an orchestrated agent runs over time". Anthropic's Boris Cherny (Claude
Code lead) defines his own job as "writing the outer execution loop". The core
equation:

**kunglao is already this paradigm**: v1.9 turned notification-driven
(passively waiting to be poked) into convergence-driven (every tick
mechanically checks open claims + self-dispatches). The "idle waiting" chronic
fault was fixed = the root cause identified by the cross-8-session /
6-workspace study is cured.

## 3. Three-framework consolidation

### 3.1 The LangChain 4-layer loop stack

| Loop | Role | Effect |
|---|---|---|
| L1 agent | model calls tools until the task completes | automated work |
| L2 verification | a grader checks against a rubric, retries with feedback on failure | quality assurance |
| L3 event-driven | events (cron/webhook) trigger agent runs | scaling automation |
| L4 hill-climbing | production traces → analysis agent → improved harness config | self-improving harness |

Key claim: "focus should pivot to loops 3 and 4 where value compounds."
(Note: this claim implicitly assumes SaaS scale — see the §5.3 ruling.)

### 3.2 DSD's 10 patterns (three tiers)

- **Basics (1-4)**: ReAct / Reflection / Tool Use / Prompt Chaining
- **Practice (5-7)**: Ralph (external validator exit, Claude Code `/goal` is this) / Evaluator-Optimizer / Multi-Agent Supervisor
- **Production hardening (8-10)**: Circuit Breaker / Heartbeat / Bounded Execution + Context Engineering

DSD's own words: patterns 8-10 are "non-negotiable once a loop runs
autonomously in production."

### 3.3 The cobusgreyling repo (engineering-grade version)

Tools: `loop-audit` (readiness score) / `loop-sync` (STATE↔LOOP drift) /
`loop-context` (memory + circuit breaker).
Its 7 patterns (PR Babysitter / CI Sweeper / ...) are coding-workflow specific
and do not map directly to RE, but the structural principle of "asynchronous
observation + reacting to in-process results" transfers (structurally
isomorphic to kunglao worker monitoring).

### 3.4 How the three frameworks relate

LangChain = the conceptual stack (explains the 4 layers); DSD = the pattern
taxonomy (explains each layer's options + failure modes); cobusgreyling = the
engineering building blocks (explains the concrete blocks + tools). They
complement each other. The kunglao evaluation uses all three.

## 4. kunglao main-loop maturity comparison

### 4.1 All building blocks present (cobusgreyling frame)

| block | kunglao |
|---|---|
| Automations/Scheduling | heartbeat_loop_prompt + CronCreate /loop |
| Worktrees | §1d.1 per-worker isolated worktree |
| Skills | kunglao-agent + sub-skills + references/ |
| Plugins/MCP | ghidra / x64dbg / frida |
| Sub-agents | worker + kunglao-redteam BLIND (v1.9.22 forward-derive) |
| Memory/State | claim-register + digest + ledger + loop-state |

### 4.2 Loop-stack / pattern maturity

| Layer/pattern | kunglao | Status | Evidence |
|---|---|---|---|
| L1 agent | worker dispatch (maker) | ✅ | kunglao-worker |
| L2 verification | redteam BLIND + kunglao-verify L1 + blind_gate | ✅ strong | v1.9.22 forward-derive |
| L3 event-driven | heartbeat + CronCreate + worker_pulse | ✅ | v1.9.28 |
| **L4 hill-climbing** | no learning across runs | ❌ | no trace→harness feedback loop |
| pattern 5 Ralph | CONVERGED = claims zeroed + convergence_check mechanical execution | ✅ | framework-expert correction: a mechanical exit IS strong Ralph (the original ⚠️ was conservative); the "asking the right question set" concern belongs to L4, not Ralph |
| pattern 6 evaluator-optimizer | redteam as independent evaluator | ✅ | — |
| pattern 7 supervisor | orchestrator | ✅ | — |
| pattern 8 circuit breaker | backtrack/active_intervention/convergence_health (SPINNING) | ⚠️ | the 3 gates never validated against a failure scenario; SPINNING `_dedup_consecutive` mis-folds flatline (self-warning at code L98-101) |
| pattern 9 heartbeat | .heartbeat.json + reconcile | ⚠️ | **design-layer bug — see §6** |
| pattern 10 bounded + context | digest built but not wired to cold start | ⚠️ | not a bottleneck under Opus 1M (defer) |

**Conclusion**: the loop skeleton is isomorphic to the "ideal loop", all 5
blocks present. The improvement axis is **production readiness** (especially
pattern 9's live bug), not an architecture rewrite.

## 5. Multi-perspective refinement (4 subagents)

### 5.1 Strong consensus: heartbeat is the only real correctness bug

3 agents independently located it (reliability ×2 + YAGNI); code-level
evidence in §6. This session: STALE=5267min intercepted 2 subagent dispatches
= a live symptom.

### 5.2 Cut (90%+ overlap with existing mechanisms)

| Original proposal | Cut reason | Existing mechanism |
|---|---|---|
| loop-audit | 95% a rename | `acceptance_check.py` (oracle/CLI/VoI/digest/test-suite, 5 binary gates) |
| STATE↔contract drift | 90% overlap | `plan_drift_detector.py` (5 drift classes) + v1.9.18 `--reconcile` |
| hill-climbing L4 | SaaS-scale argument, negative ROI for a single user | none (failure-registry data volume cannot feed L4) |

### 5.3 Conflict rulings

- **L4 priority**: the framework expert ranked it #2 (LangChain "value compounds") vs YAGNI cut it ("SaaS fantasy"). **Ruling: YAGNI is right** — the LangChain claim presupposes many users with high-frequency runs; kunglao is a single user occasionally running samples. L4 deferred.
- **digest wired to cold start**: YAGNI noted 76K→38K under a 1M Opus context is 3.8% vs 7.6%, not a bottleneck. **defer** (worth it only when Haiku hits the wall).
- **pattern 5 Ralph**: framework-expert correction adopted ✅ (§4.2 already reflects it).

### 5.4 The blind spot the framework expert added: triage quality (see §7)

`convergence_check` + `priority_ratio` are the highest-leverage L3 decision
point ("which claim to dispatch now"), yet the whole study was silent about
their **ranking quality** — it only assessed "does the mechanism exist", not
"does it rank correctly". An independent evaluation gap.

## 6. Heartbeat bug root-cause analysis (refined to code level)

### 6.1 Symptoms (live evidence)

This session, 2026-08-10: dispatching a subagent got `worker_budget.py` REJECT
twice — `heartbeat STALE (5267 min > 35) — cron not ticking`. `runs/.heartbeat.json`
measured `last_tick_ts == started_ts == 01:49:56Z` (the cron tick never fired
after registration) and `activity_ts` was missing (the hook never ran). Not a
new failure — the same root cause behind the recurring "heartbeat stopped" of
v1.9.12/13/18/25/26/28/36.

### 6.2 Root causes (code level, 5 of them)

**RC1 inconsistent semantic split (design layer, the deepest)** —
`hooks/heartbeat_touch.py`'s docstring states the E2.3 semantic split:
`tick_ts` (cron only, **gates** the 35-min check) vs `activity_ts` (any tool,
**observation only**). But `worker_budget.py::check_heartbeat_alive` L530
`data.get('last_tick_ts', '')` reads only `last_tick_ts`, **never
`activity_ts`**. The field the hook bumps is not the field the gate reads →
the bump is fully ineffective for the gate. v1.9.36's "decouple liveness from
cognition" actually decoupled the wrong field: it labeled the liveness signal
(`activity_ts`) observation-only while leaving the gate dependent on cognition
(the cron tick). **The fix did not fix the gate.**

**RC2 the setdefault illusion** — `heartbeat_touch.py`'s
`data.setdefault("last_tick_ts", data["activity_ts"])` is commented "legacy
readers", but `setdefault` is a **no-op** when the key exists; after
`--heartbeat-on` registration `last_tick_ts` always exists → this line never
changes `last_tick_ts`. The code "looks like" it synchronizes the two fields;
it never executes.

**RC3 bare write_text race** — `heartbeat_touch.py` uses
`hb.write_text(json.dumps(data))`, **not** `_atomic_write` (tmp→rename). Every
Bash/Read/Write/Edit/Agent by the orchestrator + N worker subagents fires this
hook → multiple processes concurrently read-modify-write the same
`.heartbeat.json` → classic race → some writer's update silently lost.

**RC4 no cycle-in-progress lock** — `heartbeat_tick.py` never checks "is the
previous tick still running". Two cron ticks overlap → both run
`_reconcile_workers` → both rewrite the `analysis_state.txt [active_workers]`
section → `worker_budget::pre_check` may read a stale value when checking ≤3
against `[active_workers]` → **the WORKER_CAP=3 invariant gets bypassed** (a
4th worker may be dispatched). `_atomic_write` only makes each single write
atomic; it does not serialize the read-compute-write sequence.

**RC5 cron is session-only (platform limitation)** — the `/loop` cron job does
not persist across sessions. A new session registers no cron → `last_tick_ts`
never updates → the gate goes STALE. v1.9.28 introduced the gate intending to
"force the orchestrator to register /loop", but the platform limitation turns
this into periodic self-harm.

### 6.3 Cascading failure mode

`last_tick_ts` STALE → the dispatch gate rejects everything → the ledger stops
updating → `convergence_health` reads a stale trajectory → false
SPINNING/STALLED → the orchestrator panic-dispatches or freezes entirely.
SPINNING's `_dedup_consecutive` (L98-101) mis-folds a genuine flatline → false
convergence → unbounded burn (the most dangerous: continuous and silent).

### 6.4 Historical placement

v1.9.12/13/18/25/26 all reported "heartbeat stopped"; each fix was different
(register cron / wire-up hook / reconcile workers) and never touched the root
cause. v1.9.28 added the dispatch gate (heartbeat must be alive); v1.9.36
added `heartbeat_touch` (bump activity_ts). **v1.9.36's fix came closest, but
never actually took effect because of RC1 (the semantic split)**. This
session's STALE=5267 is the empirical proof of that path.

### 6.5 Fix design (code level, implementation-ready)

| # | Fix | Change site | Nature |
|---|---|---|---|
| **F1** | the gate reads `activity_ts` (or `max(last_tick_ts, activity_ts)`) | `worker_budget.py::check_heartbeat_alive` L530 | **core** — actually kills the STALE false positive; liveness = tool activity, independent of cron cognition |
| F2 | `heartbeat_touch` replaces bare `write_text` with `_atomic_write` | `heartbeat_touch.py` | removes the RC3 race |
| F3 | `heartbeat_tick` gains a cycle-in-progress lock (`fcntl.flock` on `.heartbeat.lock` or a PID file) | `heartbeat_tick.py` | removes overlapping RC4 ticks |
| F4 (optional) | split the `/loop` registration check out of the dispatch gate into an advisory warning (no block) | `worker_budget.py` | unblocks the RC5 platform limitation |

**F1 is the core**: semantic alignment — the gate's question is "is the
orchestrator session alive", and tool activity (`activity_ts`) is a more
direct liveness signal, less prone to false negatives, than the cron tick (the
cron tick is itself driven by the orchestrator session). Splitting `/loop
registration` into an advisory (F4) preserves the original intent of
"reminding to register the cron" without using it to block dispatch.

### 6.6 TDD list (F1+F2)

- RED1: simulate a busy orchestrator (cron not ticking) but active tools → the current gate STALE-rejects (wrong); after F1 alive (right).
- RED2: 4 processes concurrently writing `.heartbeat.json` → no update lost (F2 atomic write).
- RED3: regression — with the cron ticking normally the gate is still alive (the happy path unbroken).

## 7. Triage-quality evaluation plan (the framework-expert blind spot, refined)

### 7.1 Why triage is the highest-leverage L3 point

Once `convergence_check` decides DISPATCH, `priority_ratio` (VoI
`[0.45L+0.30D+0.25N]/cost`, issue #2) ranks **which claim to dispatch**. A
wrong ranking = tokens burned on low-value claims while high-value claims
queue. The highest-leverage decision of every tick — yet the whole study only
assessed "the mechanism exists", never "does it rank correctly".

### 7.2 What to evaluate

- **Value-order conformance rate**: on historical samples, the conformance between `priority_ratio`'s ranking and "what was actually solved first" (plan §2.2 G2, target ≥70%). This concretizes the **deferred E4.1 item**.
- **C-401≠C-402-style discrimination**: are same-score degeneracies broken (issue #2 has a regression test but lacks real-sample validation).
- **explore→exploit switching**: is the threshold 5 of `explore_gate` (verified facts < 5 → spread by cheapness) reasonable.

### 7.3 Method

Take 3-5 historical samples (malware-analysis-workspace progress.txt + ledger
carry the claim resolution order), replay `priority_ratio`'s output, compute
the Spearman correlation or top-3 conformance against the real order. Report
honestly; no re-ordering or sample cherry-picking to hit a target (plan §2.3
constraint).

### 7.4 Output

`tools/measure_value_order.py` + `runs/triage-quality-<ws>.json`. This is not
a code change, it is **measurement** — giving G2 a real number instead of "it
feels better".

## 8. Secondary risks (recorded, not on the must-do list)

- **SPINNING `_dedup_consecutive` mis-folding flatline** (self-warning at `convergence_health.py` L98-101) → false convergence → unbounded burn. Most dangerous (continuous and silent). Mitigation: once §6.5 F1 fixes the heartbeat, stale-trajectory input shrinks, indirectly lowering this risk.
- **mtime as liveness signal is unreliable under the triple interference of Windows + git worktree + antivirus**: antivirus refreshes mtime → false activity (a stuck worker is never detected); git checkout resets mtime → false zombie (an active worker gets reconciled away, facts lost). `_reconcile_workers` / `_scan_active_workers` depend on mtime. Long-term fix: add a content-hash or an explicit worker heartbeat.
- **3 PENDING gates never validated against failure scenarios**: backtrack/active_intervention/troubleshooting are soft constraints (the orchestrator must "remember" to call them; they are not wired into settings hooks). Acceptable marginal risk for a single user's occasional runs → defer.

## 9. Final conclusions and improvement priorities

| # | Item | Nature | Decision | Implementation |
|---|---|---|---|---|
| **1** | heartbeat F1+F2 (gate reads activity_ts + atomic write) | correctness bug (live symptom) | **must-do** | §6.5, small focused PR |
| 2 | triage-quality measurement (E4.1 concretized) | evaluation blind spot | do | §7, measurement only, no code change |
| — | heartbeat F3 (cycle-lock) | prevents overlapping ticks | optional | RC4, if overlap persists after F1 |
| — | heartbeat F4 (/loop advisory) | unblocks platform limitation | optional | RC5 |
| — | digest wired to cold start | efficiency (not a bottleneck under Opus 1M) | defer | do it when Haiku hits the wall |
| — | failure-scenario validation for the 3 PENDING gates | soft constraint | defer | single-user risk acceptable |
| — | SPINNING flatline mis-fold / mtime liveness | secondary risk | record | F1 mitigates indirectly; long-term content-hash |
| cut | loop-audit / loop-sync drift / hill-climbing L4 | overlap / SaaS scale | not doing | §5.2 |

**Doing none of them does not break anything**: `acceptance_check` guards the
build, `convergence_health` guards against spin, `plan_drift_detector` guards
drift, 175 tests green. **But heartbeat F1 is a live symptom (2 dispatches
intercepted in this session's own measurement) and the only must-do the
refinement produced** — it is a correctness bug, not an enhancement.

## 10. Sources

- [The Art of Loop Engineering — LangChain 2026-06](https://www.langchain.com/blog/the-art-of-loop-engineering)
- [10 Loop Engineering Design Patterns — DataScienceDojo 2026](https://datasciencedojo.com/blog/loop-engineering-design-patterns/)
- [cobusgreyling/loop-engineering — GitHub](https://github.com/cobusgreyling/loop-engineering)
- [LEAF Architecture Pattern — ResearchGate](https://www.researchgate.net/publication/408733345)
- [Autonomous Agentic Event-Driven Systems — Confluent](https://www.confluent.io/blog/autonomous-agentic-event-driven-systems-architecture/)
- code evidence: `hooks/heartbeat_touch.py` / `hooks/worker_budget.py::check_heartbeat_alive` L505-559 / `scripts/heartbeat_tick.py` / `scripts/hook_activation.py`
