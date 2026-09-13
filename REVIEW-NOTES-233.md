# REVIEW-NOTES-233 — fix: unify negative exits (closures must cite settled claims)

Branch `fix/233-negative-exits` (worktree `.worktrees/233-negative-exits`, base `dev`).
OpenSpec change: `openspec/changes/fix-233-negative-exits/` (`openspec validate` → exit 0).
Left STAGED, not committed (review-gate pre-commit hook requires an
orchestrator-minted gate token).

## What changed

0. **Repo hygiene gates re-pinned with the change** (mechanical, per their own
   documented procedures): `python scripts/re_pin_references.py` refreshed
   `references/_INDEX.yaml` for the charter edit; `python scripts/deploy_manifest.py
   --write` refreshed `deploy-manifest.yaml` sha256 entries for
   `scripts/completion_gate.py` / `scripts/ask_for_direction_gate.py` /
   `references/contracts/agent-three-state-charter.md`; the new test file
   carries the `# -*- coding: utf-8 -*-` declaration (non-ASCII gate).
1. **Citation protocol (mechanical, uniform)** — `scripts/completion_gate.py`:
   every non-empty `closed_by` (positive AND negative closures — one rule, no
   text classification) must contain a claim id matching `CLAIM_ID_RE`
   (`C-1`, `OC-2`, `F-100` vocabulary). The cited claim is looked up in
   `claim-register.yaml` under the oracle's `workspace_path`:
   - unknown id / no workspace / no register / unreadable register →
     rejected, fail-closed (`unverifiable citation`);
   - non-terminal status (not in `status_defs.TERMINAL`, with an identical
     literal fallback for the standalone CLI face) → rejected (`OPEN` etc.);
   - obstacle claim (`origin: failure-obstacle`) must be `REFUTED`
     (path-scoped standard);
   - `DEFERRED` claim must carry non-empty `wake_condition` +
     `infeasible_ladder` (task-scoped standard — the #815
     `infeasible_proposal.file_proposal` markers).
   Defective closures no longer resolve their item; they surface as exit 1
   with a NAMED reason: `INVALID_CLOSURE — N closure citation(s) rejected:
   <item> closed_by='…' — <cause>` (folded into the unresolved-items path;
   empty `closed_by` keeps its original plain-unresolved semantics).
2. **Prose pinning** — `scripts/ask_for_direction_gate.py::find_death_evidence`
   docstring + `references/contracts/agent-three-state-charter.md` 判死宣告 row.
3. **RED tests** — `tests/test_closure_citation_233.py` (13 tests: prose
   closure named-reason, OPEN/unknown citations, obstacle not-REFUTED,
   DEFERRED with/without standard, positive-cites-too, mixed naming,
   fail-closed unverifiable, empty-closed_by unchanged).
4. **Re-pinned existing tests (documented contract change)** — oracles that
   closed items with free text now cite terminal claims from a register under
   `workspace_path`:
   `tests/test_completion_gate.py` (`_all_closed_oracle` → C-1..C-6),
   `tests/test_intent_aware_completion.py` (C-1/C-2 + register; RED3 resolves
   via user-signed deferrals since it has no workspace_path),
   `tests/test_gate_layers_717.py` (L3 ledger + heartbeat-off fixture → F-100),
   `tests/test_heartbeat_off.py` (`_closed_oracle` → C-001),
   `tests/test_failopen_tiering_103.py`, `tests/test_summary_fake_826.py`,
   `tests/test_notes_fake_834.py`, `tests/test_notes_closure_762.py`
   (`closed_by: C-302`, register present).

## Pinned sentences

- **Path-scoped negative** (docstring + charter): a path-scoped negative is
  licensed only by a settled obstacle claim REFUTED (or a capability-falsified
  failure_analysis, `outcome: REFUTED`) — the existing `find_death_evidence`
  standard, unchanged.
- **Task-scoped negative** (docstring + charter): a task-scoped negative is
  licensed only by the DEFERRED standard — V-signal + recovery ladder L1-L3 +
  non-empty attempt inventory + wake_condition (`infeasible_signal` /
  `infeasible_proposal`).

## Verification

- `uv run python -m pytest -q` (full suite): `3 failed, 6671 passed, 12 skipped
  in 1729.10s` — the 3 failures are the pre-existing environment-dependent
  android-toolchain tests listed below (zero failures attributable to this
  change).
- `openspec validate fix-233-negative-exits` → `Change 'fix-233-negative-exits'
  is valid` (exit 0)
- `tests/test_comment_hygiene_lint.py` green: all newly added comments/
  docstrings avoid `#\d+` refs and narrative markers (the per-file ratchet
  counts are unchanged from the ledger; new-file debt is zero).
- 3 pre-existing, environment-dependent failures exist on clean HEAD too
  (verified by re-running them with all changes stashed):
  `tests/test_toolchain.py` (2, android toolchain absent),
  `tests/test_mcp_supply.py::test_toolchain_decompiler_fail_with_install_guidance`
  (and `tests/test_env_drift_475.py::TestEnvRepairL1::test_noop_without_substrate`,
  which fails only on some runs — host-state dependent).
  Unrelated to this change; not touched.

## Out of scope (not implemented, per issue)

- Fact-grammar tripwire patterns (explicitly rejected in design).
- Verdict-side "no" binding → #21 (v0.2).

## Deviations

- None mechanical. The fail-closed rule for unverifiable citations
  (no workspace_path / no register) is a documented design decision (design.md
  D2), mirroring `find_death_evidence`; it forced the RED3 re-pin to
  user-signed deferrals rather than `closed_by` citations.
- A previous agent's `tasks.md` checkboxes claimed prose-pinning and re-pins
  that were not actually present in the tree; they are now true (work completed
  in this session).
- Repo-wide mechanical gates (comment-hygiene ratchet, reference pins,
  deploy-manifest digests, coding declarations) required in-change refreshes;
  each was refreshed with its own sanctioned tool, no policy edits.
- Issue-ref shorthand (`#233`) was written as `issue 233` in new comments to
  satisfy the comment-hygiene ratchet; prose content is unaffected.
