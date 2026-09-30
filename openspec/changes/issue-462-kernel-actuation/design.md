# Design — issue-462-kernel-actuation

## Context

The kernel's organs landed across #428/#429/#431/#433/#420 but no
production or eval face connected them: the loop could not learn
(settlement never reached the fold), could not decide differently
(no strategy object was ever composed at a decision event), and could
not show any of it (the loop prompt rendered zero strategy content).

## Goals / Non-Goals

Goals: the six wirings of the issue, each as the smallest honest
connection over delivered organs — no new organ, no second decision
source, the determinism wall untouched.

Non-goals: mainline-layer Q activation (waits for sample volume, #429
§8 Phase B), the V(s) sides-dim (RESERVED v0.2), per-cell γ routing.

## Actual / Concrete Design Decisions

### D1 — which face hosts compose (W1)

The SubagentStop hook (`hooks/round_closure.py`) is the production
host: #429 §6 rules Stop(worker) = the round-closure event, and §1
rules the decision clock event-driven on "worker returned". The tick
axis is `priority_ratio.round_index` (RAW snapshot-row count — the
#251-ruled machine-independent round, never a wall clock). The
mechanisms registry gains a declaration-only hooks-channel entry
(NOT scheduler-migrated — the #878 explicit exclusion). The kernel
faces fire per SubagentStop with a marker-resolved workspace, deduped
by content_hash (no worker discriminator exists at the Stop face).

### D2 — the seam shape (W2)

Compose emits BOTH faces: the tick files remain the versioned,
reconstructable ledger (content_hash dedup, resume continuity); every
compose additionally re-emits `runs/round-strategy.json` as a DERIVED
sections-shaped projection (`{schema, round, sections:[{title, body}]}`
— exactly what `strategy_sections.py` reads). One producer, two
shapes, no renderer adapters duplicated into consumers. The projection
carries learned/attributable content only (lead + budget context,
anti-hints, monitor focus, rendered card blocks with inline ledger
refs); the static loop-policy constants stay in the tick objects, so a
lead-less (cold) strategy renders NOTHING regardless of budget
telemetry. The seam face fails open under a broad cage while the
versioned tick write keeps raising on real failures; a deleted or
non-UTF-8-corrupt seam self-heals on the next decision event.

### D3 — the store adapter semantics (W3)

`PosteriorStrategyStore.method_lead` is DTS call site 2 THROUGH the
compose single-point (q_cells' "compose is the sole consumer of the
sampler"). P_LLM is a measured proposal face: each family's share of
the two PROPOSAL channels (q-cell dispatch rows + settled task-ledger
`method_family` signals); settlement-source rows are outcome data and
NEVER enter the prior (counting them would skew toward
dispatch-heavy families). rng = `q_cells_seed_state(ws)` (f(store
state, round) — #251). `decayed_weight` = the γ ladder over the
settled stream (weight_i = Π_{k>i} γ_k, the no-peeking recurrence,
shipped DTS default schedule). `cell_count` = q-cell rows at this
signature; None only while the spine has no data at all (compose falls
back to the settled-ledger total — the seam's documented legacy
fallback). Construction fails loudly; store reads ride the q_cells
store protocol's documented fail-open.

### D4 — the settlement feed (W5)

The bank call lives INSIDE `scalar.settle_round_credit` (the settlement
path named by the issue), behind a first-successful-settlement guard
that tests settlement PRESENCE in the folded ledger row — not row
existence (a first run that recorded the identity row but died before
settling must bank on the retry), and not appended-only (replays and
the late-cite amendment refine the ledger only; the append-only
observation log has no retraction face — re-banking would
double-count). The matching face `q_cells.observe_settlement` joins
the LATEST pending dispatch row by the envelope's claim id (what the
production ALLOW tail records); unmatched = the honest gap (no
fabricated bucket); r_r rail-clamps into [0,1] at the append boundary
(#429 §4). At-most-once polarity under a crash between settle-append
and bank is the accepted residual (never double-bank beats
always-eventually-bank for a learning feed).

### D5 — the envelope sampler (W4)

The e2e dispatch act hosts call site 2 at envelope synthesis: the
declared proposal wins untampled (day-one ruling — Q never overrides
the proposal channel); sampling only when undeclared. Candidates: the
measured proposal channel INTERSECTED with the #432 registry (a
retired token must never ride the prior — the fail-closed vocabulary
gate would lockstep-reject every dispatch in the workspace), else
uniform over the registered vocabulary. The sampled family rides
INSIDE the kunglao_dispatch v1 envelope and the audit stream records
`method_family_recorded` with the full receipt (schema q-cell-sample/1).
Fail-open: a sampler crash leaves the envelope undeclared
(byte-compatible) — a broken kernel never breaks the dispatch loop.
The freshness-merge with #459 kept the sampler byte-identical inside
the new `_launch_dispatch` phase.

### D6 — atomic writes

Since W1 the compose/T2 write faces run from concurrent SubagentStop
processes: every whole-document replace write goes through
writer-unique tmp (mkstemp) + `os.replace` + 0644 parity + non-silent
cleanup (the #275 house rule — no baselined silent handlers; the
ratchet only shrinks).

## Risks / Trade-offs

- Per-SubagentStop cadence (no worker discriminator at the Stop face)
  — bounded by content_hash dedup; recorded scope.
- The W6 queue file is written twice per closure in two ordered shapes
  (full snapshot → dispatched+remaining) — consumers tolerate both.
- Transient seam/tick divergence under concurrent closures — both
  documents whole; self-heals at the next decision event.

## Alternatives Considered

- A renderer adapter inside each consumer (adapting tick files to
  sections) — rejected: duplicates the projection logic per consumer,
  drifts, and the compose README argues the write face owns rendering.
- Baseline-registering the two cleanup handlers (silent-except
  ratchet) — rejected by CI: the house rule bans silent handlers; the
  handlers were made non-silent instead.

## Design-Review Dispositions (openspec gate, 2026-09-30)

The design review (vs the five adjacent specs) PASSED; its findings
and dispositions:

- MEDIUM-1 (the seed claim was false in implementation:
  `q_cells_seed_state` computed the round but never hashed it, so the
  #251 per-round cold-start property did not hold at call site 2) —
  FIXED: the round now rides INSIDE the hashed payload (the
  case_face_seed shape), pinned by a cold-workspace distinct-draws
  test.
- MEDIUM-2 (branch state contradicted the hygiene narrative) — FIXED:
  the non-silent handlers, the baseline revert, and the re-minted
  baselines are committed in this change.
- MEDIUM-3 (the production prior lacked the registry intersect the
  W4 face has) — FIXED: `_proposal_prior` intersects with the #432
  registered vocabulary; an unreadable registry degrades to the
  unfiltered prior with one warn (the #432 GATE stays the enforcement
  face — the q_cells store's own division).
- LOW-1 (mechanisms registry incomplete for the T2 host) — FIXED: the
  t2_closure declaration-only entry.
- LOW-2 (the "ONE object per decision event" sentence lacked the dedup
  qualifier) — FIXED in the spec wording.
- LOW-3 (the two proposal channels double-count a
  dispatched-then-settled declaration) — recorded here as a deliberate
  weighting choice: both channels are the LLM's proposal behavior;
  outcome data remains excluded on both.

- Banking credits at round_close (hook) instead of inside
  settle_round_credit — rejected: the settlement path is where the
  ladder value exists; a hook would re-derive it (a second sampler).
