# Spec - maker-checker-deadlock (#98)

## Requirements

### REQ-1: ImportError-level failures remain FAIL_CLOSED

When a gate module cannot be imported (ImportError, ModuleNotFoundError, or
any exception during import), the promotion is BLOCKED with an audit receipt.
The register is not modified. This preserves the #78 fail-closed invariant:
code must be complete for any terminal promotion.

Applies to:
- `claim_migrator` three gate import blocks
- `compare_register_change_proven_gate` three gate import blocks

### REQ-2: Runtime gate errors degrade to STAMP

When a gate module imports successfully but the gate function raises a
non-ImportError exception during execution, the promotion degrades to STAMP
(instead of being BLOCKED). The register IS updated with STAMP status.
The migration succeeds (returns `(True, ...)`).

Applies to:
- `claim_migrator` three gate execution blocks
- `compare_register_change_proven_gate` execution block

### REQ-3: blind_gate recognizes self_caveat

When a fact file's frontmatter contains `self_caveat` (non-empty string),
`check_proven_gate` returns `(False, STAMP, "self_caveat: <value>")`.
`check_inference_blind_scope` returns the same pattern. The self_caveat
check precedes sign-off extraction in the check order.

### REQ-4: Self-stamp guard preserved

`verifier_id == worker_id` remains a self-stamp rejection. self_caveat does
not bypass the self-stamp guard (a self-caveated fact with a self-signed
sign-off is still rejected).

### REQ-5: No new status values

STAMP (claimed-but-unverified) is the degraded state. No new claim statuses
are introduced.

## Scenarios

### S1. claim_migrator: ImportError -> BLOCKED (existing behavior preserved)
Given claim C-1 status OPEN
And blind_gate module is unavailable (ImportError)
When claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
Then returns (False, "BLOCKED... blind_gate...")
And register C-1 status remains OPEN
And no ledger event

### S2. claim_migrator: runtime error -> STAMP
Given claim C-1 status OPEN with valid fact file
And blind_gate imports OK but check_proven_gate raises RuntimeError
When claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
Then returns (True, "...")  [migration succeeds]
And register C-1 status is STAMP
And message contains "runtime error" or "degraded"

### S3. claim_migrator: contradiction gate runtime error -> STAMP
Given claim C-1 status OPEN with valid fact+signoff
And fact_contradiction_gate imports OK but check_proven_contradiction raises
When claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
Then returns (True, "...")
And register C-1 status is STAMP

### S4. claim_migrator: inference gate runtime error -> STAMP
Given claim C-1 status OPEN with valid fact+signoff
And check_inference_blind_scope raises RuntimeError
When claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
Then returns (True, "...")
And register C-1 status is STAMP

### S5. blind_gate: self_caveat fact -> STAMP
Given fact with frontmatter self_caveat: "unverified"
When check_proven_gate("C-1", facts_dir)
Then returns (False, STAMP, "self_caveat...")
And not (True, PROVEN)

### S6. blind_gate: self_caveat + self-stamp -> still rejected
Given fact with self_caveat AND verifier_sign_off where verifier_id == worker_id
When check_proven_gate("C-1", facts_dir, worker_id="w1")
Then returns (False, STAMP) with self-stamp reason

### S7. Hook: ImportError in import block -> block (preserved)
Given blind_gate module unavailable
And direct register edit to PROVEN
When compare_register_change_proven_gate(reg, before, agent, facts)
Then returns (False, "blind_gate unavailable...")

### S8. Hook: runtime error in execution -> violation (STAMP guidance)
Given all gates import OK
And gate function raises RuntimeError during execution
When compare_register_change_proven_gate(reg, before, agent, facts)
Then returns (False, "...Downgrade to STAMP...")
And reason does NOT contain "fail closed"

### S9. claim_migrator: valid signoff + all gates OK -> PROVEN (regression)
Given valid BLIND sign-off, all gates available
When claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
Then register C-1 status is PROVEN
