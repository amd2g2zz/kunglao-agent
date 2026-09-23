---
name: complexity-routed-model-tiers
description: 'Complexity-signal model routing with an invariant verification gate (external-distilled, S7):
  assign the lightest capable model tier per work unit from objective, countable complexity signals; purely
  mechanical units → light tier, any implicit-reasoning content → never light; the verification gate is
  invariant across tiers; two consecutive verification failures on one unit auto-escalate one tier. When
  assigning models/tiers to worker dispatches, sub-agent fan-out, or bulk generation phases without weakening
  the checker.'
domain: contracts
family: external-distilled
source_id: S7
source_license: MIT
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(machine-check-contract)
---

# Complexity-routed model tiers (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized
> paraphrase; provenance = S-id above (agent-contract formality
> source). Our dispatch protocol already carries tool tiers (T1/T2/T3 tool
> budgets) and the global rules carry model-selection guidance; this card
> lands the missing piece — signal-driven PER-UNIT model assignment with an
> invariant checker.

## The pattern

Bulk phases (generation, transcription, distillation fan-out) burn tokens
mechanically; verification stays cheap and centralized. So: route each work
unit to the lightest CAPABLE tier, judged by objective countable signals
read off the artifact itself — never vibes:

| Signal | Meaning |
|---|---|
| purely-mechanical content (no implicit reasoning) | convertible by template — light tier |
| implicit-reasoning content (pre/post-shape reasoning, no body) | requires real reasoning — never light |
| invariant-like conditions (cross-cutting consistency rules) | consistency reasoning |
| quantifier-dense conditions | resists mechanical translation |
| recursion / termination-sensitive logic | termination-sensitive |
| cross-unit interfaces | protocol logic between agents |
| verifier's own difficulty estimate (PO-count class) | checker-side difficulty prior |

**Fast paths:** purely-mechanical unit → always light. Any implicit-reasoning
content → never light. Tier names are abstract; map to whatever the runtime
offers, and never pick a tier above the session's main model.

**The safety argument is the checker, not the chooser:** whichever tier
generates the artifact, the SAME verification gate judges the result. The
gate is invariant; tier changes cost tokens, not safety.

**Two-strike escalation:** if one unit fails the same verification twice
consecutively, auto-escalate that unit one tier (and record it). Escalation
is per-unit, bounded, and evidence-triggered — the anti-patterns are
global escalation on first failure and silent tier-shopping until a lucky
pass.

## Mapping onto kunglao

- Dispatch tiers (T1/T2/T3) bound TOOLS per dispatch; this pattern bounds
  MODEL per work unit — orthogonal axes, compose freely: a light-tier model
  with a T2 tool budget for mechanical units; the checker gate stays the
  machine-check contract.
- The complexity signals are computable from artifacts we already hold
  (claim density, hypothesis count, obfuscation-family novelty, falsifier
  count) — the card's move is: route on measured signals, not on dispatch
  author's mood.

## Anti-patterns

- Tier assigned by author confidence instead of artifact signals.
- Checker strength varying with the generator's tier (weaker checkers for
  lighter models — the invariant-gate rule forbids this).
- Escalation as punishment instead of evidence-triggered bounded response.

Companions: [machine-check-contract.md](../machine-check-contract.md),
[dispatch-protocol](../../orchestration/dispatch-protocol.md) (tool-tier
face), [error-response-taxonomy.md](../error-response-taxonomy.md).
