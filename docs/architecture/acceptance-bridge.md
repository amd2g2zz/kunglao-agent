# Acceptance — the learning→decision bridge (issue #779, faces 2+2c+3)

> Scope: the settle-side credit bridge, the case-posterior prior
> source, and the breaker-on-bridge contract, on branch
> `feat/779-bridge`. Companion of `rl-signal-contract.md` (the signal
> definitions this document's credits carry). All acceptance commands
> run from the repo root; every fixture the tests build is SYNTHETIC
> (no eval corpus, no real workspace material).

## 1. What to accept — per deliverable

### 1.1 Credit fallback admission (the credit-into-pool bridge)

**Claim.** At settlement, a claim whose strategy pool starved — no
step records (`q_cells.step_credit_totals` count 0) AND no banked
terminal mass (`q_cells.banked_mass` row count 0) — gains one
claim-level admission into the pool through
`q_cells.observe_step_credit(..., method_family=...)`, with
credit = the claim's terminal credit, family resolved from the
method-family-log usage rows keyed by cid.

**Acceptance command.**

```bash
uv run pytest tests/test_bridge_779.py -q -n 4
```

Expected (machine-checkable): exit 0, `8 passed` — the pins that
matter:

| Pin | Asserts |
|---|---|
| `test_bridge_admits_claim_credit_when_pool_starved` | exactly one `credit_kind=step` row for the claim, `credit == terminal reward`, `method_family` == the usage-row family, fold mass `(reward, 1−reward)` |
| `test_bridge_skips_when_step_records_exist` | step-grade stays: zero new bridged rows when step records exist |
| `test_bridge_skips_when_terminal_mass_already_banked` | a matched terminal bank moves the pool EXACTLY once (no double-count) |
| `test_bridge_is_idempotent_across_replays` | replay passes admit nothing (first-settlement clock) |
| `test_bridge_without_usage_family_records_the_honest_gap` | no family → no pool address → no pool row (never a fabricated bucket); the store credit row still lands |
| `test_bridge_appends_credit_row_to_posterior_store` | one `posterior-store/1` credit row in `<ws>/runs/posterior-store.jsonl`, `credit == terminal reward`, `credit_kind=step` |
| `test_breaker_freezes_on_degenerate_bridge_traffic` | five identical bridge credits freeze the next pass (`signal_frozen=true`, `pool_bridged=0`, `signal_degenerate` blocker emitted) |
| `test_breaker_stays_cold_on_varied_bridge_traffic` | mixed credits (distinct ≥ 2) never freeze; the bridge keeps admitting |

### 1.2 Case-prior fourth source

**Claim.** In `method_sample`'s prior chain, `proposal_prior_labeled()`
gains the `case` source: `runs/posteriors.yaml` case Betas join
families via the update_map (green_up ∪ red_up hypothesis ids →
hypothesis claim_id → usage-row family) and fold SHRINK-capped success
mass, labeled `prior_source: "case"` — chain order history →
llm_prior → case → (cross-task store fallback).

**Acceptance command.**

```bash
uv run pytest tests/test_case_prior_779.py -q -n 4
```

Expected: exit 0, `10 passed` — key pins: `case` labels a one-family
prior at share 1.0 (`test_case_prior_is_the_fourth_source`); history
and llm_prior win over case (`test_history_and_llm_prior_win_over_case`);
a red-dominated case folds zero upward weight
(`test_case_prior_red_case_teaches_nothing_upward`); the SHRINK cap
bounds the fold (mass-100 and mass-34 cases fold as capped 8.0 masses —
`test_case_prior_shrink_cap_bounds_the_fold`); the registry wall and
retired/unmapped cases join nothing; `method_sample`'s receipt labels
`prior_source: "case"`
(`test_method_sample_labels_the_case_source`); `reconcile_declaration`
produces a non-empty `sampled_family` where it used to be the cold gap
(`test_reconcile_declaration_gains_the_case_draw`).

### 1.3 Breaker-on-bridge pin

**Claim.** Bridge-produced pool observations count in the degeneracy
series `rlvr.signal_guard.recent_credits` monitors: every bridged
admission appends a `posterior-store/1` credit row to
`<ws>/runs/posterior-store.jsonl`, so five identical bridge credits
freeze the posterior-moving legs (case observations AND the bridge)
and raise the `signal_degenerate` blocker; recovery stays manual.

**Acceptance command.**

```bash
uv run pytest tests/test_bridge_779.py -q -n 4 \
  -k "breaker or posterior_store"
```

Expected: exit 0, `3 passed`
(`test_bridge_appends_credit_row_to_posterior_store`,
`test_breaker_freezes_on_degenerate_bridge_traffic`,
`test_breaker_stays_cold_on_varied_bridge_traffic`). The freeze pin's
ledger evidence: `runs/logs/kunglao-*.jsonl` gains one row with
`action: signal_degenerate`, and the frozen pass reports
`signal_frozen=true` with `pool_bridged=0` and zero case observations.

## 2. Where it plugs in

Integration points (branch state, file:line — line numbers move; the
symbols are the anchors):

| Face | Integration point | Role |
|---|---|---|
| settle → bridge | `scripts/settle_round_credit.py:710` (`_bridge_pool_admission(ws, banked)` inside `run()`'s non-frozen branch) | the bridge fires per first-settlement claim, AFTER the round-credit bank and both case-observation legs, ONLY when the signal guard is not frozen (`run():686-696` sets `pool_bridged=0` on the frozen branch) |
| bridge → pool | `scripts/rlvr/q_cells.py:1462` (`observe_step_credit(..., method_family=)`) → `scripts/rlvr/q_cells.py:1433` (`_bridge_admit`) | matched dispatch → the normal `_bank_matched` face (byte-identical); unmatched + family → the family-keyed fallback admission at the current signature, `credit_kind=step`, `reason: pool-bridge` |
| family resolve | `scripts/method_families.py:355` (`usage_family_map`) | claim id → LAST declared family from `runs/method-family-log.jsonl` |
| bridge → series | `scripts/rlvr/strategy_store.py:270` (`append_workspace_credit_row`) | the workspace-local `posterior-store/1` credit row (one builder `_build_store_row` with the cross-task face) |
| decision ← learning | `scripts/rlvr/strategy_store.py:501` (`proposal_prior_labeled`) + `scripts/rlvr/strategy_store.py:539` (`_case_prior`) | the `case` prior source in `method_sample`'s chain |
| sampler consumers | `strategy_store.reconcile_declaration` / `gate_sample` / `method_lead` | unchanged call sites — they now draw from the case-fed chain (usage rows record `sampled_family`/`prior_source`) |

Before→after call chain (the starved-claim path):

```
BEFORE (the #779 defect):
  settle_round_credit.run
    └─ scalar.settle_round_credit → _bank_q_cell_credit
         └─ q_cells.observe_settlement → UNMATCHED (no pending dispatch
            row) → honest gap → the strategy pool starves
  method_sample prior chain: history → llm_prior → (empty) → store
    └─ case posteriors in runs/posteriors.yaml: NO decision consumer

AFTER:
  settle_round_credit.run
    ├─ scalar.settle_round_credit → _bank_q_cell_credit → (unchanged)
    ├─ signal guard (freeze_if_degenerate) — unchanged gate
    ├─ case-observation legs (fresh / late-arm / reconcile) — unchanged
    └─ _bridge_pool_admission(ws, banked)
         ├─ step_credit_totals == 0 AND banked_mass n == 0
         ├─ method_families.usage_family_map(ws)[cid] → family
         ├─ q_cells.observe_step_credit(cid, terminal_credit,
         │        method_family=family) → _bank_matched | _bridge_admit
         │        → credit_kind=step row → q-cell pool (the fold's mass)
         └─ strategy_store.append_workspace_credit_row(...)
                  → runs/posterior-store.jsonl credit row
                    → signal_guard.recent_credits series
                    → rl-posterior-moved evidence
  method_sample prior chain: history → llm_prior → CASE → store
    └─ _case_prior: runs/posteriors.yaml Betas
         └─ _case_update_maps (oracle/cases/*.yaml update_map ids)
              └─ _hypothesis_claims (hypotheses/*.md claim_id)
                   └─ usage_family_map (method-family-log.jsonl)
                        → SHRINK-capped success mass → share prior
                        → prior_source="case" → the sampler draws
```

## 3. How the connection works — the boundary's stores and schemas

| Store | Path | Producer (this change) | Consumer |
|---|---|---|---|
| q-cell observation log (consolidated experience family) | `<ws>/runs/experience.jsonl` (legacy `runs/q-cell-log.jsonl` rides the compat window) | `q_cells.append_observation` via `_bank_matched` / `_bridge_admit` — `q-cell-obs/1` rows, `credit_kind: "step"`, `reason: "pool-bridge"` on bridged rows | `q_cells.fold` → the sampler's local cells + the history prior's dispatch rows |
| method-family usage log | `<ws>/runs/method-family-log.jsonl` (`method-family-usage/1`) | the dispatch gate's ALLOW tail (pre-existing; the replay test writes through the same producer face) | `usage_family_map` — the settle-side family resolve AND the case-prior join's last hop |
| case posterior ledger | `<ws>/runs/posteriors.yaml` (`posteriors-schema/1`) | the settle pass's case-observation legs (pre-existing) | `_case_prior` — the decision side's NEW read |
| workspace credit series | `<ws>/runs/posterior-store.jsonl` (`posterior-store/1`, credit rows) | `append_workspace_credit_row` — credit, `credit_kind`, `method_family`, `provenance.dispatch_id`, holdout-filtered BEFORE append | `rlvr.signal_guard.recent_credits` (the degeneracy series), `devkit/liveness_gate.py` (`rl-posterior-moved`) |
| cross-task store | guarded root (`KUNGLAO_POSTERIOR_STORE` or `scripts/rlvr/patterns/posterior-store.jsonl`) | `append_store_row` (unchanged) | `warm_pools` / `_store_prior` (unchanged) |

Crossing rules the boundary enforces:

- **One observation, one movement.** The bridge fires only when
  `step_credit_totals == 0` AND `banked_mass n == 0` — a matched
  terminal bank and step records each own their mass; the calibration
  residual reconciles the bridged row exactly as any step row
  (`banked_mass` excludes step mass; `step_credit_totals` owns it), so
  a later amendment lands cumulative mass on the ladder value without
  double-counting.
- **Counts/credits never normalized away.** The credit row carries the
  settled ladder value verbatim (clamped [0,1] at the store boundary —
  the same rail as the cross-task face); case masses fold under the
  single `SHRINK_CAP` (8.0) — the γ/cap folding bounds them per the
  signal contract §1.1; nothing divides by a total except the final
  share normalization every prior source already applies.
- **Honest gaps.** No usage row → no family → no pool admission (the
  store credit row still lands — the settled credit is real). No
  settled reward readable → no bridge processing. All fail-open,
  counted in `run()`'s output (`pool_bridged`, `pool_bridge_error`).
- **Chokepoint discipline.** The `method_family` literal stays only in
  `hooks/worker_budget_sinks.py` at the hooks layer (pinned by
  `tests/test_method_families_432.py`); the bridge reads the family
  through `method_families.usage_family_map`, never through a second
  hook-side validation leg.

## 4. Assembly acceptance — after ALL Phase 1 modules land

Fingerprint gate on the synthetic campaign replay (the win-kdf
three-unit shape — `tests/test_bridge_campaign_779.py` builds it; the
unit ids, families, case docs, and credits are synthetic):

```bash
uv run pytest tests/test_bridge_campaign_779.py -q -n 4
# → 4 passed (the four metrics module)

uv run python devkit/liveness_gate.py --ledger <campaign-ws>
# → [PASS] rl-sampler-exit / rl-admission-consumed / rl-posterior-moved
#          / oracle-armed / settle-credit
#   liveness --ledger <ws>: LIVE
```

All rl-* fingerprints must be green, and the ledger evidence rows that
prove each:

| Fingerprint | Ledger evidence (row shapes) |
|---|---|
| `rl-posterior-moved` | `runs/posterior-store.jsonl` ≥ 1 `posterior-store/1` row — the bridged credit rows (credit == the settled ladder value, `credit_kind: "step"`, `provenance.dispatch_id: "C-win-*"`) |
| `rl-sampler-exit` | `runs/strategy-log.jsonl` ≥ 1 `event=dispatch, strategy=sampled` row — the sampled exit declared once the case-fed draw exists (the #496 writer lands it on the pass path) |
| `rl-admission-consumed` | `runs/plan-receipts.jsonl` ≥ 1 `plan-receipt/1` row with non-empty `admitted` (the #773 W3 writer) |
| `oracle-armed` | `oracle/cases/*.yaml` ≥ 1 file carrying `channel:` / `update_map` / `hypothesis_ref` |
| `settle-credit` | `runs/logs/kunglao-*.jsonl` ≥ 1 `task_terminal_settlement` row |

The four metrics the replay pins (measured on the synthetic campaign,
`test_campaign_replay_four_metrics`):

1. **Posterior shift > 0 after bridged observations** — every case
   Beta moved off the Beta(1,1) support (evidence mass > 0) and the
   q-cell family mass summed over the three declared families is > 0
   (the bridged `credit_kind=step` rows are the fold's mass).
2. **Usage rows have sampled_family non-empty** — written through
   `append_usage_row` with the `reconcile_declaration` view
   (`prior_source: "case"`).
3. **rl-posterior-moved green** — `evaluate_fingerprint` passes on the
   bridged store rows.
4. **rl-sampler-exit green** — `evaluate_fingerprint` passes on the
   sampled-exit strategy-log row.

Caveat, recorded honestly: the replay module drives the `oracle-armed`
/ `settle-credit` / `rl-admission-consumed` faces' writers only
indirectly (the campaign workspace is built directly, not through the
full executor); `liveness_gate --ledger` on such a workspace reports
the faces that produced evidence. Full-loop runs (the per-release
`--smoke` tier) remain the assembly-level proof for those faces.
