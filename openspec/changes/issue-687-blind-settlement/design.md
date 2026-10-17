# design — issue-687-blind-settlement

## D1 — blindness is enforced at TWO points, with one exclusion list

The builder refuses excluded faces BEFORE any read (ValueError at the
door), and `check_blind_input` re-scans hand-built docs AT the
settlement (ok=False → nothing settles). The list is duplicated with
the barrier's mechanical deny faces on purpose: the hook must never
import a scripts-side module (a failed import would fail-OPEN the
barrier — blindness silently off), so the two lists are pinned against
each other by test instead of shared by import. A poison file left in
the workspace is the standing proof: fixtures carry sentinel strings in
every excluded face, and the tests assert no sentinel can appear in an
input doc nor be opened during a legal build (the read handle is
spied).

## D2 — identity rides the input doc, not the caller's goodwill

`settler_input` raises on empty identity; `check_blind_input` refuses a
blank identity at the settlement gate; `settle_blind` never raises —
the gate result travels as `{"settled": false, "reason": "input: ..."}`
(the settlement path keeps the loud-result/no-raise posture of the
ledger writes). The identity string itself is not cryptographically
signed in this card — it is the same binding level as dual_gate's
verifier-identity (named grader, auditable row), and key-level signing
is out of scope.

## D3 — the citation seam: the input doc vouches for its own artifacts

`validate_verdict_doc` rejects any citation outside the workspace
registry (ledger rollout ids + fact ids) — but a blind settler never
reads `facts/`, so its natural citation is the artifact path it hashed.
`apply_trajectory_settlement` gains ONE additive kwarg
(`extra_resolvable`, default empty) that unions caller-vouched ids into
the registry; `settle_blind` passes the input doc's artifact paths.
Default-empty keeps every existing call byte-identical (impact: 0
upstream dependents; the scalar 379/390 suites are the regression
wall). The hallucination wall itself is untouched: an id the input doc
never vouched for still rejects the whole verdict.

## D4 — idempotency is the ledger's dedupe, not a second mechanism

`rl.settle` refuses a settlement whose core (everything except
`settled_ts`) equals the current one over the same signals, so a re-run
—even with a different clock — appends nothing and the ledger file stays
byte-identical. The test pins both directions: ledger bytes unchanged
AND the input build deterministic (same args → same doc bytes). No new
idempotency layer is added; the amend path for genuinely-changed inputs
(stale-settlement semantics) stays exactly as it was.

## D5 — the settler pays through the existing transition face

The settler act books cost as a transition row with
`action_type=settle` (scoped launch stash namespace, sibling to
`dispatch`/`verify`/`prediction-settle`). Three consequences fall out
of the existing mechanics rather than new rules: no launch stash → no
row (fail-loud warn — the production wiring card must record the
launch); the stash is consumed by the first close, so a repeated
settle_blind cannot double-bill; and no production code writes a
`settle` stash today, so zero live rows appear until the step-boundary
wiring lands (recorded seam in the proposal).

## D6 — the barrier stays ONE barrier with two identity families

The settler rides the exact deny faces of the red-team (maker faces +
the two learning logs) with actor-aware reject messages and its own
repair context. The arm store file name (`runs/.rt-blind-arm.json`) is
kept — it now holds both families (rows carry the dispatch `agent`, so
the class is recoverable); renaming it would strand in-flight armed
sessions for zero blindness gain. The settler is deliberately NOT a
`VERIFIER_AGENT_MARKERS` member: that set classifies
verifier-remediation dispatches for PROVEN claims (counting toward the
depth/remediation gates), while the settler marker only ever RESTRICTS
reads — mixing the contracts would price settlement dispatches as
remediation evidence.
