# issue-678-reward-source — design decisions

## D-678.1 — the deliverable-citation producer (T2)

**Decision.** `cited_ids_from_deliverables(ws)` scans `notes/`,
`analyses/`, and `runs/deliverables/` (recursive, text/yaml suffixes,
`errors="replace"` reads) for `\bF\d{3}\b` tokens. `fact_artifacts`
calls it when `cited_ids is None` — the default every production
caller uses; an explicit set keeps its exact old meaning (`set()` means
"no citations", not "scan"). The citation match is exact-id first
(explicit callers may pass slugged ids), then the artifact id's own
bare `F<NNN>` token: the fact grammar mandates `<FNNN>-<slug>` ids
while deliverables name the bare token, and `\b` treats the hyphen
separator as non-word — so the scan yields exactly the bare ids.

**Rejected.** (a) *Drop the deliverable leg, rely on `claim_id`* — the
claim-provenance leg cannot see verification work (red-team facts
answer no primary question), which is exactly the class that banked
0.01-then-0.99-failure live. (b) *Exact-id membership only* — breaks
against the mandatory slugged fact-id grammar; every real fact would
need the slug repeated in the deliverable. (c) *Scan `evidence/`* —
raw evidence artifacts are worker scratch, not deliverable text; the
citation relation means "named by work that ships".

## D-678.2 — the creator backfill source (T3)

**Decision.** The backfill attributes a creator-less artifact to its
`claim_id` when that claim is a dispatch of the CURRENT settlement
(the CLI assembles dispatch rows from terminal claims, so claim id ==
dispatch id by construction). Unmatched artifacts are explicitly
marked `creditable: false`. The backfill runs in the ws-level
`settle_round_credit` (and the CLI dry-run, so the grade matches what
a real pass would settle); the pure `round_credit` core stays pure.

**Rejected.** *Launch stashes (`runs/dispatch-launch-*.json`) as the
attribution source* — `append_transition` consumes the stash on
settle, so the namespace is empty exactly when the pre-#648 facts need
backfilling; the stash's `claim` field carries the same identity the
register keeps durably. *Mutating artifact dicts in place* — forbidden
by the immutability rule; backfill returns new dicts, and rows with a
creator pass through unchanged (byte-identical rows for existing
workspaces).

## D-678.3 — producer wiring default (T2/T3 interaction)

**Decision.** `cited_ids=None` means "invoke the producer"; explicit
sets bypass it. Backfilled creators and produced citations compose:
a backfilled, deliverable-cited, certified fact settles FULL; a
backfilled uncited fact settles the TRACE exploration option (class
demotion, unchanged ladder).

**Rejected.** *A new `settle_round_credit` parameter for cited ids* —
the leg already has a parameter shape; the defect was only that
nothing filled it.

## D-678.4 — TRACE credit policy (recommended: both legs)

Options:
(a) **credit < TRACE_CEIL doesn't enter Beta** — the fold treats the
    `(0, 0.05]` band as observation-only: no success, no failure mass.
    The observation stays in the append-only log and in the decay/
    schedule chain; a genuine 0.0 still trains failure.
(b) **verification claims get the citation leg** — deliverable
    citations (D-678.1) give red-team/verification facts
    (`answers_question=None`) a full-credit path instead of the TRACE
    information option.
(c) **both — CHOSEN.** (a) alone would leave verification work
    earning only a non-informative non-observation forever; (b) alone
    leaves every historic 0.01 settlement banking 0.99 failure mass
    retroactively (the fold is a read face — the fix heals old logs).
    Together: verification work that ships earns FULL (100x above the
    TRACE band, anti-farming differential preserved); work that earns
    only the information option stops poisoning the posterior.

The band keys on the SETTLED credit, never the tiebroken one:
`phi_delta` refines admissible rows, it never promotes an information
option into a verdict.

**Rejected.** *Bank TRACE as success mass* — inverts the ladder's
meaning and farms the cap. *Raise TRACE canonical* — the 100x
differential is the anti-farming structure (#438).

## D-678.5 — Φ non-degeneracy (graded fact weights)

**Decision.** `fact_face` grows `weighted_fraction` beside the
byte-identical `count`/`verified` pair:

| rung | weight | admission |
|------|--------|-----------|
| certified terminal | 1.0 | grammar-clean + PROVEN/VERIFIED register-backed (#651 gate) |
| substantive non-terminal | 0.5 | grammar-clean INFERRED / STAMP / NEGATIVE / REFUTED |
| draft | 0.25 | grammar-clean OPEN / DEFERRED |
| absent | 0.0 | junk, malformed, unknown status, premature terminal |

Only GRAMMAR-CLEAN facts (certification_scan) carry any graded weight:
the grammar is the admission ticket for every rung, so the #651 farm
wall holds — a junk file or premature `status: VERIFIED` still lifts
Φ by exactly 0.0 (the farming-chain pin stays green). `potential()`
reads the graded fraction for its facts term; `append_transition`
records `phi_delta = s' − φ` explicitly plus `claim_ref`/`action_key`
from the launch stash. The oracle dimension is armed separately (T5):
`cases_armed` + the warn make the silent gap visible; graded facts
alone already break the {0,1} degeneracy.

**Rejected.** *"Just lower the W_FACTS threshold" / widen the weights
to junk* — does not fix the oracle silence and re-opens the #651
farming gradient (junk lifting Φ mid-episode does NOT cancel in ΔΦ).
*Changing `v_anchor` or the `fv=` signature dim* — the Q-table keys
must not re-key; only Φ grades (the signature pair stays binary).
*Deriving phi_delta at read time only* — the transition row is the
birth certificate (#539 doctrine); the column rides the row.

## Residuals (named)

- A worker that writes grammar-clean INFERRED facts farms +0.5 Φ each
  mid-episode (ΔΦ does not cancel growing weight). Bounded by the
  grammar gate + per-dispatch effort; the #652 mechanical-independence
  domain owns content truthfulness.
- Launch-stash attribution for facts whose claim is NOT in the
  settlement set stays untraced (creditable: false) — correct for the
  current pass; a future cross-claim attribution needs the durable
  dispatch registry, not the consumed stash.
