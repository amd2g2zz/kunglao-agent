# Tasks — issue-797-exp key freeze

Order pinned: tests RED before implementation; registration manifest
LAST.

1. [x] SDD: proposal / spec / tasks (this change dir); invariants cited
       (INV-003 family grain, #429 zero-decision, #396 import-clean,
       Standard 11).
2. [x] RED: `tests/test_key_freeze_797.py` — the pins: two synthetic
       runs same-family -> identical frozen key; cross-run fold
       accumulation; freeze immutability (dims + state drift); anchor
       mint-once/reopen-once; dispatch rows carry the frozen signature
       with a bit-identical no-doc legacy path; other(...) refused;
       churn all-new/accumulating/frozen/no-data + ledger report +
       zero-warn AST pin.
3. [x] GREEN: `scripts/rlvr/key_freeze.py` (freeze doc
       `runs/learning-key.json` schema `learning-key/1`; `churn_rate` /
       `churn_report`; CLI `--churn/--freeze/--key`) + the additive
       `_task_open_signature` consult in
       `rlvr.q_cells.record_dispatch_observation`.
4. [x] Regression: q_cells neighborhood suites (429 / 705 / 695 / 379 /
       712 / 799 / 428 / 601) green; ruff clean; comment-hygiene
       ratchet clean (q_cells back at its 70 baseline, zero new debt).
5. [x] Registration trio: `scripts/README.md` row -> `tools/ext-scan.py`
       regenerate (no-op — the ext catalog indexes top-level scripts
       only) -> `scripts/deploy_manifest.py --write` LAST, `--verify`
       clean.
6. [x] Gates: `uv run python devkit/quality_gates.py --quick` ALL-PASS;
       pin suites green; openspec validate clean.
7. [x] Review-gate chain (reviewer kunglao-w1-797); single commit; push;
       PR -> dev (no merge).
