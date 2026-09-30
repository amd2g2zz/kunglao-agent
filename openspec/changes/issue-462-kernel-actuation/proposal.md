# Proposal — issue-462-kernel-actuation

## Why

The RL kernel (#429) was fully built — DTS posteriors (#428), Q cells
with shrinkage, the compose library (#431), the credit ladder (#433),
hook sensor topology, KPI faces — but runtime-inert. The 2026-09-30
section audit of #429 verified six missing wirings on dev@eea5b73a:
compose had no runtime host; the producer/consumer strategy seam was
shape-mismatched (the loop prompt rendered ZERO strategy content); the
compose store seam imported a nonexistent class and silently degraded
to a no-learned-content fallback; the DTS envelope sampler had zero
runtime consumers; no runtime face ever called `q_cells.observe()` (the
fold saw only credit=None dispatch rows — cells could NEVER learn); and
the T2 closure fired only from the eval loop. Without these six
wirings the kernel is decoration and every downstream optimization
(#459/#460/#461) tunes a loop that cannot learn.

## What changes

Six wirings, one reviewed commit per 1-2 (dependency order):

- **W3 store seam** — NEW `rlvr.strategy_store.PosteriorStrategyStore`
  implementing compose's StrategyStore protocol over the landed faces:
  method_lead = DTS call site 2 through the compose single-point
  (sample over the workspace's measured PROPOSAL channel — dispatch
  rows + settled method_family signals, settlement rows excluded;
  seed = f(store state, round), never wall clock), decayed_weight =
  the γ ladder over the settled stream, cell_count = q-cell rows at
  this signature. The silent IdentityStore degrade is CLOSED
  (fail-closed); an AST tripwire breaks if the import goes stale again.
- **W5 settlement feed** — `settle_round_credit` banks each dispatch's
  settled #433 ladder value into the matching Q cell on the FIRST
  SUCCESSFUL settlement (guard tests settlement presence in the fold,
  not row existence; replays and the late-cite amendment refine the
  ledger only). New match-and-bank face `q_cells.observe_settlement`;
  unmatched dispatch = the honest gap; r_r rail-clamped at the append
  boundary.
- **W4 envelope sampler** — the e2e dispatch act samples the envelope's
  method_family when the run declares none (candidates = measured
  proposal channel INTERSECTED with the #432 registry — retired tokens
  can never ride the prior into the fail-closed vocabulary gate; else
  uniform over the registered vocabulary). The sampled family rides the
  envelope AND the audit stream records `method_family_recorded` with
  the full sampler receipt. Declared runs keep the proposal face
  byte-identical. Fail-open pinned.
- **W1 compose host** — SubagentStop (Stop(worker) IS the round-closure
  event, #429 §6) composes + versions ONE round-strategy object per
  decision event (tick = the round axis via priority_ratio.round_index,
  machine-independent). Declared in the mechanisms registry (hooks
  channel — declaration-only per the #878 exclusion).
- **W6 production T2** — the same hook builds AND drains the T2
  unblocking-value queue (was eval-only). Fail-open double cages;
  writer-isolated atomic queue persist.
- **W2 consumer seam** — per the compose.py README's design: the tick
  files stay the versioned reconstructable ledger;
  `write_strategy` additionally emits `runs/round-strategy.json` as the
  DERIVED sections-shaped projection at every compose (the shape the
  live seam reads): deterministic, byte-idempotent, self-healing.
  Learned/attributable content only; a lead-less cold strategy renders
  NOTHING. Compose write faces migrate to atomic writer-isolated
  writes.

## Non-goals

- The v0.2 mainline V(s) sides-dim stays RESERVED (owner design pin
  2026-09-26, W_SIDES=0.0) — out of scope here.
- A live two-run auto-mode e2e demonstration of the §9 clause is the
  release-time exercise; this change demonstrates it mechanically
  through the real chain (settle → fold → compose → seam).
- No second decision source: compose stays the single strategy
  composer; the sampler's two consumers (the compose store adapter —
  production path; the e2e envelope act — eval path) are both kernel
  faces per #429 §5/§8.
