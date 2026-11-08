# Tasks

## 1. RED — the arming contract

- [x] 1.1 `tests/test_learning_seal_1005.py` RED: provision() generates
  the key at the module key path (0600, hex material), armed() flips
  true, the status dict carries no key material; run it, watch it fail
  (10 failed / 6 errors / 3 pre-existing-semantics pins passed)
- [x] 1.2 RED: idempotence (existing key -> created False, bytes
  untouched), declared-path honesty (writes there, live channel stays
  unarmed), short-key refusal (never auto-overwritten)
- [x] 1.3 RED: the ARMED startup face replaces the UNSEALED warn (info
  face once per process, count-carrying); reset_once_state re-opens
  the persisted once-marker
- [x] 1.4 RED: the step-credit host seals every emitted row when armed
  (seal present, verify passes, learner filter keeps all); unarmed
  rides unsealed with exactly ONE notice, settlement un-gated (this
  pin passed RED — existing semantics, pinned before wiring)
- [x] 1.5 RED: disarm re-opens the warn (mid-process and via the
  cleared marker), no crash; CLI faces; repo hygiene scan pins

## 2. The provisioning face

- [x] 2.1 `learning_seal.provision(keypath=None)` — keygen (32 random
  bytes as hex), parent-dir creation, chmod 0600, idempotent no-op on
  a sufficient key, short-key refusal with the by-hand repair note,
  status dict {path, created, armed, key_id, note} with no key material
- [x] 2.2 `learning_seal.sealed_row_count(ws=None)` — seal-stamped rows
  across the experience + settlement families; workspace resolved
  through the diagnostics getter; honest zero on any failure
- [x] 2.3 The ARMED face (`_armed_face_once`) and the posture memo
  (`_posture_tick`): INFO milestone once per process, marker cleared,
  both faces re-opened on an observed armed/unarmed flip

## 3. The host wiring

- [x] 3.1 `rlvr.ledger.record` / `rlvr.ledger.settle` gain the
  producer-injected `sign=None` parameter (applied after the schema
  lint, before the consolidated append; default None = byte-identical)
- [x] 3.2 `rlvr.scalar.settle_round_credit` passes the channel signer
  at both emission sites (identity record + settlement amend)

## 4. The operator faces

- [x] 4.1 `kunglao_log.warn_workspace()` getter and
  `kunglao_log.reset_once_state(op)` (pinned-workspace marker reset,
  fail-open)
- [x] 4.2 `kunglao seal provision [--key-path P]` subcommand: armed
  status + path + short key id, rc 0 armed / 1 unarmed, key material
  never printed

## 5. Gates

- [x] 5.1 New suite GREEN (now 29 tests); battery over the
  directly-affected suites (seal, ledger, scalar, settlement family,
  e2e rounds, syspath/loader guards) -n 4 all green
- [x] 5.2 formal_code_lint + comment_hygiene_lint clean (no new debt);
  ruff clean on all touched files
- [x] 5.3 Deploy manifest regenerated (--write) and verified (--verify)
  after the deployable-file changes; deploy-lifecycle suite green
- [x] 5.4 openspec validate learning-seal-provision --strict: valid

## 6. Review fixes (reviewer-1005-seal verdict)

- [x] 6.1 HIGH: the CLI subprocess tests isolate HOME (the router's
  key path resolves inside the tmp home — the UNARMED/rc-1 pin is
  deterministic regardless of the host's real provisioning state); a
  companion ARMED-path subprocess pin (fresh isolated home arms, rc 0,
  idempotent re-run)
- [x] 6.2 the unpinned production shape: `reset_once_state` resolves
  its workspace even unpinned (explicit > pinned > the same cwd
  walk-up the ledger face trusts); mixed-pin P1(pinned, warn
  persisted) -> P2(unpinned, armed, cwd) -> P3(disarm) re-warns —
  pinned in the suite
- [x] 6.3 the scalar module's other two settlement writers seal:
  `settle_workspace_scalars` and `apply_trajectory_settlement` pass
  the channel signer; armed tier-scalar + trajectory amendment seals
  pinned; the risk register carries the FULL producer inventory
  (reward.py + verification_ladder.py documented deferred with the
  no-filtered-reader-today fact)
- [x] 6.4 the key file is created AT mode 0600 (`os.open` create-mode,
  no crash window), partial-key cleanup on write failure, existing
  wide keys hardened, a failed hardening reports armed:false, in-repo
  declared paths are called out; pins for all four faces
- [x] 6.5 trusted_rows docstring accuracy (the posture faces may write
  the once-marker; the stores stay untouched); sealed_row_count
  degrades to the honest zero on ANY family-read failure; the ledger
  sign seam re-validates (a schema-breaking signer is refused loudly);
  the CLI prints the workspace its sealed-row count counted
  (--workspace overrides)
- [x] 6.6 openspec delta updated (provisioning mode contract, the
  three-writer seal requirement, the unpinned marker reset, the CLI
  workspace line); validate --strict green
