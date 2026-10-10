# issue-651-fact-certification — Φ's fact dimension priced by certified facts

## Why

Issue #651 (the #601 triage's "single biggest structural item", findings
4-L2/L3 + 5-F4's reward side): Φ's fact dimension (0.3 · verified-fraction)
counts a fact as verified iff its frontmatter `status` says PROVEN/VERIFIED
— worker-written at creation — and `_facts_citing` is a claim-id substring
scan over the first 2000 chars. Two junk files with `status: VERIFIED` farm
positive reward: `facts_citing` feeds the settlement credit, `phi_delta`
feeds the q-cell tiebreaker, the arm posterior, the cross-workspace warm
pools, and the termination floor's alive mass.

## What Changes

1. **The certification gate** (`scripts/lint_facts.py` — the fact
   grammar's single source gains `read_register_proven(ws)` and
   `certification_defects(fm, body, proven, fact_ids)`): one fact is
   CERTIFIED iff the fact grammar is clean (`lint_fact`) AND its
   terminal status (PROVEN/VERIFIED) is REGISTER-BACKED — every claim
   the fact cites (exact frontmatter citation via `collect_claim_refs`)
   is PROVEN in the claim register. Rationale: the promotion gate is the
   only sanctioned writer of register-PROVEN (ws_yaml single-writer +
   the claims-count wall), and the promotion write-back sync is the only
   sanctioned writer of terminal fact statuses; potential-based shaping
   cancels static inflation in ΔΦ, so the farmable shape is precisely
   the PREMATURE self-declared terminal status — which register-backing
   refuses.
2. **`fact_face` honors only certified terminals**
   (`scripts/rlvr/state.py`): `verified` counts facts whose terminal
   status survives the certification gate; `count` unchanged (every
   fact file counts toward presence; lint owns loudness).
3. **`_facts_citing` parses frontmatter and requires certification**
   (`scripts/e2e/checkpoints.py`): exact frontmatter citation
   (`collect_claim_refs` contains the claim — no body substring), the
   fact grammar clean, and a fabricated terminal status excludes the
   file. Malformed files count as 0 (fail-open, unchanged).

## Out of scope (named residuals)

- A forger who writes a fully grammar-clean fact with an honest
  non-terminal status citing the claim still counts toward
  `facts_citing` — frontmatter is worker-writable; truthfulness of
  non-terminal content rides the fact lint and the #652
  mechanical-independence domain.
- Engine re-verification of fact content (the verification-record
  binding option) — needs the verify-note↔fact link the anchored-
  verifier contract (#653) now makes trustworthy.
