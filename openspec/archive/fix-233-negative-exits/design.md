# design — fix-233-negative-exits

## D1: one mechanical check, no text classification

The incident ("app only trusts system certs") is a FACT statement used AS a
verdict. We do NOT classify text (no "negative-flavored" pattern list — that
was explicitly rejected in design; fact statements are legitimate mid-analysis
prose). Instead the uniform rule: a closure must CITE a claim id. The grammar
is mechanical:

```python
CLAIM_ID_RE = re.compile(
    r"(?<![A-Za-z0-9-])([A-Za-z][A-Za-z0-9]*-[A-Za-z0-9]+)(?![A-Za-z0-9-])")
```

It matches the repo's register vocabulary (`C-1`, `OC-2`, `F-100`) and rejects
free prose ("commit 0001", "verifier", "app only trusts system certs").
Every `closed_by` — positive or negative closure — runs the same check.

## D2: verification source + fail-closed

Citation verification reads `claim-register.yaml` under the oracle's
`workspace_path` (same precedence as the #147 contradiction check / #664
intent check, which already read workspace state from judge()). Fail-closed
at every unverifiable point:

- no `workspace_path` → INVALID_CLOSURE (unverifiable);
- no `claim-register.yaml` → INVALID_CLOSURE (unverifiable);
- cited id absent from the register → INVALID_CLOSURE (unknown claim);
- cited claim status not in `status_defs.TERMINAL` (PROVEN / VERIFIED /
  NEGATIVE / REFUTED / DEFERRED / STALE / SUPERSEDED / DEAD) →
  INVALID_CLOSURE (OPEN or non-terminal).

`status_defs.TERMINAL` is imported; if the import fails (standalone CLI face)
the identical literal set is used (locked by tests/test_status_defs).

## D3: scope standards (pinned, unchanged standards — new enforcement)

- **Path-scoped negative** (obstacle claim, `origin: failure-obstacle`):
  status must be REFUTED. This is exactly `find_death_evidence`'s standard —
  now enforced at the closure surface too.
- **Task-scoped negative** (DEFERRED claim): the claim must carry the markers
  `infeasible_proposal.file_proposal` writes only after its fail-closed gate
  (V-signal precondition + ladder L1-L3 + non-empty inventory) passed:
  non-empty `wake_condition` AND non-empty `infeasible_ladder`. Re-deriving
  the signal here would duplicate #815; the register markers are its
  mechanical residue.
- Non-obstacle non-DEFERRED terminal claims (PROVEN/VERIFIED/...) need only
  terminality — positive closures cite, nothing more.

## D4: verdict shape

INVALID_CLOSURE items are collected alongside unresolved items and reported
under exit 1 (item-level defect, precedence unchanged: 3 > 2 > 1 > 4 > 0).
Reason names each defect: `INVALID_CLOSURE <item_id> (closed_by='<text>' —
<cause>)` with causes: `no claim id cited`, `unverifiable citation ...`,
`cited claim <id> is OPEN`, `cited claim <id> is not terminal (<status>)`,
`obstacle claim <id> must be REFUTED to license a path-scoped closure (got
<status>)`, `DEFERRED claim <id> lacks the task-scoped standard
(wake_condition/infeasible_ladder missing)`.

## D5: re-pinning

Existing suites that close items with prose (`commit 0001`, `verifier`,
bare `F-100` without a register) are re-pinned: fixtures gain a
`claim-register.yaml` with a terminal claim and `closed_by` cites it. This is
a documented contract change (proposal.md), not a test regression.

## D6: pinned sentences (prose anchors)

- `find_death_evidence` docstring + charter 判死宣告 row:
  "A path-scoped negative is licensed only by a settled obstacle claim
  (REFUTED) or a capability-falsified failure_analysis (outcome REFUTED);
  a task-scoped negative is licensed only by the DEFERRED standard (V-signal
  + recovery ladder L1-L3 + non-empty attempt inventory + wake_condition)."
