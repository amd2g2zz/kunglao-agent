# issue-799-seal-learning-channel — HMAC-seal every reward-bearing input; learners refuse unsealed rows

## Why

The 5-expert design review's adversarial seat found the wall insufficient
for RL: only 2 of ~12 judgment faces are sealed; six stay worker-writable
at <=2 writes per exploit. Three surviving exploit families die wholesale
with one ~50-line defense reusing #736's `_sanction_sign` HMAC:

1. **Launch-stash Φ inflation** — `runs/dispatch-launch-<claim>.json` is
   unsealed JSON a worker can Edit mid-flight; one edit sets phi->0.0 and
   banks `r_incr = full Φ + 0.25·phi_delta` into posteriors, warm pools
   and termination mass (incremental_reward.py).
2. **Step-credit self-certification** — worker-typed `status: PROVEN` +
   `verify_status: passes` classify to credit 1.0 at the worker's OWN
   SubagentStop (step_credit.py:128-139); #718 witnesses but nothing
   claws back.
3. **oracle-status forgery** (#601 L7, named residual in
   `rlvr/state.py::_oracle_status_progress`) — a full-shape forged doc
   moves Φ's 0.5-weight oracle dim; and the fiat-propensity twin (#601
   L8) lets `propensity: 1.0` ride a stash into the SNIPS estimator.

## What Changes

1. **`rlvr/learning_seal.py` (new)** — the #736 construction verbatim
   (NUL-join HMAC-SHA256 over a versioned schema stamp + canonical
   record sha, `hmac.compare_digest` verify, key at a fixed path outside
   the workspace, no env override face): `SEAL_SCHEMA = "learning-seal/1"`,
   key `~/.claude/kunglao-learning.key`, min length 32. Armed = key
   provisioned; unarmed = the channel rides legacy byte-identically with
   ONE loud per-process notice.
2. **Writers seal** (all in owned files): `record_launch` seals the stash
   doc; `append_transition` seals the transition row; `q_cells
   .append_observation` seals every q-cell-obs row; `strategy_store
   .append_row` / `append_workspace_credit_row` seal every
   `posterior-store/1` row.
3. **Learners refuse unsealed/forged rows** (fail-closed on the learning
   path, telemetry never a crash): `read_transitions`, `q_cells.fold` +
   the pending-match/totals faces, `strategy_store.load_rows` +
   `PosteriorStrategyStore` observation reads, `refutation_fold` (via the
   two upstream reads). Refusal leaves the underlying store files
   BYTE-UNCHANGED and emits one loud warn per refused row.
4. **Launch-stash settle wall** — `append_transition` refuses a stash
   whose seal is missing/invalid when armed; the stash is left intact
   (1-F3 posture) and no row banks.
5. **Step-credit ceiling** — when armed, a `credit_kind: "step"` row
   above the unverified floor (0.3) banks at the floor unless the caller
   carries a valid seal (the host's future face); worker-typed PROVEN
   alone can no longer settle 1.0.
6. **oracle-status read wall** — when armed, `incremental_reward
   .potential` trusts Φ's oracle dim only from a seal-valid
   `runs/oracle-status.json`; otherwise the dim is honest absence.
7. **Propensity-vs-receipt cross-check** — a transition row's propensity
   survives only when it matches the sealed sampler receipt (the
   source=dispatch q-cell row for the claim, recipe_propensity column);
   otherwise the column is dropped with a loud warn (SNIPS mixing
   defense, L8).

## Out of scope (named)

- The canonical oracle-status WRITER (oracle_runner) and the step-credit
  host callers (step_grain, settle_round_credit) are outside this card's
  file map — their seal-minting wiring is the named follow-up; until it
  lands, armed boxes see the oracle dim dropped and step credits capped
  at the floor, both loudly telemetered (fail-closed direction).
- `rlvr/termination.py` (a listed learner) is outside the file map; its
  refusal face inherits via the sealed inputs it reads.
- `settlement_scorer.py` (#687, already sealed) untouched, per card.

## Invariants cited (devkit/invariants/registry.json)

- **INV-003 loop-posterior-moves** — the seal must not kill the reward
  channel: unarmed = legacy; armed = sealed writes keep posteriors
  moving (positive-control pin).
- **INV-001 loop-sampler-exit** — the propensity receipt cross-check
  strengthens the logged-propensity face.
- **INV-005 settle-credit-flows** — settlement credit rows seal at write;
  forged rows refuse without breaking the flow.

## Integration contract

- Seal block shape: `{"schema": "learning-seal/1", "record_sha256",
  "minted_ts", "hmac"}` appended as the `"seal"` key; canonical sha =
  sha256 over `json.dumps(row-without-seal, sort_keys=True,
  ensure_ascii=False, separators=(",", ":"))`.
- HMAC payload: `"\0".join([SEAL_SCHEMA, record_sha256, str(minted_ts)])`
  — the #736 NUL-join shape, keyed by the learning key.
- Unarmed (no key file): sign = identity, verify = legacy pass, ONE
  notice. Armed: any row/stash lacking a valid seal is refused by every
  learner in this card's map. No backcompat window (owner ruling
  2026-09-01).
