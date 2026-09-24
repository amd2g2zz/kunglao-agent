---
name: case-distilled-gap-report-EXP4
description: 'EXP-4 internal campaign distillation wave (chain tier, method lane, desensitized):
  two-arm measured campaign (7 layered units x {orchestrated loop, plain single-session}) with
  pass-path labeling; per-item distill verdicts (1 card landed, 3 overlaps, 5 abandoned); failure-mode
  rows feeding the next experiment; honest small-wave record (clustering skipped, n too small).
  Read before extending the method/case-distilled lane with agent-governance items or before
  designing the next orchestrated-arm experiment.'
domain: method
family: case-distilled
source_id: EXP4
source_license: internal
retrieved: 2026-09-24
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
---

# EXP-4 chain wave — gap report (desensitized)

Internal-campaign distillate: campaign id EXP4 + internal unit ids only.
Private run ledgers + pipeline log live in untracked runs/ scratch. Pipeline
spec: references/contracts/distill-pipeline.md. All items evidence-derived
(own measured runs); no community-claim items in this wave.

## Measured context (one paragraph)

7 constructed layered decryption-chain units (2/3/6 protection layers) × 2
arms, identical caps: orchestrated loop arm (claim economy + specialist
workers) vs plain single-session arm. Strict mechanical checker both arms (8
published + 8 checker-minted fresh probes, ratio 1.0). Outcome: single-session
7/7; orchestrated 5/7 (1 saturated fail, 1 no-deliverable) at ~6.6x mean cost
and ~4.4x mean wall. Pass-path labeling: both hardest passes were earned by
dispatched specialist workers' artifacts (late dispatch, final third of
budget); the other passes were orchestrator solo analysis (with red-team
workers confirming scaffold claims only). Zero harness-contamination rows
(integrity gate clean both arms).

## Clustering record (honest small-wave note)

n = 9 cleaned items — below any defensible k-means range; clustering skipped
by the pipeline's own singleton-scrutiny logic (algorithmic clustering needs
enough items for silhouette to mean anything). Items assessed individually
against the standing bar; per-item provenance recorded here instead of
cluster rows.

## Per-item verdicts

| Item (desensitized) | Verdict | Landed / rationale |
|---|---|---|
| Dispatch-timing budget partition (solo-first → late, futile dispatch) | distill | case-dispatch-budget-partition (Rule 1) |
| Verifier-channel outage → independent re-implementation in a second runtime | distill | case-dispatch-budget-partition (Rule 2) |
| Checkpoint-immediately-on-peel + eval-surface must state checkpoint conventions | distill | case-dispatch-budget-partition (Rule 3) |
| Independent re-derivation for conflict resolution | overlap | falsifier-library rule 8 already owns the conflict face; EXP-4 uses the no-conflict verification face — delta recorded inside the card |
| Peel-order discipline on multi-layer bundles | overlap | web lane external-peel-ordering-family-adapters covers peel ordering; nothing new at decision-rule depth |
| JS vm-shim Function-trap capture (execute without compiling) | overlap-candidate | likely covered by web JS-VM triage lane; not verified this wave — one-line record, revisit if the web lane card lacks the capture-without-compile variant |
| Per-unit peel specifics (blob envelopes, XOR key tables, magic literals) | abandon | case-specific; dies under the strip test |
| Unit-difficulty gradients as constructed (L1<L2<L3) | abandon | measurement artifact of one corpus, not methodology |
| Budget-cap exhaustion semantics (exhausted=fail accounting) | abandon | governance ruling, already standing; not a card |

Conflict rows: none — nothing in this wave contradicted verified internal
doctrine.

## Failure-mode rows (feeding experiment 5)

1. **Late-dispatch pathology** — 6/7 orchestrated sessions dispatched maker
   workers at 60–90% wall; machinery never got a fair window. Hypothesis for
   EXP-5: a dispatch-deadline rule (first maker dispatch ≤50% wall) converts
   the 2 worker-made passes into a stable pattern.
2. **Stamp-without-write** — one session recorded a peel claim whose artifact
   file was empty (0 bytes); claim-register showed OPEN claims never advanced.
   Detector idea: artifact size/digest presence at claim-advance time.
3. **Checkpoint-convention invisibility** — 12/14 sessions scored 0/N dense
   despite real peels; the checkpoint dir convention was not in any session
   surface. Fix candidate: surface the convention in the task prompt, then
   re-measure the dense curve.
4. **Machinery-overhead dominance on solo-tractable tiers** — when a plain
   session solves the family 6.6x cheaper, the orchestrated arm's only
   defensible claim is verification depth (fewer false positives), not
   pass-rate. EXP-5 should measure quality-per-pass, not just pass@1.

## Abandonment accounting

Zero-source-wave outcome was NOT the case here (1 card landed), but 5 of 9
items were abandoned/overlapped — consistent with the honest-abandonment
directive. No padding cards were created from unit-specific peel detail.
