# Case 2: Web request-signing recovery

> One-page sanitized battle report. The target is a live commercial product;
> disclosure is deliberately minimal — no recovered secrets, parameter values,
> or protocol field values are published.

## Target

The request-signing scheme of a large-scale web application: how the
signature parameter attached to API requests is computed. The task:
characterize the signing computation and reproduce it offline for every
recorded exchange — including exchanges withheld from the analysis.

## Defense surface

- Packed and obfuscated JavaScript bundles
- Anti-debugging traps and decoy code paths in the bundle
- Runtime-generated nonce material mixed into the signature input
- Active anti-bot fingerprinting on the client

## Agent route

1. Bundle unpacking and deobfuscation; indexing the unpacked code for
   navigation.
2. Static trace of the signing entry point through the call graph.
3. Dynamic instrumentation in an anti-detect browser: hooks and network
   capture record live (input → signature) exchanges.
4. Isolation of the load-bearing computation from decoy paths; identification
   of where the nonce material enters the signature input.
5. Offline re-implementation of the signing computation.
6. Replay verification against the recorded corpus, with withheld exchanges
   never shown to the analysis until the final check.

## Verdict

The signature scheme was characterized end-to-end and the computation was
reproduced byte-exact against every recorded exchange, withheld ones
included.

## What this demonstrates

Web-lane capability: full characterization of a production signing scheme
under obfuscation and anti-bot defenses, with held-out replay keeping the
claim honest — a reproduction cannot overfit exchanges it never saw.
