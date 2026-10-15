# issue-694-harness-ablation — the rule layer vs the policy: pre-registered three-arm harness ablation

## Why

Owner question (2026-10-14): is the harness too heavy — is that why the RL
layer loses to bare Claude Code — and would cutting parts so the RL
controls more produce a clear improvement? Measured state (2026-10-14):
authority is misdistributed (the rule layer outranks the policy: a rank
top-1 REJECT is bypassable by an `agent-reasoning:` prefix; a
capability-switch lock can freeze family switches; `try_alternate_method`
is banned in three error classes; `CATEGORY_OPERATOR_ACTIONS` has no
production consumer), the RL's own signal was empty (pre-settlement
scores of 0.0 and a sampler that chose 3 of 158 recorded transitions),
and "RL helps" has never been tested in a controlled run. The cut
decision must be evidence-gated, not argued.

## What Changes

1. **A pre-registered three-arm ablation protocol** — written to
   `experiments/exp-s11-h-ablation/` (local-only; `experiments/` is
   gitignored) BEFORE the first run: arms H0 (bare Claude Code ≡ the
   registry's `cc-bare`) / H1 (slim harness, RL decisions off) / H2
   (H1 + the listed decision set handed to the RL); same task-family
   sequence per arm; >=3 repeats per task; difficulty above smoke;
   metrics fixed (success under the independent checker,
   time-to-correct, worker+orchestrator cost, false-proven); stop rule
   fixed.
2. **The five-face keep/cut criterion applied per item** — the harness
   keeps the five faces (reward integrity / termination and budget /
   evidence and execution classes / observation and telemetry /
   execution surface); everything that *decides for the policy* is
   demoted to advisory or removed, item by item (rank top-1 REJECT ->
   advisory rank, bypass prefix deleted; capability-switch lock ->
   decision with recorded reason; `try_alternate_method` bans rescoped;
   `CATEGORY_OPERATOR_ACTIONS` removed or wired; reference recall
   injection default-off). The table lives in `design.md`.
3. **The runner extension** (`scripts/eval_matrix_runner.py`) —
   `warm_up.store_mode: per-run | per-arm`: one accumulating store per
   arm across its unit sequence (within-sequence learning), still
   isolated across arms; accumulating arms launch as one sequential
   group in declared order. This unblocks the ablation's H1/H2 faces
   (which need cross-unit accumulation) and is scoped to this card.
4. **This openspec change** carries the protocol design (committed and
   reviewable) while the protocol file itself stays local-only per the
   card; real runs need owner budget approval (S11) — no run is
   authorized by this change.

## Out of scope (recorded)

- Executing the slimming list: it lands only if H1 > H0, as a versioned
  change with the ablation receipt attached.
- Handing authority to the RL: it lands only if H2 > H1, same form.
- The pre-ACT-BUDGET termination observation: the smoke-pilot receipts
  PRE-DATE the budget fix, so the termination gap is re-measured by
  this ablation — the old receipts are context, never evidence.
- Any real run: the three arms x 54 cells need the owner's budget
  envelope approval first (protocol section 3 gates it).
