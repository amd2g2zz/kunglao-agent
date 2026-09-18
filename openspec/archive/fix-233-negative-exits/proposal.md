# fix-233-negative-exits — unify negative exits: closures must cite settled claims

## Why

Issue #233 (field incident 2026-09-11): a refusal citing "the target app only
trusts system certificates" closed an oracle item via free-text `closed_by`.
`scripts/completion_gate.py` treats ANY non-empty `closed_by` as resolved
(`:349-351`) — the one unbound negative exit on the completion surface. The
honest-negative machinery already exists (path-scoped: obstacle claim REFUTED /
capability-falsified, `find_death_evidence` @ ask_for_direction_gate.py:319-335;
task-scoped: the DEFERRED standard, infeasible_signal + infeasible_proposal
#815) but `closed_by` bypasses both.

## What Changes

1. **Citation protocol (uniform, mechanical)**: every closure (`closed_by`) on
   an oracle open_item must cite a claim id (mechanical claim-id grammar,
   e.g. `C-1`, `F-100`). No "negative-flavored" text classification — the same
   grammar check applies to positive and negative closures.
2. **Terminality**: the cited claim must be terminal
   (`scripts/status_defs.py::TERMINAL`). An OPEN (or otherwise non-terminal)
   citation is rejected. Unverifiable citations (no workspace_path, no
   claim-register.yaml, unknown claim id) are rejected — fail-closed, mirroring
   `find_death_evidence`.
3. **Obstacle-scope standard**: a closure citing an obstacle claim
   (`origin: failure-obstacle`) requires status REFUTED (the pinned
   path-scoped standard). A closure citing a DEFERRED claim (task-scoped
   negative) requires the DEFERRED standard markers written by
   `infeasible_proposal.file_proposal` (non-empty `wake_condition` +
   `infeasible_ladder`).
4. **Semantics pinned in prose**: one sentence each in the
   `find_death_evidence` docstring and the three-state charter:
   - path-scoped negative = obstacle claim REFUTED / capability-falsified
     (existing standard, unchanged);
   - task-scoped negative = the DEFERRED standard (V-signal + recovery ladder
     L1-L3 + non-empty attempt inventory + wake_condition).
5. **Gate verdict shape**: invalid citations surface as exit 1 with a NAMED
   reason per item (`INVALID_CLOSURE <item>: ...`), folded into the existing
   unresolved-items path (item-level defects outrank exit 4).

## Documented contract change (existing tests re-pinned)

`closed_by: "<free text>"` was previously sufficient to close an item. Existing
tests that close items with non-citation text (`commit 0001`, `verifier`) or
without a verifiable workspace register are re-pinned to cite terminal claims
from a `claim-register.yaml` in the oracle workspace. Affected:
tests/test_completion_gate.py, tests/test_intent_aware_completion.py,
tests/test_gate_layers_717.py, tests/test_heartbeat_off.py,
tests/test_summary_fake_826.py, tests/test_failopen_tiering_103.py,
tests/test_notes_fake_834.py, tests/test_notes_closure_762.py.

## Impact

- Affected: scripts/completion_gate.py (citation check + verdict path),
  scripts/ask_for_direction_gate.py (docstring pinning),
  references/contracts/agent-three-state-charter.md (charter pinning), the
  re-pinned tests, plus new RED-first tests for the citation protocol.
- Out of scope: fact-grammar tripwire patterns (explicitly rejected in design);
  verdict-side "no" binding (#21, v0.2).
