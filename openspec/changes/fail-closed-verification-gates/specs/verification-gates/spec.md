# Spec Delta — fail-closed-verification-gates

## ADDED Requirements

### Requirement: Required verification gates fail closed when unavailable

A verification gate classified as `required_for_terminal_state` SHALL fail
closed: when the checker module is missing (ImportError), raises any exception,
or receives a corrupt required artifact, the guarded terminal promotion MUST
NOT be written. The claim/verdict SHALL remain in its pre-call state, and the
caller SHALL receive an explicit non-success result (`BLOCKED` /
`REJECTED` / `UNVERIFIED-WITH-GAP`) together with an audit receipt recording
checker name, error class, and reason. This policy SHALL apply identically to
`claim_migrator` (scripts/kunglao_record.py), the register-edit backstop
(hooks/worker_budget.py `compare_register_change_proven_gate`), and the
disassembly post-gate (scripts/kunglao_verify.py `verify` with
`binary_path`) so that no alternate promotion route remains fail-open.

Gates classified as `required_for_terminal_state`:

- `blind_gate.check_proven_gate` (BLIND sign-off, issue #15)
- `fact_contradiction_gate.check_proven_contradiction` (issue #47)
- `blind_gate.check_inference_blind_scope` (issue #48)
- `disasm_constant_check.check_fact_disasm` when `binary_path` is supplied
  (issue #50)

Optional observability checks MAY remain non-blocking, but their receipts MUST
use `UNKNOWN`/`SKIPPED` rather than a success value, and they MUST NOT affect
promotion.

#### Scenario: claim_migrator blocks PROVEN when blind_gate module is missing

- WHEN `claim_migrator` is called with `new_status=PROVEN` and the
  `blind_gate` module cannot be imported
- THEN it returns `(False, reason)` where reason contains `BLOCKED`, the gate
  name, and `ImportError`
- AND the claim-register status is unchanged (still the original status), AND
  no `claim_promoted` ledger event is recorded

#### Scenario: claim_migrator blocks PROVEN when a required gate raises

- WHEN the BLIND/contradiction/inference gate raises an exception (not only
  ImportError) during a PROVEN migration
- THEN the migration is refused with the same `(False, ...)` contract and the
  register is unchanged

#### Scenario: verify with unavailable disassembly checker is non-passing

- WHEN `verify(ws, fact_id, binary_path=pe)` is called and
  `disasm_constant_check` (or its capstone/pefile dependencies) cannot be
  imported
- THEN `out["disasm"]["ok"]` is `False`, the disasm receipt carries
  `state`, `checker`, `error_class` and `reason`, and `overall` is NOT
  `VERIFIED` (it is `UNVERIFIED-WITH-GAP` unless already `REJECTED`)

#### Scenario: verify records a checker exception without a passing receipt

- WHEN the disasm checker raises an exception while processing a supplied
  binary
- THEN `disasm.ok` is `False` (never `{"ok": true, "skipped": ...}`) and the
  receipt records the exception class and message

#### Scenario: direct register edit to PROVEN is blocked when blind_gate is unavailable

- WHEN `compare_register_change_proven_gate` observes a claim flipping to
  PROVEN (before-snapshot exists, post-write register readable) and the
  `blind_gate` module cannot be imported
- THEN it returns `(False, reason)` and the PROVEN promotion is refused

#### Scenario: direct register edit to PROVEN is blocked when the register is unreadable

- WHEN `compare_register_change_proven_gate` has a before-snapshot but the
  post-write register cannot be parsed
- THEN it returns `(False, reason)` (fail closed) rather than permitting the
  write

#### Scenario: available-checker paths are unchanged

- WHEN all required checkers are importable and return their verdicts normally
- THEN `claim_migrator` promotes/downgrades exactly as before (BLIND sign-off
  present → PROVEN; missing → STAMP; CONFLICT → STAMP), the hook allows
  valid PROVEN promotions, and `verify` with a binary that matches the fact
  remains `VERIFIED` with `disasm.ok=true`

### Requirement: Audit receipt contract

Every fail-closed occurrence SHALL record an audit receipt identifying the
checker. The receipt SHALL contain the checker name, the checker version
(`unknown` when the module is not importable), the error class, and the
reason. In `claim_migrator` the receipt is embedded in the returned reason
string (the `tuple[bool, str]` contract is frozen); in `verify` the receipt is
a structured dict under the `disasm` key; in the hook the receipt is embedded
in the returned reason string.

#### Scenario: verify disasm receipt is structured

- WHEN the disasm gate fails closed
- THEN `out["disasm"]` is a dict with keys `ok` (false), `state`, `checker`,
  `checker_version`, `error_class`, `reason`
