## Context

A workspace may receive an intake prior and subsequently record pending or settled family declarations. The current history-first fallback deletes every candidate not yet declared. An observed history is a weight signal, not a current authorization or evidence source by itself. The Q-cell conditional draw weight is distinct from the probability that the orchestrator ultimately declares a family.

## Goals / Non-Goals

- Retain intake-supported candidates and incorporate only presently verifiable new candidates, after current registration, authorization and availability checks.
- Preserve a real empty candidate gap; do not make all registered families eligible solely because they are registered.
- Keep sampler-family, actual family, rationale, candidate provenance, conditional-weight source and unknown behavior probability distinct.
- No claim about real-world pivot success or end-to-end behavior propensity is made. Tool chains remain dispatch parameters.

## Decisions

Reconstruct support at each decision from positive intake entries and other current, verifiable evidence. Apply the closed vocabulary and workspace overlay receipt checks again so that withdrawal cannot be reversed by history. Exclude candidates prohibited by current task constraints. Availability is enforced against the actual dispatch tool parameters by the existing capability gate and its environment facts: a failed Frida channel does not make every possible dynamic-trace approach unavailable. Absent capability state is not proof of unavailability; no new method-to-tool dependency mapping is invented. When intake or discovery evidence exists, historical declarations only reweight its eligible candidates and cannot erase supported alternatives or revive revoked entries. When both sources are absent, retain the existing history → case → cross-task-store fallback, revalidating each token and current constraints. A present but corrupt or withdrawn intake/discovery source is not an absent source and cannot activate that compatibility fallback. The existing intake and discovery writers persist a boolean support-mode marker before publishing a source; marker failure prevents source publication. Existing sources are adopted when read. Removing a source therefore cannot reset a workspace to legacy mode. Malformed artifact paths invalidate their receipt without escaping support validation. Reconciliation failures in evidence mode explicitly return unsupported/error; only a workspace positively identified as legacy retains its empty-gap compatibility. Explicit expansion trigger artifact references must still be readable at decision time; a missing reference removes that receipt source while independent current sources remain usable. Legacy expansion receipts without artifact references keep their existing receipt contract. Preserve genuinely empty gaps and deterministic seed replay.

A declared deviation needs an explicit reason and current support. For legacy workspaces without intake or discovery material, missing dynamic authorization retains the existing unknown-state compatibility; explicit prohibitions always apply. New evidence-backed dynamic support requires explicit authorization. The dispatch observation retains the candidate set and provenance as well as the sampled and actual family. Candidate eligibility is based on validated positive support, never a rounded display weight. Sampler receipt weights and conditional ratios retain full floating-point precision. Conditional sampler information is labelled as such; declaration and override behavior probabilities remain null. The directly executed uniform scheduler retains its exact 1/K probability. The pre-existing learned MC estimator and downstream OPE consumers are explicitly deferred to #1034; this change neither repairs nor certifies that estimator. A legal `other(...)` follows the existing validation and quarantine route, not an automatic registration or prior.

## Integration contract

Caller: `PosteriorStrategyStore.method_sample` serves both `compose` and the dispatch reconciliation; `worker_budget_sinks._method_family_gate` validates and reconciles the actual declared method at the dispatch ALLOW boundary. Trigger: every sampled or declared dispatch, using the current workspace evidence, task constraints and receipt state before the pending observation is appended. Firing fingerprint: `rl-sampler-exit` (INV-001) records actual and sampled families and honest probability provenance; `rl-admission-consumed` (INV-002) remains the dispatch host admission record; `rl-posterior-moved` (INV-003) remains the non-empty keyed settlement channel. `q_cells.record_dispatch_observation` persists the reconciliation in the same experience row consumed by settlement and reporting. Dynamic hook and subprocess consumers require targeted end-to-end verification.

## Infrastructure

CI runs `uv sync --locked`, release manifest and hygiene checks, `uv run ruff check scripts/ hooks/ tools/`, and partitioned pytest from the repository root in `.github/workflows/release-check.yml`. The targeted changes live at repository root; no Dockerfile, compose file, `.husky/pre-push`, or `.claude/rules/harness.md` exists at this baseline. No new runtime dependency or deployment file is planned.

## Risks / Trade-offs

Candidate evidence can be revoked or become unavailable between decisions, so support is recomputed; Q-cell weights are not a substitute for an end-to-end behavior probability. Unreadable sources do not invent candidates. Independent review must inspect the exact staged diff.
