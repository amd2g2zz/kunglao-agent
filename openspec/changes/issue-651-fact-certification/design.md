# design — issue-651-fact-certification

## The certification anchor: the register, not the frontmatter

Three anchor options were on the card: a lint tie-in, status
provenance, or a verification-record binding. The ruling: **status
provenance via the register** — a terminal fact status counts only when
every claim the fact cites is PROVEN in the claim register.

Why the register is the right anchor:

- it is engine-mediated end to end: `register_proven_gate` owns
  promotion, ws_yaml is the single writer, the claims-count
  monotonicity wall refuses wipes, and the promotion write-back sync is
  the only sanctioned writer of terminal fact statuses;
- the farmable shape is precisely the PREMATURE self-declared terminal
  status (junk files with `status: VERIFIED` at settle time, before any
  promotion). Potential-based shaping (Ng/Harada/Russell) cancels STATIC
  inflation inside ΔΦ, so post-promotion junk inflation cannot mint
  reward either — only the premature lift was farmable, and
  register-backing refuses exactly that;
- a verification-record binding (per-fact verify-note link) is deferred:
  it becomes meaningful only now that the verifier contract carries the
  re-run receipts (the #653 ruling) — recorded as the follow-up option.

## The two consumption sites, one gate

The gate lives ONCE in `lint_facts.certification_defects` (the fact
grammar's single source) and both consumers call it:

- `rlvr.state.fact_face` — the Φ/state face: `verified` counts only
  certified terminal facts. The register is read once per call; the
  gate runs per terminal-status fact (non-terminal facts never reach
  it).
- `e2e.checkpoints._facts_citing` — the settlement-credit signal:
  exact frontmatter citation (`collect_claim_refs` contains the claim —
  the substring scan over the first 2000 chars is retired), grammar
  clean, fabricated terminal excluded.

## Deliberate semantics

- `count` (fact presence) is unchanged — every fact file counts toward
  presence; the certification only gates the VERIFIED share. Lint owns
  loudness (the state.py precedent).
- At settle time the claim under settlement is typically not yet PROVEN,
  so an honest citing fact with a non-terminal status still counts
  toward `facts_citing`; what is excluded is the fabricated-terminal
  shape and the grammar-broken shape. The facts credit thereby prices
  well-formed citing facts, not prose mentions.
- Fail-open everywhere: an unreadable register = empty proven set (all
  terminal statuses uncertified — fail-closed on the reward side, which
  is the honest direction), an unparsable fact counts toward presence
  only.

## Test surface

Unit: the certification gate (grammar defects, register-backing,
claim-less terminals), `fact_face` semantics, `_facts_citing` exact
citation vs body mention. Chain: the two-junk-files farm driven through
the real settle path — credit equals the no-facts baseline, the store
row carries `facts_citing: 0`, and the posterior observation is
identical to the no-facts run.
