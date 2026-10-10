# issue-653-verifier-anchor — the verify-stage contract ruling + its mechanical face

## Why

Issue #653 (from #601's finding 5-F1): the V-dispatch hands the verifier
the maker's own fact files and instructs it to "read the claim's facts",
so a maker who plants a wrong reproduce script with a matching wrong
recorded output gets its error faithfully re-derived and confirmed.
Nothing mechanically distinguishes "re-ran it myself" from "trusted the
maker's recorded output". The card's deliverable is a ruling first, then
implementation.

## Ruling

**Hybrid: re-run + independent derivation** (recorded 2026-10-11 under
the /goal directive; the owner may override on the issue). The verifier
keeps reading the maker's facts for ORIENTATION, but every reproduce
command its verdict relies on must be RE-RUN by the verifier itself,
and the note must carry a machine-checkable receipt per command. The
engine validates the receipts at landing: a `verdict: verified` note
without at least one well-formed receipt is refused as a verification
(no verify credit, no prediction settlement, no promotion attempt).
Full independent re-derivation (option B) and replay-only hardening
(option C) were staged on the issue and rejected for cost and for
leaving the hole, respectively.

## What Changes

1. **The re-run receipt contract** (`scripts/e2e/checkpoints.py`): the
   V-dispatch prompt mandates, for every command the verdict relies
   on, a three-line receipt block (`re-run: <command>` / `rc:
   <integer>` / `out-sha: <sha256 hex of the observed output>`) and
   states the distrust rule ("never copy outputs recorded in fact
   files"). The prompt body is extracted into a pure builder so tests
   pin it.
2. **The landing gate** (`_verify_note_receipts`): a `verdict:
   verified` note must carry at least one well-formed receipt block;
   malformed (bad rc/out-sha shape) counts as absent. `refuted` is
   exempt (it banks no success credit). On refusal: ONE warn, the
   verdict settles as absent (0.0 credit), prediction settlement is
   skipped (a malformed note must not settle discriminators), and the
   promotion attempt is replaced by a recorded refusal reason.
3. **Sibling-free V-dispatch pin**: the engine-built V prompt
   references exactly the target claim and no sibling claim ids; the
   orchestrator-narration channel (strategy briefs) is documented as
   the named residual channel outside engine control.

## Out of scope

- Engine re-execution of the receipt commands (side effects; the
  receipt is the verifier's own attestation, bound to the act via the
  verify-stamp).
- The evidence/ carrier question (maker-writable ground truth) —
  #652's mechanical-independence domain.
- Blocking strategy-card briefs for verify acts (the anti-hint feed is
  the compose face's policy; recorded as residual).
