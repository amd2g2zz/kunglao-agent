# Proposal — issue-688-decision-view

## Why

The RL decision process is invisible to the operator: `rl_digest` emits
one rate-limited digest line per decision and the statusline carries a
health dot, but there is no VIEW that answers "what is the controller
doing and why" at a glance. A session audit showed 31% of main-thread
cache-read spent on ticks and 26% on stop-hook feedback with no way to
tell what the controller was doing. #320 specifies the workbench TUI
(pi-tui first) but not the RL-decision view contract; existing surfaces
are log lines, not a view.

Two of the six wanted faces are blocked upstream (entropy constant-zero;
cost diagnostic-only) — the contract must still expose them with honest
absent values rather than fabricate numbers, so the renderers can ship
before the blockers land.

## What Changes

1. **View-model contract file `scripts/decision_view.py`** — the "one
   model layer, two views" shape #320 names: `build_view(ws)` returns
   the six-face model with FIXED per-face key sets (`FACES`,
   `FACE_KEYS`):
   - `in_flight` — IN_PROGRESS claims + the round's leading method family
   - `why_this_one` — top claim, score, entropy, propensity, k, its
     feeds, rank recency (from the newest `rank_feeds` payload)
   - `just_settled` — newest settled rollout (anchor / kind / band /
     reward / ts)
   - `hypothesis_space` — arm counts by canonical status bucket
     (alive / parked / pruned / terminal / other) + the frontier entropy
     face (`entropy_face`, single source)
   - `budget` — token / tool_calls / verify_calls slots: honest nulls
     with `accounted: False` (cost is diagnostic-only upstream)
   - `next_candidates` — k + `{claim, score, tier}` per ranked candidate
   Fail-open by contract: a broken source degrades ITS face to the
   documented absent shape; `build_view` never raises.

2. **Four additive `rank_feeds` payload keys** (computed at the decision
   point in `priority_ratio._emit_rank_feeds`, pure functions of the
   ranked actions): `entropy` (Shannon bits of the normalized score
   distribution), `propensity` (the event arm's share of total score
   mass), `k` (ranked candidate count), `tiers` (`{claim: tier}`).
   Outside `input_fingerprint` — the fingerprint covers ranking INPUTS;
   these are outputs, so the fingerprint and frozen-sampling semantics
   stay byte-identical.

3. **`rank_face.latest_payload(ws)`** — single-source reader for the
   newest `rank_feeds` payload + its recency, so the view reads the same
   event the statusline/heartbeat read through `rank_face`.

4. Tests (`tests/test_decision_view_688.py`) + registrations:
   `scripts/README.md` catalog row, `tests/_tiers.py` fast-tier entry,
   deploy-manifest refresh.

## What Does NOT Change

- The ranking algorithm, scores, sorts, or `input_fingerprint`
  composition (additive payload keys only; payload remains replayable
  from the event tail with identical seed inputs).
- The emit contract: ONE `rank_feeds` per RUN, silent fail-open, never
  raises; `event_taxonomy` vocabulary (no new action words).
- OPE propensity semantics — the `propensity` key here is the rank-time
  score-share readout for the view; the DR-OPE propensity stays on
  dispatch receipts (`meta_arms.mc_propensity`), untouched.
- Renderers: no new UI stack — rendering rides the existing workbench
  track (#320) later; this change ships the model layer only.
- Budget values stay honest nulls until cost accounting lands
  upstream; no fabricated counters.

## Purpose

One model layer answers "what is it doing and why" mechanically: the
selection rationale (entropy / propensity / k / tiers) is persisted where
the decision happens, and `build_view` assembles all six faces from
single-source readers so a TUI/Web renderer consumes one dict instead of
re-deriving.

## Impact

- Affected: `scripts/priority_ratio.py` (payload += 4 keys via a pure
  helper), `scripts/rank_face.py` (new additive reader), new
  `scripts/decision_view.py`, new `tests/test_decision_view_688.py`,
  `scripts/README.md`, `tests/_tiers.py`, `deploy-manifest.yaml`.
- Blast radius (GitNexus, `_emit_rank_feeds` upstream): 3 direct callers
  (priority_ratio + 2 tests), depth-3 fan-in 570 symbols / 33 processes
  rated CRITICAL — mitigated by the additive-only, never-raising payload
  change inside the existing fail-open try (signature unchanged, all
  payload consumers read via `.get()`); full fast tier + affected
  families run before report.
- Consumers verified tolerant: `frozen_sampling_markers` (reads
  `input_fingerprint` only), `rank_face` / statusline / heartbeat (read
  `ranked_order`/`scores`), `replay_ruler` (`.get("dh_pq")` on historical
  rows), e2e runner (`ranked_order` only).
