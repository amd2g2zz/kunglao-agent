## Why

A pending dispatch replaces the intake prior with its own historical family, so a supported alternative is rejected even after new evidence motivates a pivot. The dispatch record also needs to distinguish sampler weights from unknown end-to-end behavior probability.

## What Changes

- Maintain a current evidence-backed candidate set separately from historical weight adjustments; revalidate authorization and constraints at each decision. Retain valid history/case/store fallback only when intake and discovery sources are absent; keep actual tool availability at the existing dispatch capability gate.
- Record candidate provenance, sampled and actual families, and override rationale without fabricating a declaration behavior propensity. Keep exact uniform probability; defer the legacy learned MC estimator and downstream OPE consumers to #1034.
- Exercise pending and settled multi-round dispatches and invalid, revoked, unavailable, and cold-start cases.

## Capabilities

### New Capabilities

- `candidate-support`: State-dependent support and honest attribution of method-family dispatch decisions.

### Modified Capabilities

None.

## Impact

The strategy-store sampler, dispatch family gate, and observation records are affected. Tools remain dispatch parameters; existing vocabulary and admission checks remain authoritative. INV-001, INV-002 and INV-003 remain observable through the same dispatch and settlement surfaces.
