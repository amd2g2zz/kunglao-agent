# Agent Three-State Charter (v2 calibration: issue #497, origin #447)

> Single-source-of-truth: the agent's three-state choice (allowed / must-ask / must-stop) across four classes of typical events.
> Hard prohibition #1, ask_for_direction_gate, and init negotiation all declare themselves executors of this table.

## Why

Issue #447 evidence 1 shows **three texts answer "when to ask the user" without referencing each other, partially contradictorily**:

| Text | Wording |
|---|---|
| Global rule `kunglao-convergence-loop.md` hard prohibition #1 | "Don't ask the user mid-iteration — decide yourself, record reasoning, continue" (unconditional) |
| `ask_for_direction_gate.py` | Type A BAD / Type C OK / HARD_PAUSE at 3+ redirects (laddered) |
| init negotiation interface | No ask protocol at all; non-interactive stdin auto-declined (nothing) |

→ **The same situation produces unpredictable behavior across sessions, forcing the user to act as the rule system's correction signal by interrupting** (issue #447 evidence 2: 4 interruptions across the VM-repair chain).

## The three-state table (THE SINGLE SOURCE)

| Event class | Event type | State | Handling |
|---|---|---|---|
| **Normal progression** | Default case | **allowed** | Decide yourself + record reasoning + continue |
| **Normal progression** | Convergence check-in (C0-C7 all pass) | **allowed** | convergence check per section 8 |
| **Identity ambiguity** | Multiple VMs / multiple toolchains / multiple samples | **must-ask** | emit Type D signal + HARD_PAUSE (rc=2) |
| **Identity ambiguity** | Task-goal ambiguity (workflow ≠ evidence) | **must-ask** | emit Type D signal + HARD_PAUSE |
| **Authorization boundary** | New hard error inside bounded authorization (#451 style; v2 calibrated by #497) | **allowed** | **Ladder is mandatory**: first climb the method ladder (`failure_analysis_gate --record`, #495 three artifacts) / env ladder (self-recovery L1→L2→L3), then **re-evaluate after the ladder**; when the gate's TYPE_D blocker tripwire has no ladder-exhaustion mark, it degrades to rc=1 ladder guidance |
| **Authorization boundary** | Tool/resource exhaustion — ladder climbed out (ladder-exhaustion mark = failure_analysis record has no `candidates` and claim `promotion_attempts >= 3`, #495 fields) | **must-ask** | emit Type D signal |
| **Scope change** | Task-boundary expansion (beyond the original plan) | **must-ask** | emit Type D signal |
| **Death declaration** | "This path is unworkable / cannot continue / dead end" style declarative sentence (v2 #497) | **With evidence: allowed / without evidence: NEGATIVE (reject)** | With obstacle REFUTED (#495 obstacle-claim promotion) or capability-disproof (failure_analysis `outcome: REFUTED`) evidence → legitimate terminal state; without evidence → emit Type E + rc=1 forced ladder re-evaluation, **must not be treated as terminal**. #233 pins the scope semantics: a path-scoped negative is licensed only by a settled obstacle claim REFUTED or a capability disproof (this row's standard, unchanged); a task-scoped negative is licensed only by the DEFERRED standard (V signal + recovery ladder L1-L3 + non-empty attempt list + wake_condition, see infeasible_signal/infeasible_proposal). Any oracle item's `closed_by` must cite a terminal-state claim id from the register (#233 citation protocol). |
| **Plan grounding** | No tool action after a "next step:" declaration (v2 #497) | **NEGATIVE** (reject) | Type B equivalent: rc=1, execute that next step or declare the blocker (turn-window detection on the event stream) |
| **Irreversible action** | Deleting a VM / editing the vmx / git push --force | **must-stop** | Block + emit Type S + HARD_PAUSE |
| **Irreversible action** | Public release / publish | **must-stop** | Block + emit Type S |
| **Back-asking** | "should I" / "do you want" / waiting for the user to decide | **NEGATIVE** (reject) | Type A/B violation (ask_for_direction_gate) |

## Type alphabet

| Type | Meaning | Handling |
|---|---|---|
| Type A | Back-asking question | REJECT (rc=1) |
| Type B | Completion-then-ask-next-step | REJECT (rc=1) |
| Type C | Convergence check-in | ALLOWED |
| **Type D** | must-ask trigger signal (identity ambiguity / authorization boundary / scope change) | HARD_PAUSE (rc=2) |
| **Type E** | Death declaration (fatalistic declarative sentence, v2 #497) | Without evidence: REJECT (rc=1) forcing ladder re-evaluation; with obstacle REFUTED / capability-disproof evidence: legitimate terminal state |
| plan-stall | Plan grounding (no action after "next step:", v2 #497) | REJECT (rc=1), Type B equivalent |
| **Type S** | must-stop trigger signal (irreversible action) | HARD_PAUSE (rc=2) |

## Executors (who enforces this table)

| Text | Role |
|---|---|
| `scripts/ask_for_direction_gate.py` | Type A/B/C detection (RC=1 reject) + HARD_PAUSE (rc=2) when Type D/S fires — sees orchestrator text **after** it prints. v2 (#497): Type D blocker tripwire degrades to rc=1 ladder guidance without a ladder-exhaustion mark; adds the Type E death-declaration gate + plan-stall grounding gate (both declarative-sentence gates, rc=1) |
| `scripts/error_response.py` `_CHARTER_STATE` table | Error class → three-state **derived column**: value domain = this table's three states (allowed / must-ask / must-stop), symbol anchors `CHARTER_SOURCE`/`CHARTER_STATES` declared in-module; mutual reference locked by `tests/test_decision_surface_anchor.py` lockstep assertions (#446 F-class) |
| `hooks/dispatch_gate.py` | Type S intercepted on the **dispatch prompt itself** (rc=2 hard pause, before the worker runs) — the carrying executor for irreversible actions |
| `scripts/kunglao-init.py` negotiation interface | Type D fires at init — pending decisions + RC_PENDING_DECISIONS=8 |
| Global `kunglao-convergence-loop.md` hard prohibition #1 | **Rewritten as a reference to this table**, no direct wording |

> Why Type S needs two executors: `ask_for_direction_gate` only sees printed
> output (the orchestrator may not print); `dispatch_gate` sees the prompt
> itself at PreToolUse (intercepts before the worker runs) — the latter is
> the carrier, the former is defense in depth.

## Declaration over inference (detection doctrine)

Priority: **mechanical first, LLM backstops the mechanical layer's recall misses**.

```
Priority 1 — mechanical layer (cheap, deterministic, auditable — runs first, zero misses inside coverage)
├── Declaration fields: dispatch protocol "reversible": false → HARD_PAUSE (references/orchestration/dispatch-protocol.md)
├── Command grammar: vmrun delete / git push --force (finite grammar, enumerable) → HARD_PAUSE
├── Structured state: claim-register / decision_pending / .hook_state.json
└── regex tripwires: prose patterns (zh+en, non-exhaustive)
        ↓ mechanical recall miss (enumeration blind spot: wording matches no pattern)
Priority 2 — LLM semantic backstop (any language, covers wording enumeration cannot)
└── orchestrator reads this charter (docs are prompt), semantically recognizes irreversible/ambiguous
    → the recognition lands as a structured declaration ("reversible": false), back to mechanically checkable
```

Division of labor: the mechanical layer handles **deterministic interception** — hit means block, auditable, zero cost; the LLM handles
**recall** — enumeration is never complete, semantic understanding covers blind spots. Once the LLM's judgment forms, it must land as a
structured declaration: judge semantically, execute mechanically, closed loop.

User input (often Chinese) enters the system through the intake/decision_pending structured schema;
language is not a variable at the mechanical layer, and the LLM layer is naturally multilingual.

## Monotonic degradation principle

- **allowed** → cannot be force-upgraded to must-ask (unless the orchestrator actively declares the trigger type)
- **must-ask** → cannot be downgraded to allowed (you must ask)
- **must-stop** → cannot be bypassed (the user must explicitly unlock)
- **NEGATIVE** (Type A/B) → cannot bypass via "Type C convergence" (unless C0-C7 all pass actually holds)

v2 (#497) note: the authorization-boundary row's must-ask → allowed calibration is a **table-level change** (via the
openspec process, see change log), not a runtime downgrade; the blocker family's retained must-ask
escalation condition is a **structural mark** (ladder exhaustion, #495 fields), not an arbitrary runtime escalation. A death
declaration's "with evidence → legitimate terminal" is likewise decided by structured evidence (obstacle claim status /
failure_analysis outcome), not by orchestrator self-declaration.

## Invariants

- This table is the **only** authority for "when to ask the user"
- No code/rule may **directly** say "ask the user" / "don't ask the user" — must reference this table
- Table changes must pass the openspec process (version + change log)

## Change log

- **v2 (#497, openspec/changes/issue-497-decision-grammar-v2/)**: authorization boundary
  "new hard error inside bounded authorization" must-ask → **allowed + mandatory ladder** (only "tool/resource
  exhaustion — ladder climbed out" keeps must-ask; ladder-exhaustion mark = failure_analysis without
  candidates and attempts>=3); adds **death declaration** (Type E) and **plan-stall** rows — the v0.1.1 dual-track relapse behavior is a declarative sentence, invisible to question-level enforcement; the executor
  `ask_for_direction_gate.py` updated in sync.
- **v1 (#447, openspec/changes/issue-447-three-state-charter/)**: initial
  three-state table + type alphabet + detection doctrine.

## See

- `scripts/ask_for_direction_gate.py` — Type A/B/D/E detection + plan-stall
- `openspec/changes/issue-447-three-state-charter/` — full spec
- `openspec/changes/issue-497-decision-grammar-v2/` — v2 calibration spec
