# -*- coding: utf-8 -*-
"""status_defs — single source of truth for claim status sets (safety net #34).

All claim-status consumers import the sets defined here instead of
re-defining them, so a new status (e.g. DEAD for the DLQ) is added in ONE
place and every consumer picks it up. See
`openspec/changes/status-defs-safety-net/` for the full design.

Sets
----
TERMINAL (8 values):
    {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE", "SUPERSEDED", "DEAD"}
    Any status in TERMINAL means the claim needs no further work.
    SUPERSEDED added for #59: a claim closed by replacement (superseded_by)
    is terminal and must not be re-dispatched. Previously absent, so
    convergence_check._open_claims / priority._is_open counted superseded
    claims as OPEN and the loop DISPATCHed on already-closed claims.
    DEAD added for #36: a claim killed by the DLQ (promotion_attempts >= 3,
    poison / exhausted) is terminal and must not be re-dispatched. Without
    it, the convergence loop re-ranked exhausted claims every tick, spinning
    workers on claims that will not close. mark_dead (scripts/dead_letter.py)
    is the explicit writer; consumers pick up DEAD via this set.
    NOTE: the pre-change scripts were split 5-value (convergence_check /
    priority / priority_ratio / failure_analysis_gate / kunglao_record /
    progress_report: no STALE) vs 6-value (stale_blocker_prune /
    plan_drift_detector: +STALE). Unified here to 6 values — the ONLY
    behavioral change of this refactor: STALE claims are now terminal in
    the former 5-value consumers (they were treated as open, i.e.
    dispatchable, before).

PARTIAL_STATUSES:
    {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}
    A fact/claim that has evidence but needs verification.

IN_PROGRESS_STATUSES:
    {"IN_PROGRESS"}
    The in-flight marker: a claim already dispatched to a worker. NOT
    dispatchable. Consumers that used the literal `status != "IN_PROGRESS"`
    branch alongside TERMINAL use `status not in IN_PROGRESS_STATUSES`.

ACTIVE_STATUSES:
    {"OPEN", "IN_PROGRESS"}
    Claims with ongoing/awaiting work (claim_expiry checks these for
    staleness). "OPEN" = needs work (dispatchable); "IN_PROGRESS" = already
    dispatched (not dispatchable). Two concepts, one set — do NOT use this
    for dispatchability.

LedgerLineType (.convergence_ledger.jsonl row contract)
------------------------------------------------------
Rows are either SNAPSHOT (default; the convergence trajectory snapshot
with ts/decision/open_count/open_ids/partial_count/active_workers/
blockers/facts_total) or OUTCOME (event: one external-checker verification
result — #35 writes these; fields type/ts/claim_id/checker/result).
Aggregation MUST only consume rows with type == OUTCOME — never treat
snapshot fields (e.g. a stale active_workers count) as events.
Existing rows without a `type` field are SNAPSHOT; adding the field is
additive and breaks nothing.

Adding a new status (operating manual, e.g. #36 DEAD)
-----------------------------------------------------
1. Add it to the canonical legal set below (and to TERMINAL iff a DEAD
   claim needs no further work — yes for DLQ).
2. Check it against PARTIAL_STATUSES / IN_PROGRESS_STATUSES — a new
   terminal status must NOT be in either.
3. Consider ledger impact: DEAD is a claim status, not a ledger row type —
   no LedgerLineType change needed.
4. Consumers pick it up automatically; the grep guard in
   test_status_defs.py (test_consumer_has_no_own_status_set) prevents a
   hardcoded copy from drifting.
"""

TERMINAL = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE", "SUPERSEDED", "DEAD"}

PARTIAL_STATUSES = {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}

IN_PROGRESS_STATUSES = {"IN_PROGRESS"}

ACTIVE_STATUSES = {"OPEN", "IN_PROGRESS"}


class LedgerLineType:
    """Ledger row kinds. See module docstring for the row contract."""

    SNAPSHOT = "snapshot"
    OUTCOME = "outcome"
    OPERATOR_ACTION = "operator_action"


def ledger_line_type(row: dict) -> str:
    """Return the LedgerLineType of a ledger row.

    Rows without a `type` field are SNAPSHOT (additive compatibility with
    pre-contract rows).
    """
    return row.get("type", LedgerLineType.SNAPSHOT)
