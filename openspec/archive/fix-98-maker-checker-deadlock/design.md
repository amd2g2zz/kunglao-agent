# Design - fix-98-maker-checker-deadlock (#98)

## D1. Two-tier exception classification

The fail-closed gates (#78) treat all exceptions identically. Issue #98
requires splitting exceptions into two tiers with different policies:

| Tier | Exception class | Meaning | Policy |
|------|---------------|---------|--------|
| Infrastructure | ImportError, ModuleNotFoundError | Gate module broken, missing, or unloadable; code is incomplete | FAIL_CLOSED: BLOCKED, register unchanged, audit receipt |
| Runtime | RuntimeError, TimeoutError, OSError, etc. | Gate module imported OK, but gate function raised during execution (verifier subagent timeout, resource limits, env fault) | Degrade to STAMP: register updated, self_caveat note, migration succeeds |

Key invariant: a gate that cannot even be imported means the codebase is
incomplete or broken - that MUST block. A gate that imports fine but whose
checker function fails at runtime means the verification infrastructure is
temporarily unavailable - that SHOULD degrade gracefully per guardrails SS1b.

## D2. claim_migrator degradation pattern

For each of the three gate blocks (BLIND, contradiction, inference):

```python
# Before (current #78 code):
try:
    from blind_gate import check_proven_gate, STAMP
    ...
    allowed, effective_status, gate_reason = check_proven_gate(...)
    if not allowed:
        gate_msg = ...
except Exception as exc:
    return (False, _required_gate_receipt("blind_gate", exc, claim_id))

# After (fix-98):
try:
    from blind_gate import check_proven_gate, STAMP
except Exception as exc:
    # Infrastructure failure: code incomplete -> FAIL_CLOSED
    return (False, _required_gate_receipt("blind_gate", exc, claim_id))
try:
    ...
    allowed, effective_status, gate_reason = check_proven_gate(...)
    if not allowed:
        gate_msg = ...
except Exception as exc:
    # Runtime verifier failure -> degrade to STAMP (guardrails SS1b)
    effective_status = STAMP
    gate_msg += (f" [{gate_name}: verifier runtime error "
                 f"({type(exc).__name__}: {exc}); degraded to STAMP]")
```

The import attempt is separated into its own try/except. The gate function
call gets its own try/except that degrades instead of blocking.

## D3. Hook backstop degradation

`compare_register_change_proven_gate` has two distinct exception sites:

1. **Import blocks (L434-455)**: `try: from X import Y / except Exception` -
   These remain FAIL_CLOSED. If the gate module cannot be imported, the
   code is incomplete and the PROVEN promotion must be blocked.

2. **Execution block (L460-482)**: `try: for cid in newly_proven: ... /
   except Exception` - This splits:
   - `except ImportError`: FAIL_CLOSED (should not happen at this point since
     imports succeeded above, but defensive)
   - `except Exception`: degrade - append violation for each claim in
     `newly_proven` indicating runtime degradation to STAMP, then fall
     through to the violations check which produces the "Downgrade to STAMP"
     message.

The hook cannot write STAMP itself (it only allows/blocks writes), but it
communicates the correct guidance: "runtime verifier error - use
claim_migrator for STAMP downgrade" rather than "infrastructure failure -
fix or restore and retry."

## D4. blind_gate self_caveat recognition

`check_proven_gate` reads fact frontmatter. When a fact carries:

```yaml
---
self_caveat: "unverified - needs verifier pass"
verify_status: pending
---
```

The gate returns `(False, STAMP, "self_caveat: ...")` instead of the generic
"verifier_sign_off missing" message. This provides a clearer audit trail:
the absence of sign-off is intentional (verifier was unavailable), not an
oversight.

The self_caveat check is ordered before the sign-off extraction check:
self_caveat -> no fact file -> no sign-off -> self-stamp -> REFUTE.

`check_inference_blind_scope` gets the same self_caveat recognition for
consistency.

## D5. Rejected alternatives

- **R1. Add --override flag to bypass gates** - rejected: would create a
  bypass mechanism that defeats maker-checker. Degradation is a fact-level
  marker, not a gate bypass.
- **R2. Treat all runtime errors as BLOCKED but with shorter timeout** -
  rejected: the deadlock is structural, not timing. A verifier that cannot be
  dispatched will fail regardless of timeout.
- **R3. Introduce a new status like SELF_CAVEAT_PENDING** - rejected: STAMP
  already means "claimed-but-unverified" which is exactly the self_caveat
  state. Adding a new status would require schema + consumer changes for no
  new information.
