# Design — fail-closed-verification-gates (#78)

## Design Decisions

### D1. Gate classification: `required_for_terminal_state` vs advisory

A gate is **required for terminal state** when its check protects a terminal
promotion (`PROVEN` / `VERIFIED`) — its verdict is part of what makes the
terminal state *mean* verified. Unavailability of a required gate makes the
terminal promotion unverifiable → fail closed. Classification:

| Gate | Class | Because |
|---|---|---|
| `blind_gate.check_proven_gate` (BLIND sign-off) | required_for_terminal_state | PROVEN without independent verifier = STAMP (issue #15) |
| `fact_contradiction_gate.check_proven_contradiction` | required_for_terminal_state | same-topic CONFLICT must downgrade PROVEN (#47) |
| `blind_gate.check_inference_blind_scope` | required_for_terminal_state | inferential claims need independent static coverage (#48) |
| `disasm_constant_check.check_fact_disasm` (when `binary_path` supplied) | required_for_terminal_state | byte-exact cross-layer check (#50); caller explicitly requested it |
| L2 redteam dispatcher (orchestrator-injected) | advisory (external) | already truthfully `NOT-RUN` — model for the rest |

There are no in-scope advisory local gates; the classification constant
(`REQUIRED_FOR_TERMINAL_STATE`) is defined once in `scripts/kunglao_record.py`
and imported by the hook-side backstop so the two promotion routes cannot drift.

### D2. Unavailability semantics: preserve state + explicit non-success

All three paths share one policy: **when a required gate is unavailable
(missing module / ImportError), raises (checker exception), or receives a
corrupt required artifact, the promotion does not happen and the claim/verdict
stays in its pre-call state.**

- `claim_migrator(ws, id, PROVEN, actor)` → `(False, reason)`; register NOT
  rewritten (original status preserved); no ledger `claim_promoted` event.
  Reason carries the audit receipt: gate name, error class, detail.
- `verify(...)` with `binary_path` and unavailable disasm checker → the
  `disasm` key is `{"ok": false, "state": "UNVERIFIED-WITH-GAP" | "SKIPPED",
  "checker": ..., "error_class": ..., "reason": ...}`; `overall` becomes
  `UNVERIFIED-WITH-GAP` unless it is already `REJECTED` (already non-passing —
  keep the stronger verdict). `disasm.ok` is NEVER true when the check did not
  run.
- hook `compare_register_change_proven_gate` → `(False, reason)` so the
  Write/Edit that would flip a claim to PROVEN is blocked; the register on
  disk is not modified by the hook itself (the tool call is refused).

Why `UNVERIFIED-WITH-GAP` rather than a new bespoke word: the term already
exists in the L2 verdict vocabulary (`L2_VERDICTS`) and in the redteam agent's
verdict set — it means "could not be verified because something required is
missing," which is exactly the disasm-gate situation. Adding it to the
`overall` enum is a one-line schema delta, and existing consumers of
`VERIFIED`/`REJECTED`/`PARTIAL` are unaffected.

### D3. Audit receipt shape (checker name/version, error class, reason)

Every fail-closed occurrence records a structured receipt so the orchestrator
can distinguish "gate said no" from "gate could not run":

```json
{
  "gate": "blind_gate",
  "checker": "blind_gate",
  "checker_version": "unknown",
  "error_class": "ImportError",
  "reason": "no module named 'blind_gate' ..."
}
```

`checker_version` is `unknown` when the module is not importable (the module
could not be introspected) — for the disasm gate the checker module may expose
no `__version__`, so `getattr(mod, '__version__', 'unknown')`. In
`claim_migrator` the receipt is embedded in the returned reason string
(space-delimited `gate=... error_class=... reason=...`), because the
`tuple[bool, str]` return contract is frozen (`specs/phase-5/contract.md` L79)
and shared by the CLI and existing tests; the verify path carries it as a dict
inside `out["disasm"]`.

### D4. Hook backstop: unreadable register fails closed only when a
before-snapshot exists

`compare_register_change_proven_gate(before, ...)`: if `before is None` the
hook was not armed for this write (no PreToolUse snapshot) — it returns
`'no-before snapshot'` (cannot detect anything, must not block every write).
If `before` exists but the post-write register is unreadable (`after is None`),
a promotion may have been written and cannot be checked → fail closed
(`(False, 'register unreadable ...')`). If `after` is readable and no claim
became PROVEN → pass through unchanged.

### D5. Hook backstop: gate imports required, one import point

The hook currently imports `blind_gate` in a try/except and treats the
contradiction/inference gates as optional (`have_contradiction_gate` /
`have_inference_gate` flags). For the backstop to be equivalent to
`claim_migrator` (else the direct-edit route is weaker than the formal route),
all three gates become required: if any of the three imports fails and there
IS a newly-PROVEN claim, the promotion is blocked with the failing gate's
receipt. The optional-flag pattern is removed.

### D6. Rejected alternatives

- **R1. Keep fail-open but log loudly** — rejected: logging is not a gate;
  the issue's own reproduction shows the current code logs nothing and returns
  `(True, ...)`.
- **R2. Change `claim_migrator` return to a tri-state object** — rejected:
  `tuple[bool, str]` is a frozen phase-5 contract consumed by the CLI and
  several test suites; embedding the state word (`BLOCKED`) in the reason
  string preserves the contract while making the state explicit and greppable.
- **R3. Add a new `overall` state like `CHECKER-UNAVAILABLE`** — rejected:
  `UNVERIFIED-WITH-GAP` already exists in the L2 vocabulary and says the same
  thing; a bespoke word would force schema + consumer changes for no new
  information.
