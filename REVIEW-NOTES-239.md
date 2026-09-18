# REVIEW-NOTES-239 — fix/239-plan-first-ownership

Issue: #239 "regression(#7): plan-first gate satisfied by an
orchestrator-ghostwritten plan (live field evidence) — dispatch-time
enforcement inverts plan ownership". Branch `fix/239-plan-first-ownership`
(based on `dev`). Change ID: `openspec/changes/fix-239-plan-first-ownership`.

## Mechanism summary — how first dispatch vs re-dispatch is distinguished

`check_worker_plan` (hooks/worker_budget_gates.py, wired unchanged as the
`('plan', ...)` entry of `pre_check` in hooks/worker_budget_sinks.py) now
decides first-vs-re dispatch from the claim's APPROVAL-POINT anchor log
`runs/.dispatch-anchor-<KEY>.jsonl` — the record `stamp_dispatch_anchor`
appends only after the whole gate battery passes (#754 lifecycle silence):

- log absent/empty -> FIRST dispatch of the claim -> PASS, no plan consulted
  at all (an orchestrator-ghostwritten plan neither satisfies nor blocks it —
  the ghostwrite incentive is removed at the root);
- log has rows -> RE-dispatch beyond the planning round -> requires the plan
  reference for THAT claim: the on-disk `runs/plan-C<NN>*.md` with content
  (#294 empty-shell check) and worker-session provenance (#57 gate 3
  `plan_author_violation`: cites an issued dispatch anchor, or carries a
  `dispatch-anchor:` line with an mtime after the first issued dispatch), OR
  the claim's plan path in the dispatch prompt (reserved for re-dispatch
  continuity).

Only the anchor log counts as "prior dispatch": the current dispatch's own
KUNGLAO_DISPATCH_CONTEXT nonce (prompt) and the #527 context-file nonce are
composed BEFORE approval and never classify a first dispatch as a re-dispatch
(new helper `_anchor_log_ts_list` extracted from `_dispatch_anchor_issued`,
which keeps its three-source merge for provenance arming). Provenance
machinery (#57 gate 3) is reused, not reinvented — on a re-dispatch the
author gate is armed by construction (a re-dispatch implies log rows).

## Files changed

- hooks/worker_budget_gates.py — check_worker_plan contract v2 (first-dispatch
  bypass keyed on the approval-point log; re-dispatch legs + new reject text);
  `_anchor_log_ts_list` extraction; block-comment + docstring updates.
- hooks/worker_budget_sinks.py — pre_check battery comment reworded;
  REJECT_FIXES['plan'] repair text reworded to the v2 contract.
- agents/kunglao-worker.md — golden rule #3: the dispatch carries intent,
  not a plan; the worker's FIRST sanctioned write is its own plan with a
  `dispatch-anchor:` provenance line; re-dispatch beyond the planning round
  requires the plan reference.
- skills/kunglao-agent/SKILL.md — Plan-to-execute paragraph + failure-mode
  table row re-pinned to the v2 contract (no tracker tokens: hygiene lints).
- tests/test_plan_first_ownership_239.py — NEW: 11 tests (first-dispatch pass
  incl. the e2e replay; re-dispatch reject incl. full-lifecycle e2e;
  ghostwritten-plan provenance reject; worker-authored plan passes;
  --plan-reference-is-continuity legs).
- tests/test_worker_budget.py — re-pinned: first dispatch passes without a
  plan; re-dispatch reject; empty-shell/BOM/unreadable/prompt-ref legs moved
  to the re-dispatch face; e2e split into first-dispatch-pass +
  redispatch-reject; the two #270 guidance scenarios seed a prior dispatch.
- tests/test_framework_rigidity_57.py — g3 re-pins (context-file/prompt-nonce
  arming re-scoped to the re-dispatch face; new first-dispatch-is-plan-free
  pin; legacy-posture + prompt-relaxation pins reworded).
- scripts/hygiene_baseline.yaml — comment-hygiene ledger tightened
  (test_worker_budget.py r1 53->45, test_framework_rigidity_57.py r1 14->12):
  my re-pinned docstrings avoid tracker refs, which shrank both files' debt.
- deploy-manifest.yaml — sha256 refreshed for the 3 edited deployed assets
  (worker_budget_gates.py, worker_budget_sinks.py, kunglao-worker.md);
  `deploy_manifest.py --verify` green (396 entries, order stable).
- openspec/changes/fix-239-plan-first-ownership/ — proposal + design + tasks
  + specs/plan-first-dispatch-gate/spec.md (MODIFIED requirement delta).

## Contract-change summary (documented in the proposal)

- OLD: every claim dispatch requires `runs/plan-C<NN>*.md` (or an in-prompt
  plan reference) at dispatch time — for a fresh claim only the orchestrator
  could satisfy the gate, hence ghostwriting (#239 field evidence).
- NEW: first dispatch plan-free (planning is the worker's first act of
  execution); re-dispatch beyond the planning round requires the plan
  reference; in-prompt `--plan` reference reserved for re-dispatch
  continuity; plan provenance = dispatch linkage (`dispatch-anchor:`),
  an orchestrator-authored plan does not satisfy the worker's contract
  (mirrors #237 D3 maker != checker).
- Umbrella #7 NOT referenced/closed; B1o drift gate (#237 branch) untouched;
  no change to plan_author_violation evidence paths A/B.

## Test evidence

- RED (on clean HEAD, before GREEN): `tests/test_plan_first_ownership_239.py`
  -> 6 failed / 5 passed — the failures were exactly the first-dispatch and
  provenance faces (e.g. "REJECT plan: no runs/plan-C001*.md ... write the
  plan FIRST").
- Targeted re-runs after GREEN: test_plan_first_ownership_239.py 11 passed;
  test_worker_budget.py + plan_first 91 passed; test_framework_rigidity_57.py
  40 passed; agents-hygiene/comment-lint/deploy-manifest/statusline/
  skill-contract files 198->134 passed after doc hygiene fixes.
- FULL suite (definitive run on this branch): see pytest summary line below.
- Env-baseline verification: `git stash push --include-untracked` -> clean
  HEAD -> `test_env_drift_475.py::TestEnvRepairL1::test_noop_without_substrate`
  and `test_toolchain.py::test_android_server_fail_without_listener` FAIL on
  clean HEAD too -> pre-existing environment failures, not attributable to
  this change -> `git stash pop` (restored cleanly). (The stated baseline's
  test_mcp_supply android-toolchain failure did not reproduce on this
  machine this run; the two failures above are this machine's baseline face.)

pytest summary line: `2 failed, 6672 passed, 12 skipped in 1009.22s` — the
only 2 failures (`test_env_drift_475.py::TestEnvRepairL1::test_noop_without_substrate`,
`test_toolchain.py::test_android_server_fail_without_listener`) were verified
above to fail on clean HEAD too (environment baseline); no NEW failures.
(First full run of this session, before the doc-hygiene fixes: 10 failed /
6664 passed — the other 8 were tracker-token, dated-narration, comment-ledger
and stale-deploy-digest faces caused by editing shipped assets, all resolved.)

## openspec validate

`openspec validate fix-239-plan-first-ownership` -> "Change
'fix-239-plan-first-ownership' is valid", exit 0.

## Deviations / notes for the reviewer

1. `gh issue view 239` failed with TLS timeouts for most of the session
   (transient backend outage); I implemented from the settled owner ruling in
   the task brief. A late retry recovered the issue body, which matches the
   implemented ruling point-for-point (including the three mechanical points
   and the RED acceptance criteria).
2. `npx openspec new change` does not exist in openspec 1.2.0 (globally
   installed); the change was scaffolded by hand following the repo's
   existing change layout (proposal/tasks/design + specs/ delta), and
   validates exit 0.
3. Hygiene-lint-driven collateral (not drive-by refactors): tracker-token and
   dated-narration lints forbid `#239`/dates in agents/*.md and SKILL.md, so
   the doc wording uses "issue 239" / "owner ruling" phrasing; the
   comment-hygiene ledger shrink and the deploy-manifest digest refresh are
   the sanctioned mechanical responses to editing shipped assets.
4. The "dispatch prompt should carry goal + acceptance criteria + constraints"
   sentence in the issue is prompt-content guidance, not part of the ruling's
   "Mechanically:" list — no new gate added for it (documented in the design).
5. Anti-ghostwrite ceiling: a plan carrying a forged `dispatch-anchor:` line
   with a fresh mtime (path B) remains indistinguishable from worker
   authorship by file evidence alone; the ruling's fix removes the
   dispatch-time inducement (first dispatch no longer needs a plan) and keeps
   the #57 evidence contract. A worker-session attestation write-gate was
   considered and rejected as out of the confined pathway (design.md).
6. No `git commit` (review-gate pre-commit needs an orchestrator token).
   Everything is staged (`git add -A`).
