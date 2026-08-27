# Design: Hypothesis-PROVEN Fact Contradiction Annotation

## D1 — Design Goal

When `OPEN_HYPOTHESIS_AT_CLOSE` fires, the BLOCKED action message SHALL name, per open hypothesis, any PROVEN fact that contradicts it — enabling the analyst to adjudicate with a specific evidence reference instead of a generic "adjudicate before delivery" message.

## D2 — Contradiction Detection Surface

Two detection paths, applied in order:

**Path A — Explicit marker** (high-confidence): The hypothesis body explicitly names a PROVEN fact ID (pattern: `refutes H-NNN`, `F<id>`, `contradicts F<id>`, `F-<id>`). The PROVEN status of the referenced fact is verified against `facts/_INDEX.md`.

**Path B — Candidate negation heuristic** (medium-confidence): The hypothesis carries `candidates: [...]` (non-empty). A PROVEN fact exists whose conclusion text contains a direct negation of a candidate (e.g., candidate `"AES"` vs PROVEN conclusion `"uses RC4 cipher, not AES"`). This is a string-inclusion check with a small stopword list (`not`, `never`, `rather than`, `instead of`).

Both paths are fail-open: a detection error produces no annotation (the generic message fires).

## D3 — Implementation Location

`scripts/convergence_check.py`, `_act_open_hypothesis` action builder only. No new modules. No changes to `decide()`, `STAGE_PROBES`, or `TRANSITIONS`.

## D4 — _INDEX Scan Pattern

Reuse the same lightweight line-scan pattern as `_partial_facts` (convergence_check line 164-178): split `|` lines, check `parts[1].upper()` against `{"PROVEN"}`, collect `parts[0]` + `parts[3]` (id + conclusion). No schema validation library, no YAML parsing, no exceptions on malformed rows.

## D5 — Hypothesis Body Scan

For each open hypothesis: read `hyp.body` (already in memory from `s.open_hypotheses()`). Run two regex passes:
- Path A: `F[-\s]?\d+` capture → lookup in PROVEN fact set.
- Path B: for each candidate, scan PROVEN fact conclusions with negation-keyword prefix check.

## D6 — Output Format

```
Cannot CONVERGE: {n} open hypothesis(ies) {ids} — adjudicate before delivery.
  Contradicted: H-NNN by F-NNN (conclusion: <snippet>)
  ...
```

If no contradiction detected: unchanged message (generic block only).

## D7 — Fail-Open Contract

Any exception in Path A or Path B is caught, swallowed, and returns no annotation for that hypothesis. The generic message serves as the fallback. This matches the existing fail-open posture of all other DRAIN gates.

## D8 — Anchor Compatibility

Anchor test fixtures (`decide_anchor_619ebd3.json`) all have `open_hypotheses: []`. `_act_open_hypothesis` is never invoked in the anchor suite. The new annotation code path is dead code under anchor testing — zero anchor re-pin required.
