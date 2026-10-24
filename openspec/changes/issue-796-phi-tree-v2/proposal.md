# issue-796-phi-tree-v2 — Φ rewards decisive mass on the closure hypothesis tree, not actions

## Why

Both the five-party and six-party reviews convicted the same defect: the
live Φ (`W_FACTS·graded_fraction + W_ORACLE·green`) is
**dilution-dominated** — every newly DISCOVERED fact grows the
denominator before certification grows the numerator, so discovery steps
bank `r_t < 0` (the ctf-1 audit: 783 transitions, 8 distinct Φ values,
monotone decline after row 8). Exploration is punished; churn is
profitable (a supersede never claws back the credit the overturned claim
already settled). #760's pricing face prices "should this act run";
nothing prices "how much closure did the finished act buy".

## What Changes

1. **NEW `scripts/rlvr/phi_tree.py`** — the Φ-tree economy face:
   - `tree_phi(ws)` — Φ over the closure hypothesis tree (#528 layer):
     only DECISIVELY-resolved nodes carry mass
     (posterior × trunk-depth weight), chain multiplier INSIDE Φ
     (adjacent resolved trunk nodes settle superlinear — ML
     pre-condition: a Φ-term, never an additive settlement bonus);
     normalization saturates at `PHI_NORM`. Uniform birth mass: an
     unresolved node carries ZERO Φ mass — discovery can never dilute
     (the addendum's dilution ban); only resolution/refutation moves
     existing node mass.
   - `decisive()` gate — resolution credit requires a MACHINE witness
     or an independent referee confirmation; worker-authored
     refutations never settle decisive-resolution (straw-man farming
     patch). Assertion-only flips settle NEUTRAL.
   - `settle_resolution` — the `hypothesis/decisive-resolution`
     settlement writer: every credited row carries BOTH the ΔΦ
     valuation AND the proposing-step attribution ref (rows missing
     either are invalid); ΔΦ below the rule threshold records with
     zero credit (machine-recorded, never an opinion). Credit is
     ESCROWED until the claim's terminal state releases it (clawback
     timing-evasion patch: no warm-pool propagation inside the window).
   - `clawback` — overturning a credited node revokes its credit
     against the proposing step: only executable against an escrowed
     attribution ref (no ref ⇒ the original credit could not have
     settled — refuse loudly), amount = escrowed credit + documented
     churn penalty, emitted to the SIGNED negative ledger face
     (`phi-clawback/1`, sealed) — never folded into the non-negative
     credit stream (E-30 structural verdict) — and MIRRORED into the
     shared strategy store (censored, negative phi_delta; the
     cross-workspace laundering patch).
   - `elimination_credit` — a well-formed failed attempt eliminates a
     live candidate for small saturating credit (scenario 2 monotone;
     same decisive gate — farming planted candidates pays nothing).
   - `reconcile_claim` — on the claim's terminal close, the
     proxy-vs-truth calibration pass records `(ΔΦ, attribution, oracle
     outcome)` triples and releases the claim's escrows.
2. **`scripts/hypothesis_store.py` schema v2** — tree edges
   (`parent_id`), `posterior`, `critical_path` flag, decisive-evidence
   fields (`resolved_evidence`/`resolved_ref`), and the attribution ref
   (`resolved_step_ref`) per resolved node. v1 files parse unchanged
   (additive fields, defaults honest-absent).
3. **`scripts/rlvr/incremental_reward.py` Φ swap** — `potential()` drops
   the dilution-dominated facts term and reads the tree Φ as its
   progress dim (oracle dim unchanged, still #799-seal-gated);
   potential-based property preserved (Ng 1999 — optimal-policy order
   safe). Every transition row stamps `phi_regime` (Φ formula version —
   ML pre-condition 2: the ledger survives a Φ swap uncorrupted).
4. **`references/contracts/reward-rules.yaml` v4** — rule classes
   `hypothesis/decisive-resolution` (ΔΦ ≥ threshold WITH mechanical
   witness) and `hypothesis/churn` (the clawback band), plus the
   valuation+attribution pairing contract on every resolution row.
5. **L9 fold-in** — `refutation_fold.record_verify_outcome` marks
   absorbed-at-kill rows `censored` (the caller passes the
   absorbed-from-disk marker through): a kill-banked verdict never
   propagates to the shared store as clean cross-workspace evidence.

## Constraints honored

- #799: every economy read/write goes through the seal's gate — rows
  are signed at write (`sign_row`), learners read `trusted_rows`.
- #760: complementary, not overlapping — pricing computes whether an
  act should run; Φ-tree prices what the finished act bought. No new
  pricing table, no dispatch-gate changes.
- #797: the learning key stays the family-granularity frozen key; no
  new key face.
- Untouched: ranker core (#792), settlement_scorer/settlement_wire
  (#802), supply face (#794), claims_store/scalar semantics (called,
  never modified). Synthetic fixtures only — no production log enters
  the repo.

## Impact

- commits: feat: Φ-tree v2 — reward decisive mass on the closure
  hypothesis tree (issue 796)
- tests: tests/test_phi_tree_796.py — the acceptance anchor is the
  three-scenario replay E2E (the reward vector must rank
  scenario 3 > scenario 2 > scenario 1), plus the panel pre-conditions
  and adversarial patches as pins.
