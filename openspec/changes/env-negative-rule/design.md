# Design — env-negative-rule (#56)

## Gap assessment vs #48 (evidence)

**Method.** Read `scripts/blind_gate.py` (#48 implementation) fully and probed
four F040-shape synthetic claims against the shipped `check_inference_blind_scope`
(probe script: `$CLAUDE_JOB_DIR/tmp/probe_gap.py`; fixture claims are the issue's
documented F040 text shapes, not live data). The gate's env-fault diagnostic is
at `scripts/blind_gate.py:345-351`:

```python
if _has_zero_hits(fact_text) and _has_env_fault(fact_text):
    return (False, STAMP, "...environmental negative evidence cannot establish routing...")
```

with `_ZERO_HITS_PATTERNS = (r"\b0 hits\b", r"\b0 occurrences\b")` and
`is_inferential_claim` matching `INFERENTIAL_PATTERNS` (which includes `0 hits`
but no existence / no-call-captured vocabulary).

**Result.**

| case | shape | `is_inferential_claim` | `check_inference_blind_scope` | verdict |
|---|---|---|---|---|
| A | routing + "0 hits" + env-fault (F040 literal) | True | not-allowed, STAMP | #48 catches |
| B | existence + "0 hits" + env-fault | True | not-allowed, STAMP | #48 catches (via `0 hits` ∈ INFERENTIAL_PATTERNS) |
| C | existence + "no call captured" + env-fault | **False** | **allowed, PROVEN** | **gap — slips through as non-inferential** |
| D | "absent" + "no calls observed" + env-fault | **False** | **allowed, PROVEN** | **gap — slips through** |

**Conclusion.** #48 covers ~60-70% of #56 (the F040 *literal* routing shape and
existence-when-phrased-as-`0 hits`); the plan's "~90%" estimate was high. The
residual is a code generalization, not doc-only:

1. **G1 — basis vocabulary is narrow.** `_has_zero_hits` recognizes only
   `0 hits`/`0 occurrences`. The issue's explicit **无调用捕获** ("no call
   captured") trigger — and sibling phrasings ("no calls observed", 未触发) —
   do not fire the env-fault diagnostic even when the claim is otherwise
   inferential.
2. **G2 — NEGATIVE-existence conclusions are not inferential.** "does not
   exist" / "absent" / "not present" / 不存在 are absent from
   `INFERENTIAL_PATTERNS`, so existence claims short-circuit at the
   `is_inferential_claim` guard and never reach the env-fault diagnostic.

## Design decisions

### D1. Generalize the basis detector (G1)

Rename the intent (not the call sites) by introducing a broader predicate and
keeping the legacy name as a subset alias (so existing tests that import
`_has_zero_hits` still work — `test_inference_blind_scope.py` does not import
it, but defensive):

```python
_ENV_NEGATIVE_BASIS_PATTERNS = (
    r"\b0 hits\b", r"\b0 occurrences\b",
    r"no call captured", r"no calls observed", r"never called",
    r"无调用捕获", r"未触发",
)
def _has_env_negative_basis(text: str) -> bool: ...
# backward-compat alias (proper subset)
_has_zero_hits = _has_env_negative_basis
```

The env-fault diagnostic fires on `_has_env_negative_basis(fact_text) and
_has_env_fault(fact_text)`.

### D2. Flag NEGATIVE-existence conclusions as inferential (G2)

Add a dedicated tuple folded into the inferential check, scoped to NEGATIVE
conclusions (positive existence is NOT flagged — avoids false positives on
"Foo exists at 0x..."):

```python
_NEGATIVE_EXISTENCE_PATTERNS = (
    r"does not exist", r"\babsent\b", r"\bnot present\b",
    r"不存在", r"未发现",
)
# is_inferential_claim checks INFERENTIAL_PATTERNS + _NEGATIVE_EXISTENCE_PATTERNS
```

Conservative on purpose: `\babsent\b` (word-boundary) avoids matching
"absentee"/"quintessential" etc.; "not present" is two words; no bare "no"
or "not" patterns (those would over-flag).

False-positive audit: grep of `tests/` for the new vocabulary returned only
benign hits (Chinese docstrings, the word "absent" in one test description
string, none in claim statements or fact text) — so no existing test changes
behavior.

### D3. Generalize the rejection reason

Env-fault diagnostic reason changes from "cannot establish routing" to
"cannot establish routing or existence" so the message matches the generalized
rule. Existing #48 tests assert the reason loosely
(`test_red4_zero_hits_env_fault_downgrades` checks `"environmental" in
reason.lower() or ...`), so the wording change is backward-compatible.

### D4. No new gate, no new wire point (complementarity with #48)

The rule is implemented inside the existing `check_inference_blind_scope`. The
two wire points (`claim_migrator` PROVEN branch at
`scripts/kunglao_record.py:214`; `compare_register_change_proven_gate` at
`hooks/worker_budget.py`) are unchanged. This is the structural proof that #56
is complementary to #48, not a duplicate gate.

### D5. Doc placement

The rule is added to `references/failure-modes-monitoring.md` — F8
("Self-confident false PROVEN") is the precise sibling (false PROVEN from bad
evidence). It is recorded as a new evidence-discipline subsection under the F8
family, NOT a new F-row number (F1-F18 numbering stays stable). A one-line
pointer is added to `references/failure-modes.md`. The entry cross-references
#48 and `failure_analysis_gate.py`'s three-question mechanism.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/blind_gate.py` | UPDATE | `_ENV_NEGATIVE_BASIS_PATTERNS` + `_has_env_negative_basis`; `_NEGATIVE_EXISTENCE_PATTERNS` folded into `is_inferential_claim`; env-fault diagnostic uses the broader basis + generalized reason |
| `tests/test_env_negative_rule.py` | CREATE | F040 regression (acceptance #2) + existence/generalized-vocab cases (G1/G2 residual) + complementarity test (no-over-flag, same-gate) |
| `references/failure-modes-monitoring.md` | UPDATE | env-negative rule subsection under F8 family |
| `references/failure-modes.md` | UPDATE | one-line index pointer |

No changes to `kunglao_record.py`, `hooks/worker_budget.py`, or `schema.md`
(#48 already wired the gate; #56 only extends the gate's internal patterns).

## Out of scope

- Auto-healing / sign-off rewriting (verifier re-run owns that).
- Dynamic-miss validation in general (ordinary dynamic evidence still passes
  the byte-anchor path; only env-faulted NEGATIVE inferences are blocked).
- Negative-evidence detection beyond the dynamic/behavioral dimension (static
  "xref found nothing" is a valid NEGATIVE — the rule targets dynamic misses
  under env faults, not all NEGATIVE claims).
- Re-running the F040 RCA (analysis-workspace side, not this repo).
