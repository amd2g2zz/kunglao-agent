# fix-98-maker-checker-deadlock (#98, D6/F15)

## What
Distinguish ImportError (gate module broken / code incomplete) from runtime
verifier unavailability (subagent timeout / resource limits) in the
fail-closed verification gates. ImportError-level failures retain FAIL_CLOSED
(blocking); runtime verifier failures allow guardrails SS1b self_caveat
degradation to STAMP (not PROVEN, not blocked).

Three promotion paths are affected:
1. `claim_migrator` (`scripts/kunglao_record.py` L218-254): three gate blocks
   catch `except Exception` uniformly, returning `(False, BLOCKED receipt)` for
   both ImportError and runtime errors. Runtime errors should degrade to STAMP.
2. `compare_register_change_proven_gate` (`hooks/worker_budget.py` L403-486):
   three import blocks + one execution block all catch `except Exception` and
   return `(False, fail closed)`. Execution-block runtime errors should degrade.
3. `blind_gate.check_proven_gate` (`scripts/blind_gate.py`): no awareness of
   `self_caveat` fact marker; should recognize it and return (False, STAMP).

## Why
Guardrails SS1b permits a worker to write `self_caveat: "unverified - needs
verifier pass"` with `verify_status: pending` when the verifier subagent is
genuinely unavailable (budget cap, infra down). The current three FAIL_CLOSED
gates treat ALL exceptions identically: ImportError and RuntimeError both produce
a BLOCKED receipt that prevents any status change. This creates a deadlock:
verifier unavailable -> gate raises runtime error -> claim BLOCKED (cannot
become PROVEN) -> worker cannot self_caveat -> verifier keeps timing out ->
repeat.

The deadlock blocks convergence without any code defect: the gate modules are
present and importable (code is complete), but the verifier subagent that
would produce the `verifier_sign_off` block cannot be dispatched.

## Scope
- `scripts/kunglao_record.py` `claim_migrator`: split `except Exception` into
  `except ImportError` (BLOCKED) + `except Exception` (degrade to STAMP) for
  all three gate blocks (BLIND, contradiction, inference).
- `hooks/worker_budget.py` `compare_register_change_proven_gate`: execution block
  (L460-482) splits `except Exception` into `except ImportError` (fail closed)
  + `except Exception` (add violation for STAMP downgrade, not hard block).
  Import blocks (L434-455) remain FAIL_CLOSED (ImportError = code incomplete).
- `scripts/blind_gate.py` `check_proven_gate`: recognize `self_caveat` in fact
  frontmatter, return `(False, STAMP, self_caveat reason)` for explicit audit.
- `scripts/blind_gate.py` `check_inference_blind_scope`: same self_caveat
  recognition for consistency.
- NOT touched: `scripts/kunglao_verify.py` (already has correct degradation via
  UNVERIFIED-WITH-GAP, #78 pattern), `scripts/fact_contradiction_gate.py`
  (read-only checker, caller handles degradation).

## Acceptance
- When gate import fails (ImportError): BLOCKED receipt, register unchanged
  (existing FAIL_CLOSED behavior preserved).
- When gate import succeeds but gate function raises (RuntimeError, timeout,
  etc.): claim migrates to STAMP with self_caveat note, register updated,
  migration succeeds (not BLOCKED).
- Hook backstop: ImportError in import block -> block; runtime error in
  execution block -> violation (STAMP downgrade), not hard infrastructure fail.
- `self_caveat` in fact frontmatter -> `check_proven_gate` returns (False, STAMP)
  with self_caveat reason; claim NOT PROVEN.
- Self-stamp guard still enforced (verifier_id != worker_id).
- Existing tests: 716 passed, 2 pre-existing failures unchanged.
- `openspec validate fix-98-maker-checker-deadlock` PASS.
