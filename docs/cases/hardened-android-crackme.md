# Case 1: Hardened Android native crackme

> One-page sanitized battle report. This target is a constructed crackme built
> in-house to exercise the full protection stack, so its recovered constants
> are publishable.

## Target

A commercial-grade hardened crackme for Android: a Rust native library
(`.so`) carrying a license-validation routine. The task: recover the three
cryptographic parameters embedded behind the protection stack and
re-implement the derivation so it reproduces every captured input/output pair
byte-exact offline — no device, no app at verification time.

## Defense surface

- Control-flow flattening over the validation dispatcher
- Self-modifying code (a stub that decrypts its own body at runtime)
- Anti-hook, anti-emulation, and anti-dump checks
- Constants encrypted at rest, materialized only inside the routine
- A decoy computation lane that produces plausible-but-wrong outputs

## Agent route

1. Static triage of the `.so`: ELF structure, stripped symbols, section and
   import scan.
2. Control-flow recovery over the flattened dispatcher to isolate the
   validation routine from packing scaffolding.
3. Location of the self-modifying stub and the constant-decrypt path;
   derivation of the decrypted bodies without executing on the host.
4. Decoy discrimination: byte-level divergence probes between the two
   computation lanes until the true derivation is separable from the decoy.
5. Recovery of the three parameters — the ChaCha-KDF sigma word, the
   AES-shaped S-box seed, and the 16-byte license magic.
6. Offline re-implementation of the derivation over the recovered material.
7. Replay verification: the re-implementation was run against every captured
   pair, **including pairs captured on the decoy path**, which must
   reproduce as the wrong-answer baseline they are.
8. Convergence was unattended; worker deaths mid-run were detected and their
   claims re-queued by the loop without human intervention.

## Verdict

The official checker passed the run: **3/3 constants recovered, 18/18
byte-exact replays** — the 18 including the decoy-path outputs, graded as
correctly-reproduced decoys rather than mistaken for the true lane.

## What this demonstrates

Unattended multi-hour depth on a heavily layered native target, decoy
discrimination under encrypted constants and self-modifying code, and
byte-exact convergence enforced by a mechanical oracle rather than
self-assessment.
