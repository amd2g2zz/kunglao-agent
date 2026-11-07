# issue-1004-ledger-retire — design

## Context

#721 shipped the 4-family consolidation with a compat window: writers of
the unswitched families kept their legacy rels, `read()` dual-read
(legacy rows first — they predate the live file — then consolidated),
and `migrate()` archived legacy bytes into `runs/archive/`. #1021
retired the adapter shims. This change retires the rest of the window:
every family switches whole, the dual-read dies, the archive migration
is replaced by the retire CLI that DELETES the legacy rels.

## Goals / Non-Goals

- Goals: one physical home per family; `read()` = consolidated rows
  only; `liveness()` = consolidated counts only; a one-time retire CLI
  that moves legacy rows in and deletes the legacy rels (never
  archives); the seal wall and the blind-act walls intact.
- Non-Goals: running the retire on any real workspace (R5, separate
  step); touching `rlvr.disposition.legacy_disposition` (live bridge);
  changing row schemas beyond the documented stamp additions
  (`cost-event/1`, `strategy-log/1` on rows that carried none).

## Decisions

### D1 — Single-writer guard is the consolidated lock

Every mover's per-module flock (rollout ledger lock, posterior-store
lock) retires with its IO. `cl.append`'s `.<stem>.lock` is the only
guard; no nested locks anywhere on the moved paths. Append-only
semantics, the stamp gate and the fail-open posture are `cl.append`'s,
unchanged.

### D2 — Writer stamps for the two unstamped historical streams

`cost_events.jsonl` rows (`{"ts","amount","source"}`) gain
`cost-event/1`; strategy-log dispatch rows gain `strategy-log/1`. The
consolidated append REFUSES stampless rows, so the writers stamp at
write; the retire CLI stamps historical unstamped rows with the rel's
single registered stamp at retirement (the #721 migration contract: a
schema stamp is the only structural addition, and only where the row
lacked one). Both stamps register in the family writer registry, so
`liveness()` sees them.

### D3 — Chronology: the retire CLI replays the dual-read order

The old dual-read returned: legacy rows in registry rel order, file
order within a rel, then the consolidated rows. The retire CLI appends
each rel's rows in exactly that order, so a workspace whose families
were read through the dual-read reads the same sequence from the single
file afterwards (pinned by a fixture test per family).

### D4 — The knowledge family unifies both posterior-store homes

The guarded-root store (`posterior-store.jsonl`) and the workspace-local
credit series (`runs/posterior-store.jsonl`) carry the same
`posterior-store/1` schema. Both retire into `knowledge-store.jsonl`
under the guarded root. Credit-series rows carry `workspace_id` (the
shared row builder), so `signal_guard.recent_credits` filters to the
calling workspace — the workspace-local series semantics survive the
merge. The DTS rows (`rlvr.posteriors`) key on (state-signature hash,
arm) — workspace-derived keys — and fold over the family file whole
(the knowledge family is WHAT IS KNOWN, cross-task by design). The
ws-local rel was not in the #721 LEGACY registry; R2c's module list
names the posterior store group whole, so the retire CLI carries the
ws-local rel explicitly.

### D5 — The seal wall moves with the IO

`strategy_store` seals at write (`sign_row` before append) and its
readers (`load_rows`, `cell_count`, `_proposal_prior`) keep
`trusted_rows`. The append target changes; the seal verification does
not. Round-trip pinned on an armed workspace (provisioned tmp key).

### D6 — Derived-row revocation is the one sanctioned rewrite

`crystallize.revoke_claim` rewrites the knowledge family file in ONE
pass (both predicates — negatives by `claim_ref`, broadcasts by
`claim` — filtered together; two passes over one file would race). The
revocation contract (derived rows die with their settlement; evidence
of record untouched) is unchanged.

### D7 — The legacy names have one sanctioned home

`LEGACY`, `SWITCHED`, `DEFAULT_MIGRATION`, `ARCHIVE_DIR_REL`,
`include_legacy`, `legacy_path` are deleted from the core. The retire
CLI carries the rel mapping as explicit constants (the one place the
retired names may appear). A repo-scan test pins the boundary:
production modules under `scripts/` + `hooks/` neither read nor write a
legacy rel; the core carries none of the retired names.

### D8 — Feature table home

`feature_prior.default_table_path` resolves to the knowledge family
file; `feature_mining` writes through `cl.append` (validated
`feature-table/1` rows). The historical ws-scoped
`runs/feature-table.jsonl` rel is retired ws-relative by the CLI (the
#721 `legacy_path` routed knowledge rels under the guarded root, but
the mined file always lived ws-relative — the CLI resolves it where the
writer actually wrote it).

## Risks / Trade-offs

- [Seal interplay] An armed workspace must not start refusing its own
  rows because the file name changed → the seal tests ride the new
  faces (round-trip test); no `sign_row`/`trusted_rows` call site
  changes.
- [Chronology] Post-retirement reads must equal pre-retirement dual
  reads → fixture-pinned per family (D3).
- [Flock] Nested locks would deadlock the loop → the movers' lock rels
  are deleted, not bypassed; the scan test pins no module references
  its retired lock rel.
- [Readers of the ws-local posterior store] `recent_credits` gains a
  workspace filter (D4) — the degeneracy series stays per-workspace.
- [Blind-act walls] The knowledge file is already deny-listed by name
  (`knowledge-store.jsonl`); the walls are unchanged by this move.

## Migration Plan

Repo code ships first (R2a–R3). The retire CLI (R4) is the operator
face; the real workspace migration is R5 (separate orchestrator step —
NOT run here).

## D9 — The verbatim `(no-schema)` row is a DELIVERED #721 contract

An earlier review pass proposed refusing multi-schema rels' stampless
rows because `append()` rejects stampless rows and `schema_prefix`
reads cannot see them. **Counter-evidence wins:** `tests/test_ledger_consolidation_721.py::test_retirement_never_guesses_a_second_schema_stamp`
pins `cli.main(...) == 0` and a byte-verbatim row. That is an
intentional, tested contract from the already-delivered #721.
Changing it here would be an undeclared behaviour change inside this
PR, so the proposal was reverted and the existing path is retained.
The review also found the `(no-schema)` liveness bucket had lost its
positive assertion after R3; `test_verbatim_unstamped_row_counts_as_no_schema_in_liveness`
now pins it. The private `_locked_append` call remains; cleaning it up
is a separate card, not this PR.

## D10 — Repo-scan basename blind spot (fixed here)

The no-legacy pin matched only full rel paths (`runs/q-cell-log.jsonl`),
while the blind-act deny walls spell the same name as a basename. The pin
now also matches a bare basename string constant, both deny walls are
explicitly allowlisted (a deny key REFUSES a path, it never opens one),
and a mutation probe proves a fresh basename literal would be caught.

## One PR, not one PR per slice

Issue #1004's Staging paragraph is authoritative: "The retirement
should be one PR (schema/reader/writer/migration/tests) plus one
workspace migration run." The 11:25 comment's "each its own reviewed
PR" describes the internal review order (R2a/R2b/R2c independent,
R3 after them, R4/R5 last), not separate PRs. AGENTS.md's
one-issue-one-PR-one-branch-one-worktree rule settles it.

## Open Questions

None — the owner ruling (no backcompat) settles the only real question.
