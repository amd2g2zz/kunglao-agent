# Fired-Predicate Resume Prompt — RECOVER-layer kick prompt from mechanical state (#45)

## Why

The #39 external kicker's D4 kick currently pipes `heartbeat_loop_prompt.build_prompt(ws)`
VERBATIM into the fresh `claude -p` session. That prompt is a static `/loop`
contract — it tells the fresh session how to RUN the loop, but carries **no
state**: the fresh session must re-derive everything from scratch, or worse,
recover from the dying session's narrative files.

Research F4 ("an LLM saying done is not an event", ARC-AGI-3, 52 runs, ~17M
tokens): when the external commitment store is ablated, goal-abandonment goes
from 0.00 → 1.00. kunglao behavior #5 (open-claim count is truth) is the same
principle: **the loop's state IS the logged mechanical state** — the
convergence ledger snapshots, the claim register, the facts index, the worker
status files. A kick's fresh session MUST resume from those fired predicates,
NEVER from the dying session's narrative (`progress.txt` "我正在做...",
`analysis_state.txt` task fields are LLM self-descriptions, not events).

## What Changes

- **`scripts/external_kicker.py`** — NEW `build_resume_prompt(ws, ...)`:
  assembles the RECOVER prompt from logged mechanical state only:
  1. **Ledger last snapshot** `.convergence_ledger.jsonl` (last SNAPSHOT row
     per the LedgerLineType contract): round number N = count of SNAPSHOT
     rows; `decision` / `open_ids` / `active_workers` / `blockers` /
     `facts_total` from the last snapshot.
  2. **claim-register.yaml** OPEN / PARTIALLY-VERIFIED claims (status in
     PARTIAL_STATUSES or OPEN; IN_PROGRESS excluded — those are covered by
     worker status files).
  3. **facts/_INDEX.md** PARTIAL facts (same line-format scan as
     `convergence_check._partial_facts`).
  4. **runs/worker-status-\*.md** in-progress files (last `status:` line ==
     `in-progress`, same rule as `_scan_active_workers`) → the active-worker
     id list.
  - Prompt body: "你正在收敛循环第 N 轮; open claims=[...]; active
    workers=[...]; blockers=[...]; 下一步 = dispatch top claim per
    priority.py" — and when there are NO open claims: "CONVERGED, verify
    report" (never an empty prompt).
  - **NEVER reads**: `progress.txt`, `analysis_state.txt`.
  - **Length cap + truncation**: `max_chars` hard cap; when the open-claims
    list would overflow, entries are dropped LOWEST-priority-first (order
    from `priority.rank_claims`, the sanctioned ranker), with an explicit
    "+N more truncated by priority" marker so the fresh session knows the
    list is a top-N.
- **Kick wiring (D4 replacement)**: `tick()` builds the kick prompt with
  `build_resume_prompt(workspace)` instead of
  `heartbeat_loop_prompt.build_prompt(ws)`. `heartbeat_loop_prompt.py`
  itself is untouched (its CLI still emits the /loop contract).
- **`tests/test_resume_prompt.py`** — NEW, RED-first, synthetic `tmp_path`
  workspaces only.

## Capabilities

### Modified Capabilities

- `external-kicker`: the D4 kick prompt becomes a fired-predicate resume
  prompt (RECOVER layer) — assembled from the convergence ledger snapshot +
  claim register + facts index + worker status files, with a length cap and
  priority-ordered truncation. The fresh session resumes from mechanical
  state, never from the dying session's narrative (F4: "LLM saying done is
  not an event").

## Impact

- `scripts/external_kicker.py`: +1 public function `build_resume_prompt`
  (+3 small private helpers), +2 constants (`DEFAULT_MAX_PROMPT_CHARS`,
  `DEFAULT_MAX_OPEN_CLAIMS`); the kick prompt line in `tick()` changes from
  `heartbeat_loop_prompt.build_prompt(ws)` to `build_resume_prompt(ws)`
  (2-line wiring, incl. dropping the now-unused local import).
- `tests/test_resume_prompt.py`: new (~12 tests) — synthetic workspaces
  only; never touches the real workspace, never spawns.
- `scripts/heartbeat_loop_prompt.py`: NOT touched (its CLI stays).
- Behavior change: a kicked fresh session now knows round number, open
  claims, active workers, blockers, partial facts, and the next step —
  instead of starting a state-less loop contract.
- NOT in scope: #43 drift detection (signature/rotation), #44 state_anchor
  hook, progress-report changes, convergence_check changes, changing the
  /loop prompt itself.
