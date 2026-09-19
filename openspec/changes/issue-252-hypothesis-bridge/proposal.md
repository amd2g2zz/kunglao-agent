# Proposal: issue-252-hypothesis-bridge — the hypothesis layer joins the claim economy

## Why

Issue #252: the hypothesis organ (#528 storage, #662 seeding, #711 bets) is
healthy in isolation and contributes nothing to the ranking economy. The
seeder scaffolds carry `candidates=[]` with a PROSE contract ("the
orchestrator fills candidates") that nothing mechanizes; hypothesis state
lives in a private state machine the TS sampler cannot see; the queue
(`claim-register.yaml`) is the only thing `priority_ratio` prices. With
#234 (obstacle -> strategy siblings) and #250 (unknowns -> epistemic
claims) both minting claims DIRECTLY, the store as-is grows a SECOND
parallel queue — the exact no-second-representation red line (#446
family).

Owner research-note: this is the representation-integrity bridge —
hypothesis families must produce claim-visible arms and settle back into
one family ledger; it must not duplicate claim-register; it feeds #251.

## What Changes

- **Arms are born as CLAIMS**: new `scripts/hypothesis_bridge.py` mints
  hypothesis candidates as OPEN claims carrying the family linkage
  `competitor_group: hyp-<H-id>` + `hypothesis_ref: <H-id>` (the #234
  edge-field style) through the NORMAL mint path (append to
  claim-register.yaml) — never a parallel register. Minted claims are
  TS-samplable immediately (`priority_ratio.is_open`).
- **One representation**: a minted candidate does NOT also live as a
  store candidate string. The bridge's sweep face
  (`mint_pending_candidates`) converts legacy/feeder strings (apkid
  #669, taint #692, case #110 fillers keep their write contracts) into
  arm claims and clears the strings from `hypotheses/` — the seeder
  keeps writing candidate strings, the cold-start chain pays them into
  the economy.
- **Store demoted to the FAMILY LEDGER**: `sync_family_ledger` derives
  family state FROM claim settlements (the #528 transitions, unchanged):
  any arm PROVEN/VERIFIED -> the family hypothesis confirmed and the
  competing open hypotheses in its competitor_group superseded; all arms
  settled with none positive -> refuted; otherwise pending. Wired into
  `kunglao_record.claim_migrator` (guarded — a sync failure never fails
  the migration).
- **Candidate-fillers integrate**: #234 exhaustion-inventory siblings
  and #250 situational epistemic claims are stamped with the family
  linkage at their EXISTING mint sites (integration points, not new
  pipelines); #250's claims keep `boundary_type: epistemic` and are not
  re-minted or double-represented.
- **Lint guard (no-orphan-representation)**: `check_bridge_lint` errors
  on (a) candidate strings parked in `hypotheses/` that the sweep has
  not paid (a path writing to hypotheses/ without a corresponding claim
  mint) and (b) claims claiming family linkage to a nonexistent
  hypothesis. A static allowlist test pins which modules may write to
  `hypotheses/` without minting (scaffold/adjudication/settlement
  faces); a new writer without the bridge is a test failure.

## Boundary

- The #528 state machine internals are UNCHANGED (open/refuted/
  superseded/confirmed vocabulary and transition rules; the issue's
  out-of-scope clause).
- #250-3 owns semantic retraction; #251 owns the sampler seed region —
  untouched here. The bridge only adds linkage fields and a guarded
  sync call site.
- The seeder's fail-open posture (D7) is preserved: the sweep and the
  sync never block cold start or settlement.

## Capability Intent

One economy: hypothesis families exist as claim-visible arms and settle
back into one family ledger; nothing competes with claim-register.
