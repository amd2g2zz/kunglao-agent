# Spec — 派发协议结构化 (issue #452)

## R1: protocol v1 schema

### Requirement: v1 protocol MUST be valid JSON

```json
{"kunglao_dispatch": {
  "version": 1,
  "claim": "C-<digits>",
  "tier": 1|2|3,
  "tools": [...],         // optional, default []
  "agent": "...",          // optional
  "task": "..."            // optional
}}
```

Field validation rules:
- `version` MUST equal `1` (current `DISPATCH_PROTOCOL_VERSION`).
  Different version numbers MUST be rejected (caller falls back to v0).
- `claim` MUST match `re.fullmatch(r"C-\d+", claim_id)`. Other forms rejected.
- `tier` MUST be in {1, 2, 3}. Other values rejected.
- `tools` if missing or non-list → treated as `[]`. Non-string items coerced
  via `str()` and trimmed; empty strings dropped.

## R2: parsing precedence

### Requirement: v1 takes precedence over v0

When both `[T<N> tools=...] claim C-NN` (v0) and `{"kunglao_dispatch":{...}}`
(v1) are present in the same text, `parse_dispatch` MUST return the v1 result.

### Requirement: parse_dispatch is the single source

The dispatch protocol parser MUST live in one place (`hooks/lib_kunglao.py`).
Consumers (`hooks/dispatch_gate.py`, future `hooks/worker_pulse.py`) MUST
call `parse_dispatch`, not re-implement the regex.

## R3: parse failure signal (#452 AC)

### Requirement: dispatch_gate MUST emit visible signal on unparseable input

When neither v0 nor v1 matches the prompt, the gate MUST:
1. Write `dispatch_gate: unrecognized dispatch protocol (...)` to stderr (with `flush=True`)
2. Emit `hookSpecificOutput.additionalContext` containing `WARN` + the dispatch_protocol.md link
3. Still exit 0 (not block the orchestrator — it may fix the prompt)

### Requirement: no more silent return 0

The pre-#452 behaviour (`return 0` without any output on parse failure) is
FORBIDDEN. Test asserts `_warn_unparseable()` is called.

## R4: backward compatibility

### Requirement: v0 protocol MUST continue to work

`[T1 tools=grep] claim C-001` (v0 regex) MUST still parse correctly. The
v0 path is reached only after v1 fails (so adding v1 does not break v0 callers).

### Requirement: hooks/dispatch_gate.py DISPATCH_RE kept as backward-compat re-export

`from hooks.dispatch_gate import DISPATCH_RE` MUST continue to work for
legacy importers (e.g. `hooks/worker_pulse.py` may import it). The shared
parser in `lib_kunglao.py` is the new source of truth.

## R5: docs/dispatch_protocol.md

### Requirement: protocol MUST be documented

`docs/dispatch_protocol.md` MUST describe:
- v0 + v1 schemas
- Parsing order
- Failure-signal contract (stderr + hookSpecificOutput)
- Compatibility policy

## R6: tests

### Requirement: parse + signal contract MUST be tested

`tests/test_dispatch_protocol.py` MUST cover:
- v1 happy / version-mismatch / invalid-claim / invalid-tier / malformed
- v0 happy / partial-match / no-match
- v1 precedence over v0
- `parse_dispatch_json` returns `(0, [], None, None)` on failure
- `_warn_unparseable()` emits to stderr + hookSpecificOutput
- End-to-end: unparseable prompt → warning emitted
- End-to-end: v1 prompt → no warning