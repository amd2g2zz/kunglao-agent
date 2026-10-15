# Design — issue-688-decision-view

## Context

The ranker (`priority_ratio`) already emits ONE `rank_feeds` event per
RUN carrying `feeds` / `scores` / `ranked_order` / `input_fingerprint`;
`rank_face` owns reading it for the statusline/heartbeat; `entropy_face`
owns the frontier PQ entropy; `rl_digest` owns the per-decision digest
line. What does not exist is the model layer between those single-source
faces and a renderer — the six-face view the issue's table defines — nor
the decision-point selection statistics (entropy / propensity / k) the
"why this one" face needs, because the emit only persists raw scores.

Constraints that shape this design:

- **Emit contract**: `_emit_rank_feeds` is silent fail-open inside a
  try (a payload crash must never reach the ranking result); payload
  equality under same-seed replay is pinned by tests, so new keys must
  be deterministic functions of the run's own actions.
- **Fingerprint purity**: `input_fingerprint` covers ranking INPUTS
  (claims hash, evidence hash, rng_base, round); consumers recompute it
  from exactly those four fields. New keys are outputs and must stay
  OUTSIDE the fingerprint doc, or frozen-sampling detection and the
  replay tests break.
- **Additive-only everywhere**: payload consumers read with `.get()`;
  rank_face latest_rank returns a fixed dict; view contract keys are
  fixed per face with documented absent shapes.

## Goal / Non-Goal

- Goal: (a) persist decision-point `entropy`/`propensity`/`k`/`tiers`
  in the `rank_feeds` payload; (b) ship the six-face view-model
  contract (`build_view`) as the single model layer both future views
  (TUI #320, Web) consume, fail-open per face.
- Non-Goal: rendering (no TUI/Web code here), fixing the two upstream
  blockers (entropy zero-source, cost accounting) — the contract carries
  honest nulls until they land; recomputing posteriors or re-ranking
  (the view reads persisted events, never re-runs the ranker).

## Decisions

### D1. The four keys are pure functions of the ranked actions

`_view_stats(actions)` (module-level helper, pure):
- `k = len(actions)` — the ranked candidate count.
- `propensity` = top arm's share of total score mass:
  `scores[0] / sum(scores)` (actions are pre-sorted at the emit call
  site), rounded to 6dp — a bounded, deterministic "how dominant was
  the pick" readout. None when the sum is 0 or k == 0 (honest null, not
  fabricated 1/k). This is deliberately NOT the OPE propensity
  (`meta_arms.mc_propensity`, dispatch-receipt scope) — same word,
  different layer; design keeps the scopes disjoint: rank-time share
  for the view, MC selection probability for OPE.
- `entropy` = Shannon entropy in bits of the normalized score
  distribution over the k candidates, rounded to 6dp; 0.0 when k <= 1
  (a single candidate is fully determined), None when the distribution
  is degenerate (sum <= 0 with k > 1 — zero-mass scores cannot be
  normalized). Computed with `math.log2`; negative scores (possible
  only via a negative worth override) are clamped at 0 before
  normalizing so the distribution stays a simplex.
- `tiers` = `{claim_id: tier}` — per-candidate dispatch tier, same
  claim-keyed shape as `feeds`/`scores`, so a renderer zips
  ranked_order × scores × tiers without touching the register.

Rationale: everything derives from `actions`, which the replay tests
pin — same seed ⇒ same payload byte-for-byte, including the new keys.
No ws reads, no clock reads, no imports beyond `math`.

### D2. Keys live at payload top level, outside `input_fingerprint`

`payload = {feeds, scores, ranked_order, input_fingerprint, entropy,
propensity, k, tiers}`. The fingerprint doc stays exactly
{claims_hash, evidence_hash, rng_base, round} + its hash — consumers
(`frozen_sampling_markers`, the157 replay tests) recompute the hash
from those four fields only. Additive top-level keys are invisible to
`.get()`-based readers.

### D3. `rank_face.latest_payload` extends the owning reader

The view must not re-implement the bounded-tail scan (single-source:
rank_face owns reading `rank_feeds`). New public function
`latest_payload(ws, now)` → `{payload, ts, age_s, stale}` mirroring
`latest_rank`'s shape but returning the whole parsed payload ({} when
absent); `latest_rank` itself is untouched (its consumers and tests
pin its dict).

### D4. The view model is a contract file with fixed face key sets

`scripts/decision_view.py`:
- `SCHEMA = "decision-view/1"`, `FACES` tuple (the six names in the
  issue's table order), `FACE_KEYS: {face: tuple_of_required_keys}` —
  the machine-checkable contract tests pin.
- `build_view(ws, now=None)` → `{"schema", "faces": {face: dict}}`.
  Every face is built by a small face function; each source read is
  wrapped so a failure degrades THAT face to its documented absent
  shape (keys present, values null) and never raises — the
  fail-open-everywhere house contract, per face.
- Face sources (all single-source, all existing):
  | face | source |
  |---|---|
  | in_flight | `_scriptlib.read_register_claims` filtered to `IN_PROGRESS_STATUSES`; family from the strategy object's `dispatch.method_lead` (`rlvr.compose.read_strategy`, fail-open None) |
  | why_this_one | `rank_face.latest_payload` → top claim, score, the new entropy/propensity/k keys, its feeds, plus recency |
  | just_settled | `rlvr.ledger.settled` tail row (anchor/kind/band/reward/ts) |
  | hypothesis_space | register status counts (alive=ACTIVE, parked=SUSPENDED, pruned=RETRACTED, terminal=TERMINAL, other) + `entropy_face.face(ws)` for h_bits/h_pq/h_trend |
  | budget | honest blocked face: `{tokens: None, tool_calls: None, verify_calls: None, accounted: False}` — cost is diagnostic-only upstream |
  | next_candidates | newest payload's ranked_order × scores × tiers, sliced to `VIEW_TOP_K` |
- Why a contract file and not inline render code: #320's "one model
  layer, two views" — the TUI and Web renderers both consume
  `build_view` output; key-set drift is caught by tests against
  `FACE_KEYS`, not by convention.

### D5. VIEW_TOP_K = 5

`next_candidates` slices the payload to the top 5 — a glanceable
shortlist; `k` on the payload records the FULL candidate count so a
renderer wanting more re-slices from `ranked_order` without a re-rank.
Named constant, not magic number.

## Risks / Trade-offs

- [propensity word collides with OPE propensity] → documented in both
  docstrings: rank-time score share vs MC selection probability; the
  two never read each other's fields (policy_compare reads envelopes,
  not rank_feeds).
- [zero-mass or single-candidate runs yield null/0 entropy] → honest
  nulls beat fabricated values; tests pin both degenerate cases so the
  absence is contract, not accident.
- [emit fan-in is CRITICAL at depth 3] → additive-only change inside
  the existing fail-open try; signature unchanged; full fast tier +
  the 157/255/218/266/294 families run before report.
- [budget face ships nulls] → the blocker (cost not accounted) is the
  documented state; `accounted: False` makes the nullness explicit so
  a renderer shows "not accounted" instead of zeros.
- [old rank_feeds rows lack the new keys] → view readers use `.get()`
  with the same absent shapes; rows written before this change degrade
  honestly (entropy/propensity None, k defaults to len(ranked_order)).
