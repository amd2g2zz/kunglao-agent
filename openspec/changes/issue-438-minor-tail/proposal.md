# Proposal — issue-438-minor-tail

## Why

Issue 438's main remediation (the per-dispatch cited cap) landed via PR
451; the issue's "Also tracked here (same review, minor)" tail stayed
open (owner comment, confirmed unfixed on dev post-merge):

1. `question_claims` (scripts/rlvr/scalar.py) reads
   `claim-register.yaml` with strict UTF-8 under
   `except (OSError, yaml.YAMLError)` — an invalid-UTF-8 register
   raises UnicodeDecodeError (a ValueError, sibling of neither) and
   kills the settlement read face: `fact_artifacts` calls
   `question_claims` on every workspace read.
2. The `stage_milestone` leg in
   `references/contracts/reward-rules.yaml`
   round_credit.value_ladder.legs is declaration-only: no settlement
   face reads it (repo-wide grep: zero code consumers); milestone
   artifacts earn full credit through the used-toward-stage citation
   leg by assumption.
3. The `scalar_settlement.py` catalog row in scripts/README.md still
   documents the pre-433 v2 round-credit formula (oracle-verified
   alone earns full) and never mentions the cited cap.

## What changes

- Decode tolerance: `UnicodeDecodeError` joins the except tuple — the
  register read degrades to the empty set, the module's existing
  tolerant-read idiom (same degradation as missing/unparseable;
  decode errors are data problems, never face-killers).
- Dead leg removal: the `stage_milestone` leg line is deleted and the
  value_ladder note discloses the actual mechanism (a milestone is
  stage use by construction and earns full through the
  cited/used-toward-stage leg; an unlinked milestone settles as the
  exploration-option trace — the disclosed under-credit-only
  assumption). Zero settlement values change; rules version stays 3.
- README row: the LEVEL 2 round-credit fragment is rewritten to the v3
  value ladder plus the per-dispatch cited cap (`CITED_CAP_DEFAULT`,
  deterministic id-sort selection, `cited_over_cap` demotion,
  late-cite rescue path).
- Tests: RED-first pins for all three (undecodable register; no
  declaration-only legs; README row names ladder + cap).

## Non-goals

- No new stage-milestone machine signal: wiring the leg would require
  one and none exists — removal is the honest fix, disclosed in the
  note.
- No rules-table version bump: zero settlement outcomes change (the
  version tracks settlement-semantic changes per the issue-379/433
  precedent; the cap itself likewise remains a module constant with
  yaml promotion a declared follow-up).
- No warn face for the degraded read: the missing/unparseable register
  already degrades silently by design; decode errors join that idiom.
