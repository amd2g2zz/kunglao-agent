# e2e-loop

## ADDED Requirements

### Requirement: verifier-act-dispatch
When the convergence decision is DISPATCH_VERIFIER, the loop SHALL dispatch a verifier act for the top-ranked verification-needing claim — a claude -p run whose prompt carries the maker-checker contract (verify facts/artifacts against the workspace's verification faces; never write facts/F*.md; edit state files only via YAML-safe means) and the STATUS line protocol.

#### Scenario: verifier act fires
- **WHEN** the decision is DISPATCH_VERIFIER and a claim is ranked
- **THEN** a dispatch_attempt row lands with a distinguishable verifier face (V-prefixed prompt)
- **AND** the act outcome follows the same rollback semantics as worker acts

#### Scenario: promotion attempt after verification
- **WHEN** a verifier act lands a verification file
- **THEN** the loop attempts promote_claims through the repo gate; a gate refusal is recorded and the loop continues (honest, not fatal)
