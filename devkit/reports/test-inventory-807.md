# Test inventory — bloat classification

Generated 2026-10-23T15:49:07+00:00 by `scripts/test_inventory.py` (DESCRIBE-ONLY).

| metric | value |
|---|---|
| test files | 744 |
| test functions | 10324 |
| mock_shape_only candidates | 0 |
| generated_golden candidates | 28 |
| dead_code_pin candidates | 16 |
| param_redundant candidates | 15 |

Candidates are HEURISTIC — every deletion requires manual verification + GitNexus dead-code cross-check (method contract).

## generated_golden (28)

| file | test | line | detail |
|---|---|---|---|
| tests/test_dedup_319.py | `test_single_tracked_precommit_gate` | 77 | pins regenerated artifact: .claude/hooks/ |
| tests/test_dedup_319.py | `test_no_reference_to_legacy_precommit_path` | 93 | pins regenerated artifact: .claude/hooks/ |
| tests/test_deploy_closure_810.py | `test_data_assets_deployed` | 41 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_deploy_closure_810.py | `test_completeness_report` | 75 | pins regenerated artifact: .claude/scripts/ |
| tests/test_deploy_closure_810.py | `test_activation_writes_env_incident_on_incomplete` | 94 | pins regenerated artifact: .claude/scripts/ |
| tests/test_deploy_inversion_783.py | `test_register_invokes_ws_local_when_copies_materialized` | 29 | pins regenerated artifact: .claude/hooks/ |
| tests/test_deploy_lifecycle_783.py | `test_manifest_digest_matches_yaml_contract_and_is_order_stable` | 148 | pins regenerated artifact: deploy-manifest.yaml |
| tests/test_deploy_lifecycle_783.py | `test_lifecycle_init_drift_upgrade_current` | 391 | pins regenerated artifact: .claude/hooks/ |
| tests/test_deploy_local_783.py | `test_deploy_local_e2e` | 28 | pins regenerated artifact: .claude/hooks/ |
| tests/test_ext_index.py | `TestShippedExtIndex.test_index_file_exists` | 75 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_ext_index.py | `TestExtScan.test_check_detects_stale_index` | 212 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_ext_index.py | `TestExtScan.test_check_non_utf8_tampered_index_exits_clean` | 224 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_ext_index.py | `TestIndexToolNamesExt.test_fail_closed_on_broken_ext_yaml` | 400 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_ext_index.py | `TestMcpWiring.test_committed_repo_index_stays_environment_free` | 544 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_external_kicker.py | `test_ensure_project_hooks_preserves_other_matchers` | 177 | pins regenerated artifact: .claude/hooks/ |
| tests/test_function_kg_530.py | `test_ext_index_no_longer_enumerates_function_kg` | 48 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_harness_common_863g.py | `test_scan_target_excludes_sibling_worktrees_and_deployed_scaffolds` | 186 | pins regenerated artifact: .claude/scripts/ |
| tests/test_init_deploy_env.py | `test_l2_core_agents_deployed` | 149 | pins regenerated artifact: .claude/agents/ |
| tests/test_mcp_env_e2e.py | `test_mock_mcp_face_artifact_to_evidence_e2e` | 85 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_statusline_assembly_212.py | `TestDeployedDataPlane.test_init_deploys_snapshot_script_with_manifest_sha` | 234 | pins regenerated artifact: deploy-manifest.yaml |
| tests/test_statusline_assembly_212.py | `TestDeployedDataPlane.test_tick_invokes_the_deployed_copy` | 263 | pins regenerated artifact: .claude/scripts/ |
| tests/test_statusline_v2_142.py | `TestStatuslineRegistration142.test_deploy_manifest_carries_the_renderer` | 623 | pins regenerated artifact: .claude/scripts/ |
| tests/test_statusline_v2_142.py | `TestStatuslineRegistration142.test_committed_manifest_matches_build_entries` | 631 | pins regenerated artifact: deploy-manifest.yaml |
| tests/test_subagent_injection.py | `TestExtNameResolution.test_broken_ext_yaml_keeps_internal_names` | 478 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_subagent_injection.py | `TestExtNameResolution.test_real_repo_ext_citations_resolve` | 485 | pins regenerated artifact: _INDEX.ext.yaml |
| tests/test_upgrade_016_sweep.py | `test_hook_wiring_runs_in_framework_env` | 686 | pins regenerated artifact: .claude/hooks/ |
| tests/test_v012_milestone_audit.py | `test_no_legacy_precommit_reference` | 51 | pins regenerated artifact: .claude/hooks/ |
| tests/test_ws_layout_delegation_863c.py | `test_scan_target_excludes_sibling_worktrees_and_deployed_scaffolds` | 90 | pins regenerated artifact: .claude/scripts/ |

## dead_code_pin (16)

| file | test | line | detail |
|---|---|---|---|
| tests/test_recall_inject.py | `test_go_signals_map_to_go_query` | 89 | dead subjects: queries_for_features |
| tests/test_recall_inject.py | `test_t3_signals_map_to_vm_dynamic_queries` | 95 | dead subjects: queries_for_features |
| tests/test_recall_inject.py | `test_disasm_tier2_maps_to_static_analysis_query` | 101 | dead subjects: queries_for_features |
| tests/test_recall_inject.py | `test_default_tier1_maps_to_static_analysis_query` | 109 | dead subjects: queries_for_features |
| tests/test_settle_by_need.py | `test_replay_observation_does_not_settle_algorithm_claim` | 28 | dead subjects: settle_attempt |
| tests/test_settle_by_need.py | `test_replay_observation_is_rerouted_to_input_contract` | 35 | dead subjects: settle_attempt |
| tests/test_settle_by_need.py | `test_reproduction_evidence_settles_algorithm_claim` | 41 | dead subjects: settle_attempt |
| tests/test_settle_by_need.py | `test_replay_observation_settles_input_contract_claim` | 49 | dead subjects: settle_attempt |
| tests/test_settle_by_need.py | `test_untyped_need_fails_closed` | 56 | dead subjects: settle_attempt |
| tests/test_settle_by_need.py | `test_unknown_evidence_class_fails_closed` | 67 | dead subjects: settle_attempt |
| tests/test_shared_primitives_292.py | `test_sbn_reproduction_settles_generation_side` | 358 | dead subjects: settle_attempt |
| tests/test_shared_primitives_292.py | `test_sbn_replay_rerouted_from_generation_side` | 366 | dead subjects: settle_attempt |
| tests/test_shared_primitives_292.py | `test_sbn_replay_settles_input_contract` | 377 | dead subjects: settle_attempt |
| tests/test_shared_primitives_292.py | `test_sbn_unknown_class_fails_closed` | 385 | dead subjects: settle_attempt |
| tests/test_web_knowledge_761.py | `TestJ1RecallInjectDictionary.test_web_signals_extend_queries` | 204 | dead subjects: queries_for_features |
| tests/test_web_knowledge_761.py | `TestJ1RecallInjectDictionary.test_non_web_claim_gets_no_web_query` | 215 | dead subjects: queries_for_features |

## param_redundant (15)

| file | test | line | detail |
|---|---|---|---|
| tests/test_blocker_evidence_gate_340.py | `TestEnvAttributionEvidenceGate.test_every_pattern_phrasing_rejected_without_evidence` | 139 | 9 cases, branch-free, 1 assert(s) |
| tests/test_completion_gate.py | `test_agent_identifiers_all_rejected` | 186 | 14 cases, branch-free, 1 assert(s) |
| tests/test_dispatch_tools_760.py | `TestI1FrontmatterHelperUnit.test_tool_matches_pattern_semantics` | 212 | 6 cases, branch-free, 1 assert(s) |
| tests/test_dynamic_channel_698.py | `test_channel_enum_known_values` | 93 | 7 cases, branch-free, 1 assert(s) |
| tests/test_eval_matrix_ws5.py | `test_malformed_registry_refuses` | 209 | 7 cases, branch-free, 0 assert(s) |
| tests/test_lint_facts_532.py | `test_index_row_shape` | 150 | 7 cases, branch-free, 1 assert(s) |
| tests/test_probe_features_581.py | `TestEntropyTokens.test_fixed_edge_bands` | 92 | 9 cases, branch-free, 1 assert(s) |
| tests/test_probe_features_581.py | `TestConstantDensityTokens.test_fixed_edge_density_bands` | 126 | 7 cases, branch-free, 1 assert(s) |
| tests/test_probe_features_581.py | `TestFeatureTableAdditiveBump.test_malformed_floss_face_rejected` | 235 | 7 cases, branch-free, 1 assert(s) |
| tests/test_reproduction_oracle_248.py | `test_generation_language_is_detected` | 42 | 7 cases, branch-free, 1 assert(s) |
| tests/test_runtime_fact_gate_341.py | `test_volatile_pattern_hits_subject_words` | 140 | 10 cases, branch-free, 1 assert(s) |
| tests/test_seven_arm_569.py | `test_multisample_validation_refuses` | 335 | 8 cases, branch-free, 0 assert(s) |
| tests/test_subagent_injection.py | `TestRealShelfResolvability.test_real_citation_resolves` | 562 | 11 cases, branch-free, 1 assert(s) |
| tests/test_validate_index.py | `TestPass.test_every_category_id_passes` | 115 | 6 cases, branch-free, 1 assert(s) |
| tests/test_validate_index.py | `TestFail.test_missing_required_field_fails` | 144 | 7 cases, branch-free, 1 assert(s) |

