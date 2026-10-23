# Test deletion ledger — #807 de-bloat (evidence-before-deletion)

Every removal below is (a) an inventory `dead_code_pin` candidate,
(b) manually cross-checked by repo-wide word scan over
`scripts/ hooks/ tools/ .claude/ devkit/` (definition-site-only: zero
call/import sites outside tests/), and (c) GitNexus-checked
(`impact <symbol> -d upstream --depth 1` → `impactedCount: 0`,
risk LOW, index at b485b0a1). 37 test functions across 20 files; net
suite delta is DOWN with no protection obligation transferred — each
deleted test exercised a symbol with ZERO production references, so no
surviving test inherits its obligation (the obligation itself is void:
there is no wired behavior left to protect).

Classifier false-positive class fixed before any deletion landed
(`scripts/test_inventory.py` `_dead_subjects`): the reference scan used
to exclude EVERY imported stem, hiding live cross-module callers
(e.g. `hooks/session_start.py` → `compact_continuity.consume_stashed_note`).
Post-fix, 31 live-subject candidates left the class (verified on a HEAD
baseline checkout); none of them was deleted.

## Rejected candidates (kept, NOT deleted)

| candidate | rejection basis |
|---|---|
| `tests/test_hypothesis_view_584.py` (whole file, 6 tests — "unwired modules" class) | `scripts/hypothesis_view.py` IS a registered dispatch face: `deploy-manifest.yaml` ships it, `tools/_INDEX.ext.yaml` publishes `python scripts/hypothesis_view.py <WORKSPACE>` — runtime-dispatched CLI, so no-static-caller ≠ dead (dispatch-surface liveness rule). Its contract tests stay. Module wiring/disposition (#866 ledger) belongs to a product-face card, not this test-quality rail. |

## Deletions (37 functions, 20 files)

| file | removed (count) | dead subjects (GitNexus upstream=0) | surviving sibling that keeps the module's live coverage |
|---|---|---|---|
| tests/test_approach_demotion_302.py | 4 | demotion_round, forbidden_rounds, patch_forbidden | demotion_state tests kept (live via scripts/target_ladder.py) |
| tests/test_bench_grade.py | 1 | z_self_of | remaining bench_grade tests |
| tests/test_bench_redteam.py | 4 | divergent_items, build_task_brief, merge_verdicts | test_stub_roundtrip_synthetic_fixture (dispatch→merge roundtrip) |
| tests/test_blind_gate.py | 4 | record_dissent, extract_dissent | remaining blind_gate battery |
| tests/test_canonical_chain_752.py | 2 | verify_install_references | remaining canonical-chain battery |
| tests/test_deploy_truth_412.py | 4 | main_with_ws | remaining selfcheck battery |
| tests/test_eval_harness.py | 1 | inject_fault | remaining eval-harness battery |
| tests/test_external_kicker.py | 2 | build_schtasks_command, build_crontab_line | remaining kicker battery incl. live ledger_line_type path |
| tests/test_hypothesis_bridge_252.py | 2 | writer_scan_offenders | remaining bridge battery |
| tests/test_machine_check_contract.py | 1 | machine_check_map_coverage | remaining machine-check battery |
| tests/test_observability_58.py | 2 | ingest_lifecycle | remaining observability battery |
| tests/test_orchestration_event_taxonomy.py | 1 | classify_worker_status | remaining taxonomy battery |
| tests/test_orchestration_hardening.py | 1 | apply_policy | remaining hardening battery |
| tests/test_preflight_588_590.py | 2 | preconditions_questions | remaining preflight battery |
| tests/test_rho_checkpoint.py | 1 | rho_sequence | remaining rho battery |
| tests/test_state_anchor_hyp_pointers_528.py | 1 | build_anchor_payload | remaining state-anchor battery |
| tests/test_toolchain_install.py | 1 | register_ida_mcp_url | remaining toolchain-install battery |
| tests/test_update_index.py | 1 | count_by_status | remaining update-index battery |
| tests/test_value_shadow_gates.py | 1 | rho_sequence | remaining value-shadow battery |
| tests/test_verification_ladder_429.py | 1 | note_write | remaining ladder battery incl. live settle_mainline_decisions path |

The dead modules themselves (e.g. `scripts/hypothesis_view.py` aside,
the def-only helper faces) are PRODUCT surface — removing them is a
product-face/refactor-cleaner decision, out of #807's test-quality
boundary (this card touches tests / devkit / workflow / docs /
inventory only).

Companion hygiene: the stray tracked `.coverage` artifact is untracked
(added to `.gitignore`); coverage artifacts belong to run output, not
the repo.
