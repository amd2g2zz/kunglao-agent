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

## Liveness is not usability

Every layer of a delivery has a cheaper fake that LOOKS like success. Name
the fake, forbid it explicitly:

| Level | Liveness signal (fake) | Usability signal (required) |
|---|---|---|
| environment build | script loads without throwing | target function produces correctly-shaped output |
| service | port listens / health endpoint 200 | a real action call returns the full result |
| network | an OPTIONS preflight / unguarded endpoint answered | the TARGET request returns business success |
| delivery | fixture replay / hardcoded sample matches | freshly generated parameter accepted by the server |

The action-level **result tuple** is the unit of proof: plaintext (or
recovered value) + the final request actually sent (route, body) + HTTP
status + business response. Any tuple member missing → "unconfirmed", not
"passed". A standalone parameter check (length, alphabet, format) is a
smoke test, never acceptance.

## The unified pre-request closure gate

Before the first real (state-changing, billable, bannable) request, run ONE
aggregating gate that collects every sub-audit at once: environment/runtime
contract audit, fingerprint/baseline consistency, session and TLS-client
identity match, request-semantics audit, and code-quality checks on the
generated deliverable. Any sub-audit failing blocks the real request —
"noted the risk in the summary" is not a pass. Gated behind the same rule:
a deliverable must generate parameters FRESH (no hardcoded captured values),
reuse the exact baseline identity (UA/headers/TLS/session/cookies) the
evidence was captured under, and carry no analysis scaffolding.

## Acceptance layering

Verification is layered, and lower layers never substitute for higher ones:

1. **Offline fixture regression** — known input/output pairs replay in the
   runtime without network (catches algorithm regressions).
2. **Representative live requests** — a handful (convention: five) of
   current, representative requests succeed against the real endpoint
   (catches session/binding/freshness issues fixtures cannot).
3. **Duration** — sustained operation for the period the task claims to
   sustain (catches expiry/rotation the five-shot cannot). Time not actually
   run cannot be claimed as passed.
4. **Browser-independence check** — the protocol deliverable regresses in an
   environment with NO browser; passing in the analysis browser proves the
   analysis path, not the deliverable.

Retry discipline inside acceptance: automatic retries for read-only
requests only; a failed non-idempotent request (POST-class) is NEVER blindly
replayed — verify server-side effect first, then decide, because the replay
itself can be the incident (double submit, double charge, double ban).

## Session identity & staleness

Evidence and calls bind to a session identity (tab/document/connection).
Any navigation, disconnect, suspension, or identity change invalidates prior
bindings AND prior results: rebind, re-verify. A stale-identity result that
"looks fine" is treated as unverified, because the environment behind it may
have silently changed. Suppressed-page-behavior test modes (e.g. suppressing
the post-success redirect during verification) are allowed only when the
real response is still recorded.

## Signer-service packaging

Recovered signers that must be callable from other runtimes are packaged as
a local HTTP sign-service (the recovered environment stays resident; callers
POST input, receive the computed value) rather than spawning a fresh process
per call — per-call subprocesses reintroduce environment drift and startup
fragility. Client-side integration carries its own trap table: parameter
serialization must go through the HTTP client's native parameter handling
(manual URL-quoting of computed values re-encodes differently and breaks
server-side verification), cookies pass as structured values not raw header
strings, and the client's transport fingerprint should match the baseline
identity the signer assumes.

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
