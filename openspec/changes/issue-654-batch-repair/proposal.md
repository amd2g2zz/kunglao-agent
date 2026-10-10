# issue-654-batch-repair — the accumulating batch-repair card, wave 2

## Why

Issue #654 spawned from #601's consolidated triage ("accumulating —
batch-repair card post-RC1"). Wave 1 (#662) landed the cheap,
mechanically-fixable subset — 1-F1, 1-F2, 4-L7, 1-F4 — and explicitly
deferred the rest to this card: **1-F3, 1-F9, 4-L6, 4-L8, 4-L5, 5-F4**
(each finding's fix direction named in the #601 lens comments). This
change implements those six findings so the v0.1.6 milestone card can
close.

## What Changes

1. **1-F3 — the launch-stash schema wall** (`rlvr/incremental_reward.py`):
   `record_launch` stamps ``schema: "dispatch-launch/1"``;
   `append_transition` refuses (None + ONE warn, stash LEFT INTACT — the
   parked wake plan must survive) any stash doc that carries a foreign
   ``schema`` or the orchestrator parked-envelope ``status`` field
   (the live 1-F3 shape). Legacy schema-less launch stashes (in-flight
   workspaces) keep settling byte-identically — the #550 back-compat
   rule.
2. **1-F9 — the obstacle invalidation face** (`rlvr/obstacles.py`):
   rows gain an additive retraction marker (``retracted: true`` +
   ``retracted_ts`` + ``retracted_reason`` — history stays on disk, the
   Phase-1 "a row is history" posture preserved); a sweep pairs
   ``kind=missing_env_entry`` rows that carry an ``env_key`` against the
   #475 env-state single source (`runs/env-state.json`) and retracts the
   rows whose entry now probes ``pass`` (a repaired env entry stops
   feeding the termination floor); ``read()``/``face()`` exclude
   retracted rows. ``record`` accepts the optional ``env_key``.
3. **4-L6 — read-time probe re-certification** (`rlvr/obstacles.py`):
   ``read()`` re-runs the probe-marker check on the cited artifact WHEN
   the artifact still exists; present-but-shapeless (tampered/rewritten)
   → the row is excluded from the face (ONE warn); artifact gone →
   history kept (unchanged posture).
4. **4-L5 — scaffold-aimed discriminators refused**
   (`rlvr/prediction_ledger.py`): ``register`` refuses a discriminator
   aimed at the checker's own MANDATED output (the engine-parsed
   ``verdict:`` frontmatter line, checkpoints.py:1308/1518/1553) — such
   a discriminator settles on contract compliance, not on the claim's
   truth (base rate ~1 by construction).
5. **5-F4 — prediction rows carry authorship; unattributed rows cannot
   settle** (`rlvr/prediction_ledger.py`): ``register`` REQUIRES a
   non-empty ``actor`` (the registered act's identity, stamped
   ``registered_by`` into the row); ``settle``/``settle_matching``
   refuse (warn, no settle) any pending row lacking ``registered_by`` —
   the raw-JSONL-append bypass (runs/predictions.jsonl is not a
   carrier) now produces rows that can never bank lift. Residual named:
   a forger who copies the authorship SHAPE is the red-team trust class
   (same named residual class as the oracle-status face, #662 4-L7).
6. **4-L8 — the SNIPS π cross-check + the declared-exclusion**
   (`rlvr/policy_compare.py`): the comparator now (a) skips rows whose
   audit envelope carries ``declared: true`` (counted
   ``skipped_declared_fiat`` — no draw receipt backs π=1.0, the SNIPS
   mixing assumption does not hold) and (b) cross-checks the transition
   row's recorded propensity against the audit envelope's propensity
   (two independent on-disk carriers of the same receipt value);
   mismatch → skip + count + warn (a corrupted carrier can no longer
   move the verdict silently).

## Out of scope

- The red-team trust class residuals (forged authorship SHAPE, forged
  full-shape oracle-status docs) — red-team domain, per the #662
  precedent of naming them in the docstring.
- Making `runs/predictions.jsonl` a write-guard carrier (the
  authorship-settle wall closes the reward path; the carrier question
  is a policy act for the mechanical-independence card #652).
- 1-F6/F7/F8, 4-L9 (bounded group — recorded on #601, no card).
