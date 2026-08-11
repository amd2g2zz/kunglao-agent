# Design — inference-claim-blind-scope (#48)

## Design Decisions

### D1. Inferential claim = statement ∪ fact-text pattern match

`is_inferential_claim(statement, fact_text) -> bool` matches inferential/routing/causal keywords against the claim `statement:` (from claim-register.yaml) AND the fact text (first 4000 chars, mirroring `find_fact_file`'s scan window). Patterns (case-insensitive):

```
INFERENTIAL_PATTERNS = [
    r"routing", r"\broute\b", r"not on .* path", r"not on path",
    r"correction", r"corrects F-?\d+", r"\bgate\b",
    r"\b0 hits\b", r"\b0 occurrences\b",
]
```

`0 hits`/`0 occurrences` count as inferential ONLY as path evidence — mechanically, any `0 hits` occurrence in a routing-shaped sentence. We do not parse sentence structure; the pattern list is the mechanical contract (issue keywords verbatim).

### D2. Sign-off coverage = static-evidence markers, orchestrator-captured ban

`verifier_sign_off` evidence is the concatenation of its `evidence_path`, `refute_attempt`, and `finding` fields. Coverage rules in order:

1. Evidence text containing `orchestrator-captured` (or `orchestrator captured`) → **fail** (not independent; RED1).
2. Evidence text containing ≥1 static marker (`xref`, `disasm`, `decompile`, `capstone`, `ghidra`, `ida`, `call graph`, `callsite`) → **pass** (RED2).
3. Otherwise → **fail** with "byte-anchor sign-off insufficient for inferential claim" (F040's 13/13 strings-count sign-off).

### D3. Environmental negative evidence (special rule)

`_has_zero_hits(fact_text)` matches `0 hits`/`0 occurrences`. `_has_env_fault(fact_text)` matches `stalled`, `never reconnected`, `未触发`, `timeout`, `reconnect`. When BOTH hold, the failure reason is explicitly the environmental-evidence reason ("environmental negative evidence cannot establish routing; require independent static xref") instead of the generic coverage message — the mechanical gate names the a2b5e25c failure mode (RED4). The static-marker requirement is the same (D2.2); only the diagnostic differs.

### D4. check_inference_blind_scope signature (mirrors check_proven_gate)

```python
def check_inference_blind_scope(claim_id, facts_dir, register_text, worker_id=None) -> (allowed, effective, reason)
```

- `register_text` is the claim-register.yaml text (already read by both wire points: `claim_migrator` holds it as `register`; `compare_register_change_proven_gate` as `register_text`).
- Check order (as built, confirmed in GREEN): fact exists → **inferential short-circuit** → signoff exists → self-stamp (worker_id == verifier_id) → REFUTE verdict → orchestrator-captured → static markers → env-fault diagnostic.
- The inferential short-circuit runs BEFORE the signoff checks: a non-inferential claim → `(True, "PROVEN", "non-inferential...")` immediately (RED3 — its fixture has no sign-off block). This is safe because the BLIND gate (`check_proven_gate`) always runs first at both wire points and enforces sign-off existence for those claims; this gate only owns inference coverage.
- All failure reasons carry uppercase `INFERENCE` (tests assert it).

### D5. Wire points (composition with #47)

1. `claim_migrator` PROVEN branch — third gate, after BLIND + CONFLICT. Each failure sets `effective_status = STAMP` and appends its own `[INFERENCE GATE: ...]` tag.
2. `compare_register_change_proven_gate` — third backstop check per newly-PROVEN claim; reuses the `register_text` already read at the top of the function; imports via the existing `sys.path.insert(_SKILL_ROOT/'scripts')` + try/except fail-open.

### D6. Sign-off schema extension (optional field)

`verifier_sign_off` MAY carry `evidence_path:` (verifier's own evidence artifact). `_validate_fields` does not require it (backward compat); the coverage test reads it when present. No BREAKING change to existing sign-offs; only inferential claims with inadequate coverage newly downgrade (that is the intent — a2b5e25c F040 would have been caught).

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/blind_gate.py` | UPDATE | `is_inferential_claim`, `_has_zero_hits`, `_has_env_fault`, `_signoff_evidence_text`, `_claim_statement`, `check_inference_blind_scope` |
| `scripts/kunglao_record.py` | UPDATE | `claim_migrator` PROVEN branch: inference gate → STAMP (~10 lines) |
| `hooks/worker_budget.py` | UPDATE | `compare_register_change_proven_gate`: inference backstop (~10 lines) |
| `tests/test_inference_blind_scope.py` | CREATE | RED1-RED4 + F040 backtest + edges |
| `references/schema.md` | UPDATE | verifier_sign_off inference-coverage convention |

## Out of scope

- Auto-healing: the gate does not rewrite sign-offs or fetch static evidence itself (verifier re-run owns that).
- Dynamic-miss validation in general: the gate only blocks the 0-hits+env-fault → routing inference combination; ordinary dynamic evidence still passes the byte-anchor path.
- Re-running the H-C experiment or RCA work (analysis-workspace side, not this repo).
