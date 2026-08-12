# OpenSpec Changes Archive Decision (#118)

## Decision: Option B — Accept as permanent history

The 56 openspec changes are retained as permanent development history.

## Rationale

1. Each change documents the design decisions behind a shipped feature/fix
2. They serve as useful context for future maintainers
3. `openspec archive` is not available in the current environment
4. Archiving 56 changes is busywork with no functional benefit
5. The changes are already in git history and don't affect runtime

## Inventory (56 changes)

All changes correspond to completed issues/PRs. Key batches:
- Phase 4-9 features (priority, digest, CLI, eval, acceptance)
- Fix series (#96-#99 hooks, maker-checker, schemas, VM-only)
- Convergence/heartbeat/completion gates
- B4 reposition (remove-cti-agents, verdict PQ-coverage, schema guard)
- S1 structure (references-index, license-decision, evals)
