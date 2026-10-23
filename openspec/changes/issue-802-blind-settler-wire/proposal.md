# issue-802-blind-settler-wire — production settlement routes through the blind face

## Why

#687 (PR #709) shipped the blind-settlement barrier family — the
whitelist builder, the settlement gate, the read barrier, the
kunglao-settler face — but left it ARMED-UNWIRED: `settlement_scorer`'s
own docstring admitted the unblinded `settle_step` "is what runs today".
An armed-unwired trust surface advertises isolation production does not
have (the exact #634/#683 pattern the 5-expert review named).

## What Changes

1. **NEW `scripts/rlvr/settlement_wire.py`** — the production writer +
   consumer:
   - `park_blind_input` builds + parks the blind input doc
     (`runs/settlement-input-<claim>.json`) through
     `settlement_scorer.settler_input` — producer narrative and the
     policy learning faces are excluded BY CONSTRUCTION; the artifact
     list comes from `step_window_artifacts` (evidence/ mtime window
     filtered through the SAME exclusion wall); deterministic bytes,
     idempotent re-park, and a CHANGED re-park after the settler ruled
     refuses (the ruling window is closed);
   - `settle_parked` settles over EXACTLY what was blinded: the trust
     wall (`check_blind_input`) first, the grader-identity match, then
     the sha256 re-check (drift refuses — settling over unseen bytes
     fabricates credit), then `settle_blind` (the
     `scalar.validate_verdict_doc` stack), then the #800/#809-aligned
     claim mint through `claims_store.apply` (pass → `settle_proven`
     whose verification must RESOLVE to a PASSED record — the store
     refuses, fail-closed; fail → `settle_refuted`; actor
     `settler:<identity>`), then the content-hash-deduped
     `settlement-wire/1` row (refusals are loud rows too);
   - `pending_settlements` is the kunglao-settler dispatch read face.
2. **The unblinded judgment becomes eval-only** — `step_grain.settle_step`
   gains `blind=`: blind mode keeps the hash-only mechanical
   bookkeeping (step-record/2 aggregate, transition close, waste) and
   skips the producer-surface judgment legs (#712 credit,
   crystallization, belief). `hooks/round_closure` defaults to blind
   mode and parks the blind input; `KUNGLAO_EVAL_SETTLE=1`
   (`settlement_wire.eval_settle_enabled`) is the explicit opt-back-in.
3. **Liveness** — the `blind-settlement-wired` fingerprint
   (`runs/settlement.jsonl`, `settlement-wire/1`, non-empty identity)
   registered in devkit/liveness_fingerprints.json + the stamp in
   consolidated_ledger NATIVE_SCHEMAS (a dead writer reads 0, visible).

## Constraints honored

- `claims_store` / `scalar` semantics untouched — the wire CALLS the
  store (the #809 wall does the enforcing) and the scalar stack.
- ranker (#792) / supply (#794) / key face (#797) untouched.
- Synthetic poisoned fixtures only — no production log enters the repo.

## Impact

- commits: feat: the blind settler is wired — production settlement
  routes through the blind face (issue 802)
- tests: tests/test_blind_settler_wire_802.py (16 pins: isolation RED,
  determinism, sha drift, identity mismatch, hand-built smuggling,
  #809 mint wall, eval gate, wire rows)
