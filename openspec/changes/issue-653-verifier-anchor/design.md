# design — issue-653-verifier-anchor

## The ruling, operationalized

Hybrid (re-run + independent derivation) lands as TWO mechanical faces
and one pin, all inside the engine's verify path — no agent surface
changes (there is no kunglao-verifier.md; the dispatch prompt IS the
contract carrier).

### D1 — the receipt is the attestation, the stamp is the binding

The engine cannot re-execute worker-side commands (side effects), so
the re-run receipt (`re-run:`/`rc:`/`out-sha:`) is the verifier's own
attestation of its observation. What makes it mechanical rather than
narrative: the landing gate refuses a `verified` verdict that carries
no well-formed receipt, so "trusted the maker's recorded output" can no
longer produce a banked verification. The receipt rides the note that
already carries the verify-stamp (the 4-L4/5-F5 writer binding), so
receipts are attributable to the act. The out-sha also gives the audit
trail a stable handle beside the pinned replay artifact.

### D2 — refusal semantics: honest absence, not a new verdict class

A refused note banks 0.0 (verdict settles as absent — the exact
semantics a missing note already has), prediction settlement is skipped
(a malformed note must not fire discriminator containment), and the
promotion attempt is replaced by a recorded refusal (the detail trail
names the gate, so the loop sees WHY nothing promoted). Fail-open on
engine read errors — the existing missing-note path is untouched.

### D3 — the parser is tolerant in shape, strict in content

Receipt matching tolerates surrounding whitespace and order-insensitive
neighbors but requires all three lines adjacent-ish (command line,
then rc, then out-sha), integer rc, and 64 hex chars of out-sha. A
`refuted` verdict is exempt: refutations bank no success credit, so
there is nothing to farm; demanding receipts there would only tax
honest refutations.

### D4 — the prompt body becomes a pure builder

`_verifier_dispatch_text(claim, stamp, timeout_s)` returns the whole
V-prompt body; `_run_verifier_act` writes it. Tests pin the contract
lines and the sibling-free property (exactly the target claim id,
no other claim ids) without constructing a RunContext.

## Residuals (named, not solved)

- The orchestrator-narration channel: sibling-verification narrative
  can still reach a verify act through strategy briefs / turn-exit
  guidance (the compose anti-hint feed). Engine-side, the V prompt is
  sibling-free and pinned; the narration channel is a compose-face
  policy question.
- A verifier that fabricates receipts wholesale is the red-team trust
  class (same named class as the oracle-status face) — the receipts
  bind to the act's stamp and the out-shas sit beside the pinned
  replay artifact for the audit.
