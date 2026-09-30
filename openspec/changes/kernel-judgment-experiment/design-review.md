# Design review — kernel-judgment-experiment (pre-code gate)

Reviewer: independent subagent (design review only; no code written,
no files modified), dispatched 2026-09-30 against the pre-registration
in this directory plus the kernel sources
(`scripts/rlvr/q_cells.py`, `scripts/rlvr/posteriors.py`,
`scripts/rlvr/state.py`, `scripts/method_families.py`,
`scripts/rlvr/strategy_store.py`, `scripts/e2e/checkpoints.py`).

## Verdict: NEEDS-CHANGES → amendments applied pre-run

The reviewer confirmed the world model, metrics, and honesty argument
sound (no leakage channel found; the flat P_LLM prior verified as the
correct control — day-one kernel distribution is exactly uniform under
it; round-robin verified symmetric across arms) and verified every
kernel claim in the design against code by execution (SHRINK_CAP=8.0,
shipped schedule floor 0.8/λ 0.9, γ=1.0 accepted and undiscounted,
sampling ∝ P_LLM·θ, 12 registered tokens, 8 distinct class hashes).

## Required amendments (all applied to design.md before any run)

1. **D1 gated on kernel-g1**: D1 (implementation defect) additionally
   requires kernel-g1 NO_SEPARATION at n=100 in R3 — a kernel that
   fails only under discount routes to D2's γ-drag clause, not
   "implementation defect".
2. **D2 extended + precedence fixed**: D2 gains the γ-drag-dominant
   clause (kernel NO_SEPARATION at n=100 while kernel-g1 separates at
   any n); D4 outranks D2 for the headline when D4's conditions hold;
   all fired rows are reported.
3. **Seed count pinned**: exactly 200 (ids 0..199) in design Decision
   4/8 and the spec delta; the "drop to the floor" semantics deleted —
   the seed count never changes.
4. **Crash/look protocol + test isolation**: Decision 9 added —
   mid-run crash restarts from scratch with no partial inspection;
   post-look fixes ship as named deviations; the committed test's
   micro-run uses seed ids 9000–9001 (outside the real range) so no
   test observes a real grid cell before the single run.

## Optional suggestions adopted

- **D3′** added: the state-key sign flip read at the γ=1 face (the
  shipped-γ arm is too amnesiac to express anchor harm reliably).
- **Mechanistic expectations pre-registered** (Decision 9): shipped-γ
  retained fold mass ≈5.6 pseudo-observations over an 800-row stream
  (per own-class-act decay γ^8); kernel NO_SEPARATION at n=100 is a
  plausible CORRECT-kernel outcome; kernel-g1 is the sensitive
  instrument.
- Waste-metric sign test clarified (mean-over-classes scalar carries
  the test; per-class censoring rule is D3/D3′ diagnostics only; tie
  counts reported); power caveat (~57% detectable win fraction) and
  no-multiplicity-correction rationale pre-stated.
- Runtime estimate corrected (10^9-scale dict ops; tens of minutes).

## Rejected / not adopted

- Changing regime constants (e.g. raising p_weak): the reviewer
  explicitly advised against — the R1/R2 contrast is well-calibrated;
  the separability problem was in discriminator logic, not the world.
- Measured-proposal prior instead of flat: rejected by the reviewer
  itself as a conflation of "kernel learns" with "kernel rides a good
  prior"; flat P_LLM kept.
