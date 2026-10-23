# issue-809-verifier-integrity — PROVEN must rest on a passing independent verification

## Why

Production logs (the android/web runs of late October) show the
adversarial-verification layer failing 100% while claims still settled
PROVEN: the L1 verifier false-rejected 9/9 yet C-004/C-006 minted
PROVEN, with settlement timestamps PRECEDING the verifier rejects. On
the web run the verifier could not parse YAML block scalars (good facts
rejected for format) and the oracle channel stayed
`client_not_registered` for the entire run. Gates exist, gates fire,
nobody is bound by them — the recording→admission inversion. #800 made
claims_store the ONE semantic owner; this card upgrades "settlement
references a verification record" to "settlement references a record
that PASSED".

## What Changes

1. **NEW `scripts/verifier_integrity.py`** — the verification-record
   resolver and per-verifier calibration faces:
   - `resolve_verification(ws, claim, reference)` resolves a settlement's
     verification reference to an on-disk record
     (`runs/verification-<claim>.md`, `runs/<claim>-verify-note.md`,
     `runs/verify-redteam-<claim>.md`, `evidence/verdict.json`, or an
     explicit workspace-relative path) and classifies its verdict word
     (pass set: verified/confirmed/pass/passed/passes; fail set:
     refuted/rejected/fail/failed/falsified). Fail-closed: absence,
     traversal escape, unparseable content, or an unknown word is NOT a
     pass.
   - `calibration_check(ws)` — the anti-surrender floor raised from
     per-verdict to per-verifier: a verifier whose verdict records are
     100% one-sided over `CALIBRATION_MIN_SAMPLE` or more records is
     BROKEN — one loud `verifier_calibration_broken` event per
     occurrence, bounded per verifier by Standard 11 (escalate at the
     limit = the verifier's trust is burned).
2. **claims_store PROVEN hard precondition** — `apply(settle_proven |
   settle_verified)` now RESOLVES the verification reference through
   `resolve_verification`; a reference that does not resolve to a
   PASSED record is refused with a provenance row
   (`verification-not-passed: ...`). Synthetic replays pin the two
   production shapes: settlement-preceding-REJECT, and 9/9
   false-rejects-yet-PROVEN. (Original production logs never enter the
   repo — fixtures are synthetic.)
3. **YAML block-scalar parse repair (kunglao_verify)** — the L1 fact
   frontmatter parser handles block scalars (`|` / `>` with chomping
   and indentation hints). A format-only difference (block style,
   folding, chomping, indentation width) no longer rejects: the value
   is extracted and the normalization lands a WARN sidecar (returned on
   the fact as `_format_warnings` and mirrored by `l1_mechanical` in
   the verdict detail without changing the verdict). Semantic
   differences still FAIL exactly as before.
4. **Oracle run-start registration assertion** — `oracle_cadence.
   assert_run_start(ws)` emits a loud bounded `oracle_cadence_warn`
   (face=run_start, reason=client_not_registered) when armed oracle
   cases exist but no implementation-under-test is registered;
   `claims_store.begin_dispatch` calls it fail-open before the first
   dispatch intent of a run. The all-run-silent
   `client_not_registered` shape becomes impossible to miss.

## Impact

- Affected: `scripts/claims_store.py` (settle precondition + dispatch
  telemetry seam), `scripts/kunglao_verify.py` (frontmatter parser),
  `scripts/oracle_cadence.py` (run-start face), `scripts/event_taxonomy.py`
  (one new emit word), NEW `scripts/verifier_integrity.py`, NEW
  `tests/test_verifier_integrity_809.py`; existing #800 test fixtures
  seed real passing records.
- Invariants referenced: #800 provenance row on every refusal;
  #800 verification-ordering guard (kept, now subsumed); Standard 11
  bounded repetition (calibration + run-start counters);
  #825 verifier-identity extraction; #601 verify-stamp writer binding
  (resolver reads stamps, never mints them); #687 path-normalization
  posture (case-folded, traversal-proof reference resolution).
