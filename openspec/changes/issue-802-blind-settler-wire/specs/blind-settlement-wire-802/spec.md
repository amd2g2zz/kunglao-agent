# blind-settlement-wire-802 delta — issue-802-blind-settler-wire

## ADDED Requirements

### Requirement: Production settlement is written through the blind face

The production stop face SHALL route settlement through the blind
face: the pending step's blind input doc SHALL be parked by the
whitelist builder (producer narrative and the policy learning faces
excluded by construction), and every parked claim with a ruling SHALL
settle through `settlement_scorer.settle_blind` (the
`scalar.validate_verdict_doc` stack). The unblinded `settle_step`
judgment legs (#712 credit, crystallization, belief) SHALL run only
behind the explicit eval gate (`KUNGLAO_EVAL_SETTLE=1`); the hash-only
mechanical bookkeeping (step-record/2, transition close, attributed
waste) runs in every mode.

#### Scenario: the stop face parks and never banks unblinded credit

- **WHEN** a worker step settles at the SubagentStop boundary in
  production (default) mode
- **THEN** the parked doc `runs/settlement-input-<claim>.json` exists
  and carries `blind-settlement-input/1`, the receipt carries
  `step_credit: null`, and no forbidden-face bytes appear in the doc

#### Scenario: the eval gate restores the legacy face

- **WHEN** `KUNGLAO_EVAL_SETTLE=1`
- **THEN** the legacy unblinded settlement runs unchanged and nothing
  is parked

### Requirement: A blind settlement settles exactly what was blinded

`settlement_wire.settle_parked` SHALL refuse (writing nothing to the
rollout ledger) when the input doc is missing or unparseable, when the
input doc carries a forbidden face (the settlement-side wall, before
any content read), when the ruling grader's identity differs from the
parked input's identity, or when any artifact's current bytes no longer
hash to the parked sha256.

#### Scenario: sha drift after the ruling

- **WHEN** an artifact's bytes change between the park and the settle
- **THEN** the settlement is refused with a sha-drift reason, the
  rollout ledger gains no row, and the wire ledger records the loud
  refusal (settled=false)

### Requirement: The claim mint rides claims_store, never around it

A decisive blind settlement SHALL flip the claim through
`claims_store.apply`: an oracle pass mints `settle_proven` with a
verification reference (the store's verifier-integrity resolver
refuses any reference that does not resolve to a PASSED record —
fail-closed), an oracle fail mints `settle_refuted`, and the mint's
actor carries the settler identity (`settler:<identity>`).

#### Scenario: PROVEN is refused without a PASSED record

- **WHEN** a blind settlement settles with an oracle pass while the
  claim's verification record classifies as REJECTED (or is absent)
- **THEN** `claims_store.apply` refuses, the register status is
  unchanged, and the refusal is loud on the wire row and in provenance

### Requirement: Production settlements show settler-identity rows

Every blind settlement EVENT SHALL land one content-hash-deduped
`settlement-wire/1` row in the consolidated settlement ledger carrying
the non-empty settler identity — including refusals (`settled: false`)
— so the `blind-settlement-wired` liveness fingerprint proves the face
fired on a live workspace.

#### Scenario: the fingerprint reads a live workspace

- **WHEN** a blind settlement (or its loud refusal) has occurred
- **THEN** `runs/settlement.jsonl` contains a `settlement-wire/1` row
  with a non-empty `identity`, and a re-run over an unchanged
  workspace appends no duplicate
