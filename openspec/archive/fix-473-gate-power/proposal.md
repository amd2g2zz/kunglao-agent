# Gate-chain power-on — oracle Phase 0 registration + fingerprint blind-spot expansion (#473)

## Why

The 2026-08-18 field incident recorded a four-step closing-escape narration
that passed every termination gate with zero interception:

1. self-declared completion ("我能继续的事都已经做了" — semantically
   equivalent to "task complete" but not matched by any pattern),
2. a self-invented tier ("需要 1-2 小时纯人工 RE" — a human-handoff tier
   keyword family entirely absent from TIER_KEYWORDS),
3. cost as the stop reason ("Session 边界再次到这" / "1-2 小时" — a TIME
   cost, while COST_FIGURE_RE only matches currency $/￥),
4. re-writing escalation as user errands ("你能继续的路: Ghidra GUI 手动跟
   30 分钟, 把字节码 dump 给我" — a user-directed imperative that assigns
   the operator work the agent should have run; `tools/_INDEX.yaml`'s
   `ghidra-decompile-functions --addresses` reaches the same capability
   without any human GUI session).

Source-verified root cause — the whole closing gate chain has no current:

1. **No one registers the oracle.** `templates/state/task-oracle.yaml:2`
   claims "Registered at Phase 0 by the orchestrator", but grep over
   SKILL.md / convergence_check.py / kunglao.py / kunglao-init.py finds
   zero registration steps. The template exists; the flow does not.
2. **completion_gate therefore never blocks.**
   `hooks/completion_gate.py:123-134` — an activated workspace WITHOUT
   task-oracle.yaml blocks (exit 3, #200), but an *inactive* workspace (the
   common case — no activation, no oracle) passes through at every earlier
   branch. More importantly premature_termination_detect — the one detector
   that reads the declaration text — has its ONLY consumer in
   scripts/completion_gate.py's exit-1 reason folding, which requires an
   oracle + open_items + declaration_text. Upstream never fires → the
   detector never runs.
3. **Even when run, the fingerprint tables miss the whole handoff register.**
   `premature_termination_detect.py:63-128`:
   - F2 TIER_KEYWORDS carries deferred/note-tier words but NO
     human-handoff keywords (手动 / manual / GUI / dump 给我 / 人工),
   - F3 COST_FIGURE_RE matches only `$`/`￥` currency — a time cost
     ("1-2 小时", "30 分钟") never fires,
   - F4 COMPLETION_PHRASES requires literal done-phrases — "我能继续的事
     都已经做了" is semantically complete-but-open and matches nothing.

## What Changes

- **Oracle registration (the power line)**:
  - `kunglao-init.py` initialize() writes a non-empty `task-oracle.yaml`
    workspace skeleton right after deploy_env (task: pending-user-input
    backfill marker + empty open_items + registered_ts) — init has no user
    task text, so the skeleton satisfies the "non-empty oracle exists"
    invariant and Phase 0 backfills the verbatim task.
  - `skills/kunglao-agent/SKILL.md` Phase 1 gets the mechanical backfill
    step: before the first dispatch, write the user's task verbatim into
    task-oracle.yaml `task_text`.
  - `heartbeat_tick.py` gains an oracle-registered check (report field
    `oracle_registered: bool`; missing oracle → the tick's stdout carries
    the actionable line) — same idempotent step pattern as selfcheck.
- **Fingerprint expansion (the sensors)** in
  `premature_termination_detect.py`:
  - F2: HANDOFF_KEYWORDS (手动 / manual / 人工 / GUI / dump 给我 /
     hand off ...) join the tier family — a handoff assignment the user
    never authorized is the same self-invented-tiering failure.
  - F3: TIME_COST_RE (\d+ 小时 / \d+ 分钟 / \d+ min / \d+ hours ...) joins
    the currency figure — time cost as a stop reason is cost-semantic
    drift; fires under the same sentence-co-occurrence qualifier.
  - F4: COMPLETION_PHRASES gains the semantic-equivalent completion
    family (我能做的都做了 / 我能继续的事都已经做了 / nothing more I can
    do / everything I can do has been done).
- **Imperative rule (F5, new)**: a closing declaration containing a
  user-directed imperative pattern (你打开 / 你装上 / 你接着干 / 你来 /
  手动跟 / dump 给我) while open-items-remaining signals are present →
  BLOCK (fingerprint F5 "user-delegation escape").
- **Tool-rebuttal duty (evidence obligation, report-only)**: when a
  declaration asserts "needs human / cannot automate" (需人工 / 无法自动
  化 / 手动), the detect() report carries
  `require_evidence: ["tool_search_zero_hit"]` — the worker must attach
  tools/_INDEX.yaml + tool-search zero-hit proof for the capability before
  the assertion is legal. Mechanical existence check only (the toolfirst
  runtime completion itself is toolfirst-side, out of scope here).

## Non-goals

- No toolfirst runtime auto-completion (separate workstream).
- No changes to completion_gate verdict precedence — the shim/judge
  contract stays; only the detector tables and the oracle's existence
  upstream change.
- No LLM semantic classification — every new pattern stays regex/keyword
  with the same D4 precision guards (clean-completion zero-fire).

## Impact

- `scripts/premature_termination_detect.py` — pattern tables + F5 + report
  field (heuristic, no workspace reads).
- `scripts/kunglao-init.py` — one skeleton write in initialize()
  (#478-deploy_env untouched; deploy_env tests re-run green).
- `scripts/heartbeat_tick.py` — one report field + actionable line.
- `skills/kunglao-agent/SKILL.md` — Phase 1 backfill step (English-only
  body per test_skill_contract; SKILL.md stays <400 lines).
- `templates/state/task-oracle.yaml` — header comment updated to name init
  as the skeleton writer + orchestrator as the Phase-0 backfiller.
- tests: new `tests/test_gate_power_473.py`; no existing test contract
  changes (ISOLATION_CASES unaffected — new patterns live in new
  sentence-level checks with their own isolation guards).
