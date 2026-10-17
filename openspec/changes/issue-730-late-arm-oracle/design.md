# design — issue-730-late-arm-oracle

## The defect, precisely

`run()` assembles one round per TERMINAL claim:

```python
claims = terminal_claims(ws)
dispatches = [{"dispatch_id": cid, "round": i + 1} for i, cid in enumerate(claims)]
```

so `dispatch_id` IS the claim id, and `banked` — the settle path's return
— is the set of claims whose FIRST settlement rode this pass.

`record_case_settlements(ws, banked)` then walks only that set.
Idempotency was therefore bought by a PROXY: "was it banked this pass"
stood in for "was it observed". The two coincide only when the case is
armed before settlement. Arming after settlement leaves the pair
permanently un-observable — the claim's id never re-enters `banked`.

**The fix is to replace the proxy with the real thing**: an explicit,
auditable record of which pairs were observed. That record is the
`case-observation/1` row itself, so there is no second bookkeeping
structure to drift out of sync.

## Why the ledger, not the belief store

The observation history could have lived on `CasePosterior` (an
`observed: list[str]` field). It lives in the consolidated experience
ledger instead, for three reasons:

1. **Lifecycle fit** — the four-family cut puts WHAT HAPPENED
   (`experience`) apart from WHAT IS KNOWN (`knowledge` / the posterior
   store). An observation event is "what happened".
2. **Auditability** — an amendment is visible as a row carrying its
   `source` (`fresh` vs `late-arm`), instead of a count that silently
   changed.
3. **Reconcilability** — the dedup set is read from the same rows that
   justify the posterior, so belief and evidence cannot disagree about
   what was counted.

Cost, stated honestly: the posterior is not rebuildable from the ledger
alone if `runs/posteriors.yaml` is deleted, because the amendment would
then see the pairs as already observed and re-observe nothing. Deleting
the belief store is not a supported flow (the ledgers are append-only
history, and the posterior is derived state), so this is accepted rather
than engineered around.

## The two legs and their order

| Leg | Input | Covers | Dedup |
|---|---|---|---|
| `record_case_settlements(ws, banked)` — fresh | claims first-settled this pass | what this pass banked | pair-level, via the ledger |
| `amend_case_settlements(ws)` — late-arm | every decisive-terminal claim in the register | the settle-before-arm ordering | pair-level, via the ledger |

Both legs are the SAME shape — one entry builder, one write face, one
dedup set — differing in the claim set they hand it and in whether the
link index filters on arming (see below). The pair
`(case_id, claim_id)` is the unit of observation, and the dedup set is
extended as entries are built, so a duplicate case id, a duplicate
claim, or a second leg arriving at the same pair all collapse. The fresh
leg also consults the ledger, which is what makes a settle-path RETRY
safe: a pass that re-banks a claim an earlier amendment already observed
must not observe it again.

**The order is an attribution choice, not a correctness one.** Both legs
dedup, so running the amendment first would not double-count — it would
merely credit every observation to the amendment and report the fresh
leg as a no-op. Fresh-first keeps the two counts meaningful: the fresh
run reports what this pass banked, the amendment reports the back-fill.

## Armed-only — the amendment only

The amendment observes only ARMED cases (all five arming fields present:
`channel` / `hypothesis_ref` / `update_map` / `expected.evidence_refs` /
`mutations`). It back-fills claims that settled before their case
existed, so it must only write cases that are complete, deliberate
question-linkages: a stub doc with a bare `target_pq` is not a hypothesis
anybody committed to, and observing against it would move a posterior on
the strength of a placeholder.

**Arming is NOT runner-loadability — and this card does not claim it
is.** The arming shape and the runner's `load_cases` disagree on the
`expected` field (a mapping with `evidence_refs` vs a non-empty list of
entries), so a doc can be armed-but-not-loadable or loadable-but-not-armed
— the live workspace's own armed cases are in the first class. That
mismatch is a pre-existing defect in the arming definition and is tracked
separately; the observation legs key on the ARMING definition. An earlier
draft of this design justified the gate with "the runner can load it and
run its mutations"; that sentence was false and was removed.

Retired cases are skipped by both legs (`status: retired`), mirroring the
loader — a case retired out of the acceptance net must not keep
collecting observations.

The FRESH leg keeps the link it has always had — `target_pq` alone,
without the arming filter — and its suite pins that
(`tests/test_credit_settle_634.py`, `tests/test_rl_output_path_691.py`).
Tightening it was attempted during review and reverted: it is a separate
behaviour change, it broke the module's own original suite, and it has
nothing to do with the late-arm gap this card closes. The link index
therefore takes an `armed_only` flag, and the asymmetry is stated here
rather than left implicit.

The single index scan (cases grouped by `target_pq`, built once per call)
also replaces the previous per-claim directory re-glob.

## Write ordering: the belief first

`_apply_case_observations` saves the posterior ledger and THEN appends
the audit rows.

The ledger rows are the dedup record, so the two failure windows are not
symmetric. Rows-first: a failed posterior save leaves the pair reading as
observed forever while the belief never moved — a permanent, SILENT gap,
exactly the bug class this card exists to close. Belief-first: a failed
row append leaves the pair unmarked, so the next pass re-observes it.

That second failure is **not self-healing on its own**, and the review
probes proved it: a transient refusal recovers on the retry, but a
persistent one drifts without bound while `case_observations` reports 0.
The error field is what makes it loud, and it is therefore set on EVERY
shortfall rather than once. Both windows are counted; neither raises.

A refused append (`consolidated_ledger.append` returns `False` rather
than raising) is likewise not counted as an observation:
`case_observations` reports rows that actually landed, while
`cases_passed` / `cases_failed` report what the pass attempted.

## Idempotency

The dedup set is `{(case_id, claim_id)}` folded from the ledger's
`case-observation/1` rows. A re-run therefore finds every pair present
and appends nothing; a re-run at any wall-clock distance is a no-op.
Verified on live-workspace data: first pass 3 observations, second pass 0,
row count and posterior parameters unchanged.

## Failure posture

Unchanged from the surrounding module: fail-open. A broken write is a
counted `case_observations_error` field and ONE warn — never a raise, and
never a crash of the tick. `run()` propagates the error from EITHER leg,
so a broken amendment is visible in the mechanism's `--json` readout
instead of reading as "nothing to do". An empty entry set returns before
touching the posterior ledger, so the honest cold start still creates no
file.
