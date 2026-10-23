# issue-802-blind-settler-wire — tasks

1. [x] SDD: openspec change directory (this change), `openspec validate` clean
2. [x] RED: `tests/test_blind_settler_wire_802.py` — poisoned synthetic
   fixtures pin the isolation boundary (a forbidden face in the
   artifact list = RED; a legal park carries zero poison bytes), the
   sha-drift/identity/hand-built refusals, the #809 mint wall, the eval
   gate, the wire rows
3. [x] GREEN: `scripts/rlvr/settlement_wire.py` (writer + consumer +
   gate + fingerprint row)
4. [x] GREEN: `scripts/rlvr/step_grain.py` — `settle_step(blind=)`:
   judgment legs eval-only, mechanical bookkeeping unchanged
5. [x] GREEN: `hooks/round_closure.py` — the blind stop face (park +
   settle_face) in its own cage; eval env opts back into the legacy face
6. [x] docstring/architecture alignment: `settlement_scorer` SHIPPING
   STATUS now records the wired state (no code path advertises
   unwired-ness that production does not have)
7. [x] liveness: `blind-settlement-wired` fingerprint registered
   (devkit registry + docs) + `settlement-wire/1` in
   consolidated_ledger NATIVE_SCHEMAS
8. [x] registration trio: scripts/README row, deploy_manifest --write LAST
9. [x] targeted suites green (`-n 4`), quality gates ALL-PASS
