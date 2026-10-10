# tasks — issue-654-batch-repair

## 1. 1-F3 — launch-stash schema wall

- [x] `record_launch` stamps `schema: "dispatch-launch/1"`; module constant `LAUNCH_SCHEMA`
- [x] `append_transition` refuses foreign-schema or `status`-carrying stash docs (None + ONE warn, stash intact)
- [x] RED→GREEN: `tests/test_launch_schema_wall_654.py` (parked envelope refused+intact; legacy settles; stamped settles)

## 2. 1-F9 + 4-L6 — obstacle invalidation + read-time re-certification

- [x] `record` accepts optional `env_key`; row carries it when set
- [x] `retract(ws, obstacle_id, reason)` writes the retraction marker into the row file
- [x] `sweep_stale_obstacles(ws)` pairs `missing_env_entry` rows against `runs/env-state.json` (`per_capability.<env_key>.status == "pass"` → retract + ONE warn)
- [x] `read()`/`face()` exclude retracted rows; read-time marker re-check when the artifact exists (present-but-shapeless → excluded + ONE warn; gone → kept)
- [x] RED→GREEN: `tests/test_obstacle_retraction_654.py`

## 3. 4-L5 + 5-F4 — prediction scaffold refusal + authorship

- [x] `MANDATED_CHECKER_MARKERS = ("verdict",)`; scaffold-aimed discriminator refused at register
- [x] `register(..., actor)` requires non-empty actor; row stamps `registered_by`
- [x] `settle`/`settle_matching` refuse authorship-less pending rows (ONE warn)
- [x] `tests/test_prediction_ledger_567.py` updated for the actor argument
- [x] RED→GREEN: `tests/test_prediction_authorship_654.py`

## 4. 4-L8 — SNIPS declared-exclusion + propensity cross-check

- [x] declared envelopes (`declared: true`) skipped from the weighted join, counted `skipped_declared_fiat`
- [x] transition-row propensity vs audit-envelope propensity mismatch → skip + count + warn
- [x] RED→GREEN: `tests/test_policy_compare_ope_654.py`

## 5. Verification

- [x] Focused suites: the five touched modules' test files green
- [x] Full fast suite green (`-m "fast and not docs"`)
- [x] `ruff check` on touched files clean; comment-hygiene / silent-except lints clean
- [x] `release_receipt.py --check` rc=0; `openspec validate issue-654-batch-repair` exit 0
