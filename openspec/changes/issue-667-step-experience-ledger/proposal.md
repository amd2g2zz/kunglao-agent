# issue-667-step-experience-ledger — the shadow telemetry substrate

## Why

Issue #667 (raised while shipping rc1): the RL's learning layer consumes
settlements and credits, but the STEP-level experience — every tool call
an agent makes, with its read/write sets — is never recorded, so the
online off-policy controller's future reward admission rule has nothing
to admit FROM. The card demands the substrate in shadow mode first:
"nothing can be learned that is not logged, and nothing logged can be
trusted as reward unless its admission rule is fixed first" — record
everything, act on nothing.

## What Changes

1. **The step ledger (`step-record/1`)** — `scripts/rlvr/step_ledger.py`
   + the shadow PostToolUse hook `hooks/step_record_capture.py` (wired
   Bash|Read|Glob|Grep|Edit|Write|MultiEdit|mcp__*): one append-only
   hash-only row per tool call (session id, call id, tool, input/output
   SHAS, duration when known). Raw content NEVER lands — the row builder
   whitelists keys and hashes everything else. Fail-open end to end.
2. **The evidence-credit ledger (`evidence-item/1` +
   `credit-amendment/1`)** — the escrow faces: an evidence item cites
   the producing step (step_ref) and carries the certification verdict
   (the fact-certification gate's output rides in as `certified`);
   amendments are the lifecycle — escrow, confirm, revoke, expire.
   THE ADMISSION RULE: a CONFIRM amendment requires a certified item;
   uncertified evidence escrows and can only expire (the farming
   scenario nets zero CONFIRMED credit). Revocation targets the
   PRODUCING step's evidence — never the verifier act.
3. **The intervention log (`intervention/1`)** — shadow-only: every
   operator/controller intervention recorded beside the steps it
   interrupted (trigger, actor, subject sha, note sha).
4. **The replay face** — `replay_credit_ledger(ws)`: the amendment
   stream for a session is a pure function of its evidence items
   (escrow per item, confirm iff certified); re-deriving it is
   byte-identical to the recorded file.

## Zero-behavior-change posture

The ledger module is recorded-only: no dispatch, gate, settlement, or
promotion face imports it (the 396 freeze-wall posture). The hook writes
only `runs/step-ledger.jsonl`; the faces write only
`runs/evidence-credit.jsonl` and `runs/interventions.jsonl`. Golden
fixtures and every decision path are untouched — the fast suite is the
pin.

## Out of scope (the v0.2 seam, recorded)

- Consuming the ledgers: the online controller's reward admission
  (scalar settlement reads), the workbench views (#320), the DESIGNED
  statusline slots — all v0.2.
- The evidence-item `certified` verdict's PRODUCTION wiring (the
  fact-certification gate computes it; the item carries it — who stamps
  items in production is the wiring card that follows this design).
