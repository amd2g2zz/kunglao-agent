# design — issue-667-step-experience-ledger

## D1 — hash-only rows are the trust boundary

A step row carries: schema, ts, session_id, call_id, tool, input_sha,
output_sha, reads[], writes[], duration_ms. Every content-bearing field
is a sha256 of the canonical JSON (or of the file bytes for path-typed
reads/writes — the path itself rides as its own sha, so even FILE NAMES
stay hashed). The builder whitelists keys: anything else in the payload
is dropped before the append. This is what makes the ledger safe to
keep forever: it cannot leak sample data, prompts, or outputs.

## D2 — the escrow state machine is enforced at the amendment boundary

`amend` validates against the item's current state:
escrow → (confirm | revoke | expire); confirm requires `certified: true`
on the item (the fact-certification verdict) — an uncertified item
escrows and can only expire; revoke references the item's producing
step (the amendment names the evidence id, and the credit walks back to
the STEP that produced the evidence — the verifier act that confirmed
is never the revoke target); expire ages pending items out at the TTL.
Refusals are None + ONE warn (the house fail-open posture), never a
raise into the caller.

## D3 — replay is a pure function because event time rides the events

Wall-clock timestamps are the replay killer, so the ledgers carry the
EVENT's ts (the hook stamps the step at capture; the evidence item and
its amendments inherit the step's ts chain). `replay_credit_ledger(ws)`
re-derives the amendment stream from the evidence items (escrow per
item; confirm iff certified) and returns the exact bytes — the recorded
file for a session with no operator actions. Determinism test: the same
session recorded twice into two workspaces yields byte-identical
ledgers.

## D4 — the hook is the shadow capture face

`hooks/step_record_capture.py` on PostToolUse
(Bash|Read|Glob|Grep|Edit|Write|MultiEdit|mcp__*): resolve the
workspace (the cost-input-capture pattern), build the hash-only row,
append, exit 0 always. PostToolUse exposes no wall duration — the
schema keeps `duration_ms: null` on the hook path (the field exists for
the runner-side face that does know durations). MCP tools ride the
`mcp__` matcher prefix verbatim.

## D5 — three registrations, one validate

The three schemas register as three spec deltas under the change;
`openspec validate issue-667-step-experience-ledger` exits 0 (the
three-registrations discipline). The schemas are the v0.2 controller's
contract — the consumption side reads exactly these shapes.
