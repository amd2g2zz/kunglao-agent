# Design — fired-predicate resume prompt (#45)

## Design Decisions

### D1. State sources = four logged mechanical files, exactly the issue's list

`build_resume_prompt(ws: str | Path, *, max_chars=..., max_open_claims=...) -> str`
reads ONLY:

1. `.convergence_ledger.jsonl` — the LAST **SNAPSHOT** row (contract:
   `status_defs.LedgerLineType`; rows without `type` are SNAPSHOT, OUTCOME
   rows are events, never a snapshot — `ledger_line_type(row)` decides).
   Round number N = number of SNAPSHOT rows (each tick appends one snapshot
   per `convergence_check._append_ledger`). Fields consumed: `ts`,
   `decision`, `open_ids`, `active_workers`, `blockers`, `facts_total`.
2. `claim-register.yaml` — claims with status OPEN or in PARTIAL_STATUSES
   (`PARTIALLY-VERIFIED` / `PARTIAL` / `PARTIALLY_VERIFIED`, status_defs).
   IN_PROGRESS claims are EXCLUDED (they are covered by worker status files
   — a dispatched claim is not "open for dispatch").
3. `facts/_INDEX.md` — lines whose 2nd `|` field matches PARTIAL_STATUSES
   (same scan as `convergence_check._partial_facts`, incl.
   `errors="replace"` — the real index contains non-UTF8 bytes).
4. `runs/worker-status-*.md` — files whose LAST `status:` line is
   `in-progress` (same rule as `convergence_check._scan_active_workers` /
   `external_kicker.has_fresh_workers`). mtime is NOT a filter here: the
   recovery prompt must surface the dead session's stale in-progress
   workers so the fresh session can reconcile them.

NEVER read: `progress.txt`, `analysis_state.txt` — LLM self-descriptions,
not fired predicates (F4). Enforced by construction: the function has no
code path that touches either filename.

Why union for open claims: the register is the mechanical truth, but the
issue's RED test (a) demands the ledger last-row `open_ids` appear in the
prompt as a fired predicate. The prompt lists register-open ids first, then
any ledger `open_ids` not already present, deduped in order — both sources
are logged state, both visible, the register order preserved.

### D2. Next-step directive: dispatch vs CONVERGED

When open claims exist → "下一步: 按 priority.py dispatch top claim"
(`scripts/priority.py` is the sanctioned ranker; the prompt names it so the
fresh session runs it, not free judgment). When NO open claims → the
directive is exactly `CONVERGED, verify report` (the issue's required
phrase; never an empty prompt). The ledger `decision` is echoed verbatim so
the fresh session sees the last recorded decision even when it disagrees
with the register-derived list.

### D3. Length cap + priority-ordered truncation

Two independent bounds:

- `max_open_claims` (default 15): if the deduped open-claims list is
  longer, keep the top-N **by priority** and append the marker
  `(+N more truncated by priority)`.
- `max_chars` (default 4000): hard cap on the assembled prompt; if the
  assembly exceeds it, drop open-claim entries lowest-priority-first until
  under the cap (never below the first claim — if even one entry cannot
  fit, hard-cut the id list with the same marker).

Priority order = `priority.rank_claims(reg, deps, weights, ws=ws)` rows
(score desc) — the SAME ranker the loop dispatches by, so truncation keeps
exactly the claims the loop would dispatch next. Ids `rank_claims` does not
rank (blocked by open deps / promotion cap) are appended in register order.
Robustness: the import is lazy + try/except (ImportError) → fall back to
register order; `claim_deps.yaml` / `task_spec.yaml` missing → empty dicts
(`rank_claims` handles that; ws=None skips the failure-analysis scan). A
truncation error NEVER fails the prompt — recovery must not depend on
optional modules.

### D4. Robustness: missing/malformed inputs never crash the prompt

- Missing ledger / empty file / no valid SNAPSHOT row → round 0, decision
  `(no snapshot)`, open_ids `[]`; register/blockers/facts still fill in.
- Malformed JSON line → skipped (recovery bias: proceed with what parses).
- Missing claim-register.yaml → open claims = ledger `open_ids` only.
- Missing `blockers` key in the snapshot → fall back to scanning
  `blockers/*.md` excluding INVALIDATED (mirrors
  `convergence_check._active_blockers`) so blockers never silently vanish.
- Missing `facts_total` → count `facts/F*.md` from disk (same glob rule as
  `_count_facts`).
- Non-UTF8 bytes in _INDEX/worker files → `errors="replace"` everywhere.

### D5. Kick wiring is the minimal hunk

`tick()` step 4 changes from:

```python
from heartbeat_loop_prompt import build_prompt
prompt = build_prompt(str(workspace))
```

to:

```python
prompt = build_resume_prompt(workspace)
```

That is the ENTIRE wiring (the local import line dies with it — the
function is self-contained). `heartbeat_loop_prompt.py` untouched; the
new function + 2 constants + helpers live in a new `#45` section of
`scripts/external_kicker.py` (D4 comment updated to say "fired-predicate
resume prompt"). Concurrent #43 edits to `should_kick`/drift branch do not
overlap this hunk.

## Rejected Alternatives

- **R1: read `analysis_state.txt [active_workers]` for worker ids**: LLM
  self-description, exactly the F4 anti-pattern; the status files are the
  mechanical source (same single-source rule as #37).
- **R2: keep `heartbeat_loop_prompt.build_prompt` as the kick prompt and
  append state**: the issue requires the RECOVER prompt to BE the resume
  from fired predicates; appending state to the /loop contract keeps a
  narrative-first prompt and is not "never from narrative".
- **R3: inline priority ordering instead of `priority.rank_claims`**: DRY
  violation — the loop dispatches by `rank_claims`; two orderings would
  drift (the exact defect class the maker-checker rules forbid).
- **R4: prompt per open claim with full statement text**: unbounded length
  for large registers; the issue mandates a length cap + truncation.
  Statements stay out; ids + counts + a truncation marker go in.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/external_kicker.py` | MODIFIED | +`build_resume_prompt` (+helpers +2 constants); kick prompt line → `build_resume_prompt(ws)` (D5 minimal hunk) |
| `tests/test_resume_prompt.py` | NEW | ~12 tests, `tmp_path` synthetic workspaces only |
| `openspec/changes/fired-predicate-resume/*` | NEW | SDD artifacts |

## Out of scope

- #43 ledger-signature drift detection / #44 state_anchor (separate PRs,
  concurrent worktree).
- `heartbeat_loop_prompt.py` content (its CLI stays; the /loop contract is
  unchanged).
- convergence_check / priority / status_defs changes — this change only
  CONSUMES them.
