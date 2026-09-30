# Design — issue-461-option-death (Phase 2)

## Context

Phase 1 (PR #471) made failures attributable: obstacle/1 rows in
`runs/obstacles/`, kinds in the ob= signature segment, the worker
intervention protocol. Phase 2 turns cause-bearing failure states into
learned termination — the issue's "Bayesian option-death termination",
owner-ruling shape: termination is a posterior INSIDE the option
(Option-Critic β(s): "when to quit" is a termination function of the
option, never a sibling arm — naive option enlargement returns the
exploration burden), attribution-in-state is the discriminator, and no
rules/gates are added. The acceptance criteria this design must
satisfy: repeated attributed failures → posterior crosses the
termination threshold; different causes → different posteriors;
cause-free failures do NOT terminate (they trigger attribution
dispatch); an MC replay A/B on the owner's five-step trap; no
verdict-face gates.

Adjacent surfaces checked: #428 posterior store (DTS engine, one
schedule), #429 §4 q_cells (the sampler this wires into), #462 kernel
fold (observe wiring), #460-B feature_prior (the seam pattern mirrored:
optional sampler kwargs + fail-open store threading + byte-identical
absent), #461 Phase 1 (the observation source), the 396 freeze
(DECISION_SOURCES list — strategy_store/compose/q_cells are NOT pinned
faces; the wall follows settlement/dispatch/gate bodies), the
three-state charter (a death verdict is a sampling weight, never a
claim status), status PARK (#634: suspension-not-terminal — the
revivability precedent), worker budgets (the forced-closure safety
bound).

## The four mandated design decisions

### (a) Posterior form — Beta per (obstacle-kind, method_family); a death observation is an obstacle ROW

    cell (K, F):  α = PRIOR_ALPHA + n_rows(kind=K, family=F)
                  β = PRIOR_BETA  + alive_mass(F)
    PRIOR = Beta(1, 1)   (the repo's one uniform base; q_cells BASE_*)

Key choice — the kind SEGMENT of the state signature, not the full
hash. The ob= segment is cumulative by design (every recorded failure
advances the signature — Phase 1's drift disclosure), so exact-hash
keys fragment to powder: the workspace's second detection_trigger
failure lives at ob=detection_trigger=2, not =1, and an exact-key
lookup never sees repetition — "repeated attributed failures" could
never accumulate, defeating the acceptance criterion. Decomposing the
segment into its component kinds gives keys that are stable under
repetition (the kind of a repeated failure does not change), bounded
(5-kind closed enum × the registered family vocabulary), and exactly
the "discriminable cause class a probe can separate" vocabulary the
signature's ob= dim was built from. Option-Critic reading: β_ω(s)
conditions on the attribution context of s; the (kind, family) cell IS
that conditioning, discretized.

What counts as a death observation: one obstacle/1 row — an ATTRIBUTED
failure, i.e. a failure whose cause was pinned by an intervention
probe (registry gate: artifact exists, probe-marker shape). A mere
timeout, a settled failure (credit 0), an unattributed act failure —
NOT death observations (decision (d)). Obstacle rows are counted
STRUCTURALLY as data (the registry's own tolerant read face); a
mis-bucketed or hand-edited row is training noise, per the Phase-1
integrity posture.

Alive evidence — the family's γ-discounted SUCCESS mass from the
q-cell fold (`q_cells.fold(default_store(ws)).family_mass(F)` success
half, shipped adaptive schedule). Rationale: outcome correlation is
the issue's own mechanism ("behavior emerges from state + termination
+ outcome correlation"); a family that still lands credits is not
dead, and a floored-but-sampled dead option that succeeds must push
its own posterior back under threshold — without alive evidence the
posterior could only ratchet up and "revivable" would be mathematically
impossible (decision (c)). DISCLOSED COARSENESS: alive mass is
family-level (settlement rows carry signature hashes, not kinds, so
successes cannot be kind-keyed without inventing a join that does not
exist); a family succeeding in obstacle-free contexts also revives its
kind-cells. This dilution biases AGAINST premature death at short
horizons — the safe direction — but is NOT symmetric at long horizons
(see the aging asymmetry below). Death mass is kind-keyed; alive mass
is family-keyed; both are pure folds.

AGING ASYMMETRY (accepted, disclosed): death counts are lifetime
integers (the registry is append-only history) while alive mass decays
under the fold's uniform tree γ (~0.8^k per later observation row of
ANY family; numerically underflowing after ~3.5k later rows). A family
with 50 ancient successes and 2 ancient same-kind attributed failures
can therefore flip dead with NO new failure once its success mass has
evaporated. Accepted rather than patched: (i) the flip fires only for
a family with no recent successes AND ≥2 attributed failures — a
reasonable death profile; (ii) the failure mode stays bounded — the
option is floored, never removed, and any floor-weighted success
re-banks alive mass at full weight (revival); (iii) the alternatives
(γ-decaying death counts, capping n) each add a knob or break the
"repeated attributed failures" monotonicity the acceptance criterion
names (ADR-001 posture: no new fitted knob here).

Derivation, not persistence: the estimator is a PURE FUNCTION of
(obstacles.read(ws), q_cells fold) computed on demand — no new store,
no write path, no dual-write hazard, no migration. Determinism: the
fold is the existing bit-exact face; counts are integers; α/β/mean are
one division each. The receipt carries no wall clock.

### (b) Decision rule — posterior mean ≥ 0.75; budget stays the safety bound

    option_dead(F | s) ⇔ ∃ kind K ∈ kinds(s): mean(cell(K, F)) ≥ 0.75
    mean(cell) = α / (α + β)

DEATH_THRESHOLD = 0.75 is a POLICY constant (ADR-001 posture:
rationale carried, never runtime-tuned): with the uniform base and
zero alive mass, one attributed failure gives 2/3 ≈ 0.667 (alive), two
give 3/4 = 0.75 (dead) — "repeated" means ≥ 2, a single unlucky
attributed failure never kills an option. Each unit of γ-discounted
family success mass demands ≈ 3 further attributed failures
(mean-rule algebra: n ≥ 2 + 3·a), so an occasionally-succeeding family
stays alive. The rule uses the posterior MEAN, not the survival
function P(p_dead > x): the mean is the point-estimate reading of
"posterior P(dead)" the issue names, deterministic, and adds no second
threshold knob; the survival reading would be strictly expressible but
doubles the parameter surface without owner direction (disclosed, not
chosen). FLOAT BOUNDARY: comparisons run on the computed float64 mean;
only the a = 0 crossings are exactly representable (3.0/4.0 == 0.75
bit-exact) — boundary tests for a > 0 must pin the computed value,
never a hand-derived rational. ∃ over kinds present in the CURRENT
signature: the verdict is state-conditioned — kinds enter through the
ob= segment of the snapshot the decision is made at. DISCLOSED SCOPE
(review defect 5): within a live workspace every registry kind is
ALWAYS present in any snapshot (ob= is cumulative, read from the
current registry), so the kind-conditioning never fires ws-locally —
it is the foreign/synthetic-snapshot guard, not a live discriminator;
the live in-workspace floor is FAMILY-GLOBAL (a family dead under one
kind is floored for all its acts in that workspace), and the operative
"wrong so far vs dead forever" discriminator inside a workspace is the
family-level alive mass (decision (a)). The owner's
attribution-in-state ruling is honored through what the kinds DO
carry — cause resolution: which cells exist and which posterior each
carries — not through live per-act kind switching.

Safety bound: the budget forced-closure (worker-budget machinery,
unchanged) remains the backstop — termination reallocates sampling
mass away from options the evidence has pronounced dead; budgets close
runaway loops REGARDLESS of attribution state. Termination never
raises a budget, never bypasses one, and never touches any gate. If
termination is wrong (posteriors fooled by noise), the budget still
closes the loop — the failure mode of this change is bounded
exploration loss at floor weight, never an unbounded loop.

### (c) DTS interaction — floor-not-delete, revivable (the PARK pattern)

The sampler (q_cells.sample_method_family — DTS call site 2) gains an
optional duck-typed ``death`` mapping {family → verdict}. A dead
family's weight:

    weight_f = P_LLM(f) · θ_f · ARM_FLOOR   (ARM_FLOOR = 0.1)

— multiplied DOWN, never zeroed: the option stays in the action space,
still samplable, exactly the PARK posture (#634: suspension on
condition, not terminal status; revival on the wake condition — here
the wake condition is posterior evidence, not an external gate). A
floored option that IS sampled and succeeds adds alive mass (its
settlement lands in the q-cell log), the posterior mean drops below
0.75, and the option revives with no code path dedicated to reviving
— the same fold runs both directions. New obstacle evidence (more
attributed failures) pushes the other way; the posterior, not a rule,
decides. ARM_FLOOR = 0.1 is a policy constant: the per-family weight
RATIO is 1:10 against any one alive competitor (enough exploration for
revival, enough demotion to redirect the trap trajectory); in the
multi-floor endgame (k of m candidates floored) each floored family
carries ≈ 0.1/(m − k + 0.1k) of the uniform-prior mass before the
theta draw — e.g. four of five floored ≈ 7% each, ≈ 72% on the
survivor.

BOTH production hosts are wired (review defect 2 — the design-review
found the envelope host was missed): call site 2 has TWO live call
sites, (i) `rlvr.strategy_store.method_lead` (the advisory compose
lead) and (ii) `scripts/e2e/checkpoints._sample_envelope_family` (the
#462 W4 kernel wiring — the family that rides the dispatch envelope
for undeclared runs and is banked into the q-cell log at the ALLOW
tail: the action-selection site of the learning loop; missing it would
leave the mechanism an advisory prompt line). Each host computes the
verdicts from its workspace handle and threads them with the same
fail-open kwargs idiom (any failure → no kwarg → the pre-change draw),
the _feature_prior_kwargs precedent — checkpoints already carries a
feature-prior kwargs block; termination joins it.

Import-direction wall: the verdict mapping is DUCK-TYPED — the sampler
reads only ``weight_multiplier``/``dead``/``p_dead`` fields and NEVER
imports rlvr.termination or rlvr.obstacles (the sampler stays
attribution-blind; my test file pins this on full module strings, the
Phase-1 freeze-test idiom). Receipt: a verdict block rides the
per-candidate receipt additively (dead, p_dead, the EFFECTIVE
multiplier actually applied) — present only when a verdict for that
family was supplied, so the determinism wall holds: death=None, an
empty mapping, or an all-alive mapping with multiplier 1.0 leaves the
DRAW byte-identical to the pre-change kernel (x · 1.0 is IEEE-exact;
pinned in tests; the existing bit-exact suite stays 16/16 with zero
edits). RECEIPT INERTNESS (review defect 3): ``verdicts(ws, families)``
returns {} — no kwarg at all — when the registry holds ZERO rows, so a
day-one workspace's receipts are byte-identical too, not just its
draws; once rows exist, all-alive verdicts carry multiplier 1.0 and an
additive death block (draw unchanged — method_lead returns only the
family string and no consumer hashes the receipt). COST NOTE (review
defect 11): after wiring, one method_lead call folds the q-cell log up
to three times (verdicts, q_cells_seed_state, sample_method_family) —
linear per row at current scale, accepted and disclosed rather than
threaded (a shared-fold refactor crosses the sampler's pure-function
boundary for no behavioral gain).

### (d) Cause-free failures — never death evidence

A failure with no obstacle row contributes NOTHING to any α. No
amount of cause-free failure accumulation can move a death posterior
above the prior mean (0.5 at zero alive mass — itself never ≥ 0.75).
This is the owner's core ruling, mechanized: cause-free failures are
the ATTRIBUTION PROTOCOL's feed (Phase 1: isolate → probe → record →
cite), not termination's. Nothing rejects them (legal output), nothing
counts them, and EX-6's cause-free control arm demonstrates the
mechanism end-to-end. Corollary: a workspace whose workers never
attribute sees zero dead options ever — termination inherits
attribution's adoption, and under-attribution degrades to today's
kernel (decay-only), the disclosed adoption dependency.

## EX-6 — the MC replay A/B (issue acceptance: the trap trajectory)

Declared synthetic; the EX-4 TRAJECTORY truth table imported as the
environment. Families = the five registered trap tokens; truth: the
first four deterministically fail with their TRAJECTORY kind when
tried; crypto-core-identification succeeds (credit 1.0) when tried.
One persistent temp workspace per arm; EPISODE_BUDGET acts per
episode; N_EPISODES episodes; the registry + q-cell log persist across
episodes WITHIN an arm (that persistence IS the learning). Per act:
fresh snapshot (attribution-in-state honestly moves the signature),
a real q_cells.sample_method_family draw (seeded per (episode, act),
SHARED across arms — the paired design: episode 1 is identical for
all three arms, C stays identical to A forever, and B diverges
exactly at the act its verdicts first floor something —
deterministic), execution against the truth table, the DISPATCH
observation row (the production ALLOW-tail fidelity — pending mass),
and on failure the settlement row (credit 0.0) plus — attribution
arms only — the real obstacles.record with the EX-4 probe artifact.
Arms:

  A decay-only        — the current kernel (no death kwarg);
  B attribution+death — failures record obstacle rows; the sampler
                        consults termination verdicts;
  C cause-free        — termination consulted, but failures record NO
                        obstacle rows (the worker skipped attribution).

NON-REAL FACES (enumerated, review defect 6): P_LLM is a DECLARED
uniform prior over the five families (both production hosts measure
the proposal channel from dispatch rows; the replay pins the prior so
arm deltas attribute to termination, not to prior-measurement noise —
the same declared-prior choice EX-5 documents); the act environment
is the deterministic truth table (no Bernoulli draws); episodes are
independent except through the persistent registries. FRAGMENTATION
ASYMMETRY (disclosed): arm B's obstacle recording advances ob= at
every failure, so B's failure evidence fragments across CHANGING
signature cells while arm A concentrates unbounded local evidence in
one cell — attribution makes B's ORDINARY DTS demotion WEAKER than
A's for the same failure count (the family anchor is SHRINK_CAPped at
8 pseudo-observations). B's advantage therefore comes from the
termination floor itself (fires at n = 2 attributed failures), not
from ordinary DTS — the experiment measures termination ON TOP of a
slightly weakened baseline, the honest and conservative direction;
the results document records this asymmetry.

Expected (asserted): B's four trap families accumulate cells over
threshold → dead → floored out of sampling mass → crypto-core reached
at least as often and as early as A (breakthrough rate +
acts-to-breakthrough + wasted-acts metrics; the learning split
first-half vs second-half shows the posteriors crossing during the
run); C reports zero dead cells (all-alive verdicts) and tracks A —
the negative control. Determinism (review defect 9): obstacle records
pass FIXED ts values (the EX-4 idiom); settlement/dispatch rows are
appended through q_cells.append_observation with a fixed ts (the
observe() wrapper hides ts — the replay uses the append face the
wrapper delegates to); the results document embeds AGGREGATES only
(never raw rows, never temp paths), so experiments/ex6-results.json
(committed) is byte-identical across reruns.

## Library faces (scripts/rlvr/termination.py)

- constants: ``SCHEMA = "option-death/1"`` (report), ``DEATH_THRESHOLD
  = 0.75``, ``ARM_FLOOR = 0.1``, ``PRIOR_* = 1.0``
- ``report(ws, snap=None) -> dict`` — the deterministic receipt: cells
  (kind, family, deaths, alpha, beta, p_dead, dead) sorted by (kind,
  family), family summary (alive_mass, dead kinds), threshold, floor,
  the fold's post-replay γ. No ts. Corrupt/absent inputs degrade to
  the empty report (fail-open reads), never a raise.
- ``verdicts(ws, families, snap=None) -> dict[str, dict]`` — per
  family {dead, p_dead (the max cell mean), kind (the argmax cell),
  alpha, beta, weight_multiplier (ARM_FLOOR iff dead else 1.0),
  threshold}; a family with no cells gets the base cell
  Beta(1, 1 + alive_mass) (never dead without deaths — structural).
  ZERO-REGISTRY RULE (review defect 3): when the obstacle registry
  holds no rows, verdicts returns {} — the callers thread no death
  kwarg and day-one receipts stay byte-identical (not just the draws).
  ``families`` is an iterable of the candidate families (the host's
  prior keys — ``verdicts(ws, prior.keys())``; review defect 7).
- ``option_dead(ws, family, snap=None) -> dict`` — the single-family
  decision face (verdicts(families=[family]) shape).
- CLI: ``report`` subcommand (the q_cells --cells precedent — offline
  diagnostic; the live faces are library calls).

Lazy imports only (obstacles, q_cells inside functions — the state.py
import-cost precedent); fail-open reads; loud-result shapes like the
sibling stores.

## Key decisions (summary)

1. Derived posterior, no new store — pure folds over the landed
   registries; determinism for free; no dual-write hazard.
2. (kind, family) keying — repetition-stable, bounded, exactly the
   signature's attribution vocabulary decomposed.
3. Death from obstacles (attributed only), alive from settlements
   (outcome correlation) — one engine each side, both existing faces.
4. Mean rule at 0.75, floor at 0.1 — policy constants, ADR-001
   posture, documented algebra (≥2 deaths, ≈3 deaths per alive unit).
5. Duck-typed verdict at the sampler — zero new imports in the
   decision-path kernel; BOTH hosts wired (strategy_store.method_lead
   AND e2e/checkpoints._sample_envelope_family — the action-selection
   site), each fail-open.
6. No activation flag — evidence-gated inertness at day one: a
   workspace with zero obstacle rows gets NO kwarg at all (receipts
   byte-identical); a workspace with <2 attributed same-cause failures
   per family gets all-alive multipliers 1.0 (draws byte-identical).
   EX-6 ships in the same change.
7. Phase-1 spec amendment — the attribution-state recording-only
   clause carries the Phase-2 carve-out (the sampler floor is the one
   licensed consumption; reject/block/gate stays barred forever),
   amended in the still-open Phase-1 change so the archived spec set
   never contradicts itself.

## Risks / trade-offs

- Kind-keyed cells cannot see cross-cause accumulation (a family
  failing for many DIFFERENT attributed causes accumulates each cell
  separately). Accepted: cause-diversity is itself evidence the option
  is mis-fit for this workspace, but pooling it would need a
  family-level death posterior that destroys "different causes →
  different posteriors". The q-cell fold's family failure mass already
  demotes such families through the ordinary DTS mean — the systems
  compose rather than duplicate.
- Family-level alive mass dilutes kind-cells short-horizon (disclosed
  in (a), safe direction) — and the AGING ASYMMETRY inverts it at
  long horizons (death counts are lifetime, alive mass decays;
  disclosed in (a) with the bounded-failure-mode acceptance).
- Attribution weakens ordinary DTS slightly (ob= advances at every
  failure → failure evidence fragments across signature cells) —
  termination composes on top rather than duplicating the demotion;
  EX-6 measures it against that slightly weaker baseline (conservative
  direction, disclosed in the EX-6 section).
- Hand-edited/mis-bucketed obstacle rows enter as death observations —
  the Phase-1 integrity posture (training noise; the 0.75 gate + alive
  mass outvote isolated noise).
- Workspace-lifetime posteriors: no cross-workspace transfer (the
  #460-substrate v0.2 seam — named, not built).
- Sampler receipts grow by an additive block only when verdicts are
  threaded; downstream receipt-hash consumers (none pinned today)
  would see new keys — the receipt schema stays q-cell-sample/1 with
  additive fields (the no-backcompat policy makes additive fields the
  cheaper face than a schema bump).

## Test plan (spec → tests)

- tests/test_rlvr_termination_461.py — Req 1 (posterior form): cell
  derivation over synthetic registries (counts, α/β/mean float-hex
  pins — the bit-exact idiom, new pins live HERE, not in the frozen
  suite); different-causes-different-posteriors; repetition crossing
  threshold at exactly 2; alive-mass revival arithmetic; cause-free
  no-op (settlement failures alone never dead); fail-open reads
  (corrupt registry, absent store → empty report).
- same file — Req 2 (decision + sampler): verdicts/option_dead
  state-conditioning (synthetic snap without a kind suppresses that
  kind's cells); verdicts zero-registry {} rule; sampler floor
  application via duck-typed mapping (weight × 0.1, receipt additive
  block, effective-multiplier honesty); death=None and empty-mapping
  byte-identity (literal receipt pin); q_cells source wall
  (full-module-string: no obstacles/termination import);
  strategy_store fail-open thread; the ENVELOPE HOST pin
  (checkpoints._sample_envelope_family threads verdicts — the
  action-selection site; source-shape pin on the kwargs block).
- tests/test_ex6_option_death_461.py — Req 3: EX-6 determinism
  (byte-identical rerun) + expectations (B ≥ A breakthrough rate,
  B's dead cells = the four trap (kind, family) pairs, C zero dead,
  crypto-core never dead, learning halves split).
- RED-first: all fail before implementation; the frozen
  tests/test_rlvr_bitexact.py stays 16/16 with ZERO edits.

## Design review (adversarial)

Independent adversarial review (architect subagent, read-only,
2026-09-30) vs the four mandated decisions, the owner rulings, and
the adjacent code (obstacles/q_cells/strategy_store/posteriors/state/
feature_prior/compose, e2e/checkpoints, blocker_lint, the freeze and
bit-exact suites, EX-4/EX-5, both 461 change folders, method registry).

Outcome: FAIL → fixed. 11 defects (2 HIGH, 4 MEDIUM, 5 LOW), all
addressed in this design/spec revision BEFORE any test was written.
Round 2 (same reviewer, fix-verification only): PASS — no remaining
CRITICAL/HIGH defects, none introduced; residual non-blocking notes:
the envelope host's receipt is audit-stream recorded (additive keys
already covered by the receipt risk bullet) and EX-6's per-act
settlement row must carry the same act's signature hash as its
dispatch row (cell coherence — honored in the implementation):

1. HIGH missing MODIFIED clause — Phase-1's "no face SHALL re-rank on
   obstacle presence" contradicts Phase-2 actuation and would archive
   into a self-contradictory spec set (validate --strict cannot catch
   it) → the clause is amended IN THE STILL-OPEN Phase-1 change
   (issue-461-attribution-state) with the named Phase-2 carve-out
   (sampler floor licensed; reject/block/gate barred forever);
   obstacles.py's stale "zero decision posture" docstring gets a
   one-line Phase-2 note in this change (non-goal relaxed
   accordingly).
2. HIGH wrong call-site topology — "the compose single-point's only
   sampler" was factually wrong: e2e/checkpoints._sample_envelope_family
   is the production envelope sampler host (the action-selection site
   banked at the ALLOW tail) and was unwired → BOTH hosts wired with
   the fail-open kwargs idiom; spec requirement names both; an
   envelope-host pin test added.
3. MEDIUM overstated inertness + unspecified empty-registry shape →
   verdicts() returns {} at zero registry rows (no kwarg at all —
   receipts byte-identical day one); the claim reworded to
   draw-identity + no-kwarg receipt identity; all-alive multipliers
   are IEEE-exact × 1.0.
4. MEDIUM undiscounted death vs γ-decayed alive — long-horizon ratchet
   → AGING ASYMMETRY section added in (a): disclosed, accepted
   (bounded failure mode — floor keeps the option samplable; any
   floor-weighted success revives at full weight), alternatives
   (γ-decay/cap on deaths) rejected with reasons.
5. MEDIUM state-conditioning is a live no-op + family-global floor →
   disclosed plainly in (b): the kind-conditioning is the
   foreign-snapshot guard; the live discriminator is family-level
   alive mass; kinds carry cause resolution.
6. MEDIUM EX-6 fidelity gaps → non-real faces enumerated (declared
   uniform prior, deterministic truth table); dispatch rows recorded
   per act (the ALLOW-tail fidelity); the fragmentation asymmetry
   (attribution weakens B's ordinary DTS vs A — conservative
   direction) disclosed in the EX-6 section.
7. LOW verdicts() call-signature inconsistency → unified:
   verdicts(ws, families, snap=None); hosts pass prior.keys().
8. LOW single-floor arithmetic wording → per-family 1:10 ratio + the
   multi-floor endgame mass formula.
9. LOW EX-6 wall-clock ts hazards → fixed ts on obstacle records and
   on settlement/dispatch rows (via append_observation's ts face);
   results doc embeds aggregates only.
10. LOW float boundary → FLOAT BOUNDARY note in (b): float64 mean
    comparisons; only a = 0 crossings exactly representable.
11. LOW triple fold per lead draw → disclosed in (c) (linear, accepted
    — a shared-fold refactor crosses the sampler's pure-function
    boundary for no behavioral gain).

Verified clean by the same review: the freeze wall (strategy_store/
compose/q_cells/checkpoints are not pinned faces; the full-module-
string obstacles wall unaffected), the bit-exact suite (16 tests,
nothing pins the sampler), byte-identity mechanics (fork order, RNG
consumption, x·1.0 IEEE identity), seed isolation (verdicts never
enter q_cells_seed_state), threshold algebra (n ≥ 2 + 3·a; revival at
any a > 0 with one success), the (kind, family) key choice vs the
cumulative-ob= fragmentation, the cause-free path (arm C well-formed),
owner rulings 1/4/5/6, compose consumers (family string only), naming
and registration surface (no collisions), the store face
(posteriors.q_cell_store absent — JSONL is the real store).
