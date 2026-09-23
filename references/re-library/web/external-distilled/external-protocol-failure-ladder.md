---
name: external-protocol-failure-ladder
description: 'Ordered diagnosis ladder for failing protocol replays (external-distilled, S2/S3): fixed-order
  triage from cheapest cause up — session/cookie validity, missing pre-requests, timestamp binding, header
  diff, environment participation, rate limiting; no blind big rewrites; mismatch-first check order (baseline →
  freshness → storage → request order → transport/session → truncation → automation exposure). When a previously
  working or newly built protocol request returns unexpected results.'
domain: web
family: external-distilled
source_id: S2,S3
source_license: none,MIT
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: new
---

# Protocol-failure ladder (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized paraphrase;
> provenance = S-id list above. Our trigger→observe→attribute loop localizes
> WHICH field a blocker reads; this card covers the other failure class — the
> replay/build that returns an unexpected result — and imposes a fixed
> diagnostic ORDER. Without an order, agents thrash: change three things at
> once, get a different failure, learn nothing.

## The rule

Diagnose in fixed order, cheapest-and-most-common cause first, one variable
per step, each step with its own check and evidence. Blind large rewrites
are forbidden: a rewrite that "fixes" the symptom destroys the attribution
evidence the next failure will need.

## The ladder (climb in order)

1. **Session / credential validity.** Diff the script's cookies against a
   fresh live session's: expired identity, missing HttpOnly-member cookies
   (invisible to document.cookie — they exist only in the full jar), silent
   login-state death. Evidence: jar diff, status-code distribution drift
   (401 / redirect-to-login climbing over time).
2. **Missing pre-requests.** Enumerate every request the page fires BEFORE
   the target: warm-up, token issuance, config, challenge initialization.
   A pre-request's response often carries the token/seed the target
   consumes. Evidence: full-sequence capture diffed against the script's
   request list; anything the page sends and the script does not is a
   candidate dependency.
3. **Timestamp binding.** Compare timestamp semantics end to end: unit
   (seconds vs milliseconds), float-vs-int truncation, which timestamp the
   signature consumed vs which the request carried (they must be the SAME
   value, not two values generated microseconds apart), and validity
   windows. Time-based signature failures are intermittent by construction
   — intermittency near a window boundary is itself evidence.
4. **Header diff.** Field-by-field diff of the script's headers against a
   captured success: content-type family, origin/referer, client-hint
   headers, case sensitivity, custom X-headers, accept-encoding promises the
   client cannot keep, and (rarely) header order. Then prune: start from
   the full captured set and remove until failure — necessity is proven by
   subtraction.
5. **Environment participation.** Determine whether environment values even
   ENTER the computation before investing in environment fixes: hook the
   candidate reads (navigator/screen/canvas-class), diff requests computed
   with and without each value, and only stub what the server demonstrably
   verifies. Env-stubbing without participation evidence is expensive
   guessing.
6. **Rate / reputation limiting.** Retry slower (human-scale spacing) and
   diff; check whether the failure correlates with volume or with identity
   age rather than with content. If pacing changes the outcome, the content
   was never the problem — switch to the budget/pacing discipline
   (web-crawler-engineering) instead of iterating on parameters.

Exit condition: the first rung whose check produces a DIVERGENCE owns the
failure; fix there and re-run the whole ladder from the top after the fix
(fixes can unmask the next rung).

## Mismatch-first check order (post-fix regression)

When a corrected build still mismatches, audit in this order before touching
the algorithm again: capture baseline identity (is the comparison even
same-profile?) → dynamic-resource freshness (stale bundle/challenge/seed —
resources expire; refresh in the same session) → cookie/storage state →
request ordering and session lifecycle → transport/session identity
(TLS-class fingerprint and session reuse) → evidence truncation (was the
"expected" side itself incomplete?) → automation exposure (a leak the fix
introduced). The algorithm is the LAST suspect: a verified algorithm does
not stop verifying because its callers drifted.

Companions: [web-risk-control.md](../risk-control/web-risk-control.md)
(detection-point attribution), [web-crawler-engineering.md](../crawler/web-crawler-engineering.md)
(pacing/budget discipline),
[external-algorithm-recovery-chains.md](external-algorithm-recovery-chains.md)
(first-deviation walk inside the computation).
