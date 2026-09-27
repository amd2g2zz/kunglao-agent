---
name: external-delivery-verification-gates
description: 'Delivery and verification gates for recovered web protocols (external-distilled, S1/S2/S3/S4):
  liveness ≠ usability (port-up/loading-success ≠ working), the action-level result tuple, unified pre-request
  closure gates, acceptance layering (offline fixture regression → representative live requests → duration),
  stale-session invalidation and non-idempotent replay prohibition, signer service packaging (HTTP middle layer
  over subprocess). When a recovered signer/protocol is about to be declared working or delivered.'
domain: web
family: external-distilled
source_id: S1,S2,S3,S4
source_license: none,MIT,none,Apache-2.0
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(web-re-quickref anti-pattern 4)
---

# Delivery & verification gates (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above. The replay-is-the-checker principle is
> web-re-quickref anti-pattern 4; this card generalizes it into a delivery
> gate doctrine: what "working" means at each level, and what may NOT count.
> Advisory: gates are fail-closed — any sub-audit failure blocks the real
> request; noting risk in a summary is not a pass.

## Liveness is not usability

The verdict algebra: `confirmed ⇔ full result tuple ∧ fresh parameters ∧
baseline identity match`; every other state is "unconfirmed". Each level of a
delivery has a cheap fake that LOOKS like success — name it, forbid it:

| Level | Liveness fake | Usability signal (required) |
|---|---|---|
| environment build | script loads without throwing | target function produces correctly-shaped output |
| service | port listens / health endpoint 200 | a real action call returns the full result |
| network | an OPTIONS preflight / unguarded endpoint answered | the TARGET request returns business success |
| delivery | fixture replay / hardcoded sample matches | freshly generated parameter accepted by the server |

The action-level **result tuple** is the unit of proof: plaintext (or
recovered value) + the final request actually sent (route, body) + HTTP
status + business response. Any tuple member missing → "unconfirmed", not
"passed". A standalone parameter check (length, alphabet, format) is a smoke
test, never acceptance.

## The unified pre-request closure gate

Before the first real (state-changing, billable, bannable) request, run ONE
aggregating gate that collects every sub-audit at once:

| Sub-audit | Verifies |
|---|---|
| environment/runtime-contract audit | sandbox fidelity vs live baseline |
| fingerprint/baseline consistency | one identity across all evidence and audits |
| session + TLS-client identity match | transport face matches the capture face |
| request-semantics audit | headers/order/lifecycle semantics of the deliverable |
| code quality | generated deliverable carries no scaffolding, no hardcoded captured values |

Any sub-audit failing blocks the real request. Deliverable rules carried by
the same gate: parameters generated FRESH; the exact evidence-capture
identity reused (UA/headers/TLS/session/cookies); zero analysis scaffolding.

## Acceptance layering

Verification is layered, and lower layers never substitute for higher ones —
each tier catches a failure class the tiers below cannot see:

| Tier | What | Catches |
|---|---|---|
| L1 offline fixture regression | known I/O pairs replay in-runtime, no network | algorithm regressions |
| L2 representative live requests | ~5 current, representative requests succeed | session/binding/freshness issues fixtures cannot |
| L3 duration | sustained operation for the claimed period | expiry/rotation the five-shot cannot; time not actually run cannot be claimed as passed |
| L4 browser-independence | deliverable regresses in an environment with NO browser | analysis-path-only success; the protocol deliverable must survive a headless container |

Retry discipline: automatic retries for read-only requests only; a failed
non-idempotent request (POST-class) is NEVER blindly replayed — verify
server-side effect first, because the replay itself can be the incident
(double submit, double charge, double ban).

## Session identity & staleness

```text
// evidence and calls bind to a session identity (tab/document/connection)
on navigation | disconnect | suspension | identity change:
    prior bindings INVALID, prior results UNVERIFIED
    (the environment behind them may have silently changed)
    -> rebind, re-verify; a stale-identity result that "looks fine" stays unverified
suppressed-page-behavior test modes (e.g. suppressing the post-success redirect):
    allowed ONLY when the real response is still recorded
```

## Signer-service packaging

Recovered signers that must be callable from other runtimes are packaged as a
local HTTP sign-service (environment stays resident; callers POST input,
receive the computed value) — per-call subprocesses reintroduce environment
drift and startup fragility. Client-side trap table:

| Trap | Rule |
|---|---|
| parameter serialization | go through the HTTP client's native parameter handling — manual URL-quoting of computed values re-encodes differently and breaks server-side verification |
| cookies | structured values, not raw header strings |
| transport face | client fingerprint should match the baseline identity the signer assumes |

## Delivery-shape note (conflict flagged)

External sources split on the final deliverable: browser-bridge services
(call the page's real function live) vs standalone protocol programs. Our
doctrine (web-re-quickref anti-pattern 5) requires the standalone protocol
script that survives a headless container; the bridge shape contradicts it
and is RECORDED AS A CONFLICT (pipeline Stage 4 row X1), not adopted — per-
task exceptions stay explicit decisions, not defaults.

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (five-step
workflow + anti-patterns),
[machine-check-contract](../../../contracts/machine-check-contract.md)
(machine_check record shape),
[loop-stage-gates](../../method/process/loop-stage-gates.md) (stage
completion discipline).

## Tool section — the offline fixture gate, mechanical (registered CLI)

The acceptance layering's first gate (offline fixture regression) has a
registered CLI: `tools/web/sign_candidate_verify.py` (tag
`js:sign-verify`).
Reach for it when: a recovered candidate is about to feed a delivery
claim — differential verification against captured samples is the gate,
and a candidate that is not `verified` may not pass it:

```bash
# emit a harness that calls the recovered candidate with every captured
# sample and fingerprints the outputs
python tools/web/sign_candidate_verify.py emit \
    --candidates artifacts/candidates.json --out harness.js
# run harness.js in the page console, save its JSON, then:
python tools/web/sign_candidate_verify.py apply \
    --results artifacts/results.json --candidates artifacts/candidates.json \
    --out artifacts/verified.json --minimum-matches 2
```

The promotion rule IS the gate algebra: `verified=true` only when every
planned sample ran and matched and the count clears the minimum — partial
matches and never-ran samples stay false with per-sample reasons. A
candidate that is not `verified` may not feed a delivery claim.
