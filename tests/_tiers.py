# -*- coding: utf-8 -*-
"""tests/_tiers.py — the tier registry for the test-suite acceleration work.

Single source of truth for the three-tier classification applied by the
root conftest (pytest_collection_modifyitems):

  fast        pure-unit modules: no subprocess, no network, no nested
              pytest, no heavy IO. Runs on every push as its own CI leg
              (target: well under a minute under xdist).
  slow        explicitly-heavy modules (nested pytest suites, long
              wall-clock probes). Never skipped — the integration leg
              runs them on every PR; the marker exists so the census can
              classify every test and CI can report the split.
  integration the default: anything not listed in either registry.

  docs        ROUTING TAG, not a tier — docs/README/governance contract
              modules sliced into their own CI leg. A docs module still
              carries exactly one tier (fast or integration).

Membership rules:
  - the registries name MODULES (stem names), applied per test item;
  - a module may not be in both FAST and SLOW (census fails loudly);
  - eligibility for fast is by construction: the module contains no
    subprocess/socket/urllib/HTTP usage and no golden-master replay
    (re-verified by the census test against the module source).
"""
from __future__ import annotations

FAST_MODULES = frozenset({
    "test_adversarial_gate_909", "test_adversarial_loop_909", "test_agents_hygiene", "test_algorithm_event_log_157",
    "test_anomaly_detector", "test_apk_mem_gate", "test_ask_for_direction_charter", "test_ask_for_direction_v2",
    "test_assembly_history_700", "test_audit_guard_reviewgate_799", "test_audit_legacy_proven", "test_audit_traceability",
    "test_bash_fact_guard_809", "test_bench_analyze", "test_bench_grade", "test_bench_intake",
    "test_bench_redteam", "test_bench_runner", "test_bench_safety", "test_bench_tokens",
    "test_blind_gate", "test_budget_channel_862", "test_calibration_gate", "test_canary_gates",
    "test_carrier_consistency_829", "test_case_bank_110", "test_case_bank_49", "test_challenge_ledger_909",
    "test_changelog", "test_claim_status_guard", "test_classification_collapse_581", "test_claudemd_g2g3_758",
    "test_closure_contract_628_629", "test_coldstart_digest_528", "test_compat_removal_863d", "test_completion_gate_optout",
    "test_completion_transaction", "test_contract_docs", "test_convergence_completeness", "test_convergence_health_rollup",
    "test_convergence_health_stalled_2", "test_convergence_rules_file", "test_course_distill_165", "test_coverage_floor_520",
    "test_coverage_policy_564", "test_crypto_algorithms", "test_dead_code_removal", "test_dead_letter",
    "test_decide_regression_anchor", "test_decide_state_machine", "test_decision_pending", "test_decision_surface_anchor",
    "test_declaration_scan", "test_declared_coverage_147", "test_delegation_863i", "test_deobf_composition",
    "test_deploy_closure_810", "test_deploy_inversion_783", "test_detector_utilization_127", "test_difficulty_thresholds_16",
    "test_digest", "test_digest_sec_g_528", "test_disasm_constant_check", "test_dispatch_background_704",
    "test_dispatch_context", "test_dispatch_context_providers", "test_dlq_dead_letter", "test_doc_pointer_lighting_24",
    "test_docsync_589_563", "test_done_default_550", "test_drift_detection", "test_drift_events_612",
    "test_dual_gate_868", "test_emit_gate_880", "test_encoding_declarations", "test_entry_sweep_585",
    "test_env_dotenv", "test_env_negative_rule", "test_eval_harness", "test_evals_fixture_530",
    "test_evals_schema", "test_evidence_index", "test_expected_hashlock_828", "test_external_kicker",
    "test_fact_expected_binding", "test_fail_closed_gates", "test_failopen_tiering_103", "test_failure_registry_530",
    "test_feedback", "test_fix_98_deadlock", "test_fixture_excerpt_lint", "test_fixture_factories_863l",
    "test_function_kg_530", "test_gitignore_coverage", "test_gitnexus_semantic_query", "test_global_hook_purge_143",
    "test_goal_operationalization_128", "test_governance_binding_867", "test_harness_common_863g", "test_heartbeat_gate",
    "test_heartbeat_pulse_618", "test_heartbeat_window_4", "test_hook_exit_codes", "test_hook_registration_entry",
    "test_hook_registry_singlesource", "test_hooks_resolve_workspace_delegation_865", "test_hypothesis_contradiction_gate", "test_hypothesis_loop_integration_111",
    "test_hypothesis_seeder", "test_hypothesis_store_528", "test_icd203_alignment", "test_ida_pro_unlock_46",
    "test_index_capability_annotations", "test_index_docs_contract", "test_infeasible_proposal_815", "test_infeasible_signal",
    "test_inference_blind_scope", "test_init_completeness", "test_init_handoff_593_598", "test_init_marker_625",
    "test_intake_promise_813", "test_issue238_role_contracts", "test_kunglao_core_loop", "test_kunglao_decide",
    "test_kunglao_log_channel_699", "test_kunglao_redteam_verdict_layer", "test_ledger_stdlib_584", "test_lessons_nursery",
    "test_lessons_telemetry", "test_lessons_tombstone", "test_lessons_trigger_precision", "test_lint_facts_532",
    "test_liveness_policy_597", "test_machine_check_contract", "test_max_retries_604", "test_mechanisms_retirement",
    "test_migrate_facts_809", "test_mission_ledger_823", "test_mission_repin_868", "test_mission_stall_634",
    "test_monitor_wiring_620c", "test_no_cti_agents", "test_notes_discriminator", "test_notes_fake_834",
    "test_notes_supersedes_528", "test_obligation_discovery", "test_observability_birth_880", "test_operator_action",
    "test_oracle_cadence_132", "test_oracle_runner_108", "test_orchestration_chunker", "test_orchestration_cost_estimate",
    "test_orchestration_eval_quality", "test_orchestration_event_taxonomy", "test_orchestration_hardening", "test_orchestration_recov_metrics",
    "test_orchestrator_tool_guard_608", "test_outcome_capture", "test_outcome_forensics_146", "test_pdl_collapse_582",
    "test_pkg_detect", "test_plaintext_610", "test_plan_drift_stale_plan", "test_plan_drift_unverified",
    "test_posteriors_106", "test_pr_template_530", "test_preflight_588_590", "test_premature_termination_detect",
    "test_priority_data_hookup_9", "test_priority_inputs_594_596", "test_priority_ratio", "test_priority_value_terms",
    "test_progress_report_663", "test_progress_txt_530", "test_prompt_command_611", "test_provenance_wiring",
    "test_python_floor", "test_qtable_p3", "test_queue_distill_176", "test_recall_quality_814",
    "test_reconcile_intents", "test_reconcile_workers", "test_redteam_antitemplate_827", "test_references_index",
    "test_refutation_propagate", "test_register_proven_gate", "test_reject_emit_624", "test_relib_audit_817",
    "test_renderer_unify", "test_renew_audit_619", "test_replay_equivalence_172", "test_report_consistency_check",
    "test_resume_hypotheses_528", "test_resume_prompt", "test_retirement_gate_861", "test_retract_claim",
    "test_rho_checkpoint", "test_rho_verifier_823p2", "test_roi_settlement_49", "test_route_capability_providers",
    "test_rpc_skeleton_template", "test_sanction_datetime_47", "test_scan_waiting_902", "test_script_discipline",
    "test_secondstop_anchor_831", "test_self_cap_smoke", "test_selfcheck_stamps_536", "test_session_start_notice_25",
    "test_skill_invocation", "test_skill_md_contract_537", "test_skill_subcommand_ux", "test_specialist_contract_expansion",
    "test_specialist_gate", "test_state_anchor", "test_state_anchor_hyp_pointers_528", "test_status_contract_607",
    "test_status_defs", "test_status_upgrade_536", "test_strategy_metrics", "test_structural_check",
    "test_stuck_event_595", "test_subcommand_zeroarg_ux", "test_summary_discriminator_826", "test_summary_fake_826",
    "test_syspath_hygiene_671", "test_t0_capability_697", "test_taint_wiring", "test_terminal_superseded",
    "test_think_bets_711", "test_tick_rc_617", "test_tier_rules", "test_tool_first_proof_630",
    "test_tool_tiers_812", "test_tool_value_881", "test_toolchain_negotiation", "test_toolchain_next_action",
    "test_toolchain_stdio", "test_ttl_warn_613", "test_tuition_p4", "test_unidbg_harness_template",
    "test_update_index", "test_user_signal_capture_868", "test_v0_retirement_861", "test_v1_8_enforcement_gates",
    "test_value_flag_removed_51", "test_value_rebuild_107", "test_value_reconciliation_133", "test_value_replay",
    "test_value_shadow_gates", "test_verdict_scorer_contract", "test_verifier_blind", "test_verifier_identity_825",
    "test_verify_truth_609", "test_violation_capture_718", "test_vm_normalization_10", "test_warn_delegation_863f",
    "test_windowed_stalker_template", "test_windows_reserved_names", "test_winrate_curve_156", "test_wire_up_settings",
    "test_worker_death_resume_11", "test_worker_liveness_protocol", "test_worker_lookup_constitution_145", "test_workspace_export_540",
    "test_worktree_marker", "test_write_gate", "test_ws_layout_delegation_863c", "test_zero_output_fingerprint",})

SLOW_MODULES = frozenset({
    "test_acceptance",   # nested pinned smoke pytest run
    "test_load_lock",    # nested pytest probes of the machine-local lock
})

# routing tag only — see module docstring
DOCS_MODULES = frozenset({
    "test_agents_hygiene",
    "test_agents_lint",
    "test_doc_sync",
    "test_docsync_589_563",
    "test_contracts_drift_102",
    "test_governance_docs_784",
})
