# scripts/ — script inventory & governance map

Audit deliverable for issue #230 (scripts governance, 2026-08-13).
Every `.py` in this directory is classified by role and by where it is
referenced. The reference map below is the definitive answer to "who uses
this script?" — used to keep documentation, hooks, CI, and tests in sync.

- **Total scripts**: 92 (72 cataloged at #318 close; +15 by #236/#271/#287/
  #304/#309/#316; +4 by #310/#331/#336 merged after the #320 snapshot;
  +1 by #409 — per-script provenance in the tables below).
- **Orphans**: 0 — every script has at least one live reference
  (tests/ count as references; a script referenced only by tests is
  categorized `TEST`, not orphan).
- **Broken references**: 0 after #230 (all intra-script imports resolve;
  all hook/CI/subprocess targets exist; SKILL.md-mentioned scripts exist).

Legend for "Referenced from": `hooks` = hooks/*.py invokes it ·
`CI` = .github/workflows runs it · `CLI` = documented in SKILL.md /
release-manifest.yaml as a user-facing entry · `lib` = imported by other
scripts (count in parens) · `tests` = exercised by tests/ only.

## CLI family (8) — unified surface (SKILL.md §CLI, release-manifest.yaml)

| Script | Role | Referenced from |
| --- | --- | --- |
| `kunglao.py` | unified entry point — subcommands compose script functions (JSON + exit codes frozen) | CLI, tests, release_receipt |
| `kunglao-init.py` | workspace init + re-init guard | CLI, tests |
| `kunglao-decide.py` | M1 DECIDE — convergence_check.decide + explore_gate + priority_ratio | CLI, tests |
| `kunglao-verify.py` | M3 VERIFY entry (thin wrapper → `kunglao_verify.py`) | CLI, tests |
| `kunglao-record.py` | M4 RECORD entry (thin wrapper → `kunglao_record.py`) | CLI, tests |
| `kunglao-monitor.py` | M5 MONITOR — heartbeat + reconcile + stuck/health watch | CLI, tests |
| `kunglao-digest.py` | digest mechanical generation (thin wrapper → `digest_build.py`) | CLI, tests |
| `kunglao-eval.py` | eval harness CLI (thin wrapper → `kunglao_eval.py`) | CLI, CI, tests |
| `mcp_probe.py` | MCP supply probe (#316): per-type manifest + ~/.claude.json + .mcp.json probe | CLI, lib(2), tests |

## Core executors (loop machinery — invoked by hooks / CLI / other scripts)

| Script | Role | Referenced from |
| --- | --- | --- |
| `convergence_check.py` | convergence decision (DISPATCH/DISPATCH_VERIFIER/SATURATED/BLOCKED/CONVERGED) — the every-turn gate | hooks, CLI, lib(2), tests |
| `convergence_health.py` | ledger-based HEALTHY/STALLED/SPINNING verdicts | hooks, CLI, lib(2), tests |
| `priority.py` | legacy dispatch ranker (v1 direct-cap formula, kept for compatibility) | hooks, lib(1), tests |
| `priority_ratio.py` | sanctioned v1.9.29 dispatch ranker (R4) | lib(3), tests |
| `route_capability.py` | deterministic feature→capability router (#278 P4-b; #310 specialist-first gating) | lib(1), tests |
| `failure_analysis_gate.py` | 3-question method-failure reasoning gate (no NEGATIVE without it) | hooks, CLI, lib(2), tests |
| `hook_activation.py` | THE canonical hook registration entry (#445): register_hooks/--wire-up + post-write self-check + tier activation | hooks, CLI, lib(6), tests |
| `env_check.py` | environment readiness gate (venv/toolchain/VM channel) | hooks, CLI, tests |
| `heartbeat.py` | convergence-gated heartbeat bookkeeping (lib for hook_activation) | lib(1), tests |
| `heartbeat_tick.py` | heartbeat tick runner (hook-invoked + kunglao.py) | hooks, lib(1), tests |
| `heartbeat_loop_prompt.py` | loop-prompt generator for the tick loop | hooks, tests |
| `hooks_selfcheck.py` | hook registration self-check (runs hook_activation) | lib(1), tests |
| `external_kicker.py` | external scheduler kicker (schtasks/crontab-friendly) | tests |
| `kunglao_record.py` | RECORD implementation module (ledger writes) | lib(2), tests |
| `kunglao_verify.py` | L1 mechanical verify implementation (reproduce + byte-exact) | lib(3), tests |
| `kunglao_eval.py` | eval harness implementation (episode runner + scorer) | lib(2), CI, tests |
| `digest_build.py` | digest generation implementation | lib(2), tests |
| `acceptance_check.py` | end-to-end acceptance criteria runner | tests |

## Enforcement gates (reject/allow decision scripts)

| Script | Role | Referenced from |
| --- | --- | --- |
| `active_intervention.py` | stuck-worker intervention decisions | lib(1), tests |
| `ask_for_direction_gate.py` | orchestrator ask-back-pattern gate | lib(1), tests |
| `backtrack_gate.py` | stuck worker backtrack decision | hooks, lib(1), tests |
| `blind_gate.py` | blind-verification gate on promotion | hooks, lib(1), tests |
| `calibration_gate.py` | calibration/confidence gate | tests |
| `completion_gate.py` | completion transaction gate | hooks, tests |
| `cost_gate.py` | cost tier gate (advisory/pause/HARD_PAUSE) | tests |
| `explore_gate.py` | explore-before-dispatch gate (lib for kunglao-decide) | lib(1), tests |
| `fact_contradiction_gate.py` | cross-fact contradiction detection | hooks, lib(3), tests |
| `plan_drift_detector.py` | plan↔reality drift detection | hooks, tests |
| `premature_termination_detect.py` | premature-done declaration detector | lib(1), tests |
| `provenance_gate.py` | PROVEN provenance chain gate | lib(1), tests |
| `reuse_gate.py` | evidence-reuse gate | tests |
| `search_gate.py` | search-before-work gate | tests |
| `troubleshooting_gate.py` | report completeness gate | tests |
| `review_gate.py` | review evidence mint/check (key-init/mint/check) | tests, docs |
| `report_consistency_check.py` | report↔evidence consistency check | tests, docs |
| `write_gate.py` | write-side gate auditor (#236) — maker-checker stamp re-verification + independent anchors + defer references re-checkable | lib(1), tests |

## State & lifecycle (claim/ledger/blocker maintenance)

| Script | Role | Referenced from |
| --- | --- | --- |
| `claim_expiry.py` | STALE demotion after inactivity | lib(1), tests |
| `complete_teardown.py` | full teardown helper | tests |
| `dead_letter.py` | DEAD status + dead-letter quarantine | hooks, lib(1), tests |
| `feedback.py` | feedback inbox processing | tests |
| `obligation_discovery.py` | obligation discovery from claims | lib(1), tests |
| `outcome_capture.py` | outcome ledger capture (R6) | lib(2), tests |
| `reconcile_intents.py` | plan↔claims intent reconciliation | tests |
| `reconcile_workers.py` | worker status reconciliation | lib(1), tests |
| `refutation_propagate.py` | refutation propagation across facts | tests |
| `stale_blocker_prune.py` | stale blocker pruning | lib(1), tests |
| `status_defs.py` | claim status constants — single source of truth | hooks, lib(13), tests |
| `tier_rules.py` | claim tier rules | tests |
| `loop_state.py` | loop state persistence | lib(1), tests |
| `update_index.py` | facts/_INDEX.md maintenance | tools, tests |
| `lint_facts.py` | facts × malware-veri-notes aligned frontmatter lint (#336) | CLI, tests |
| `migrate_facts.py` | old-format facts → aligned schema migration (#336) | CLI, tests |
| `retract_claim.py` | RETRACTED terminal state + dependency blast-radius reopening (#331) | CLI, tests |
| `progress_report.py` | one-block progress report | tests |
| `init_state.py` | init-completeness single source of truth (#304) | hooks, lib(3), tests |

## Observability sidecar (issue #287)

| Script | Role | Referenced from |
| --- | --- | --- |
| `kunglao-status.py` | status panel CLI — renders claims board + active workers + convergence trend (SKILL.md §Status panel; ANSI auto-degrade) | docs, tests |
| `kunglao_status.py` | disk-rendered TUI status panel implementation | lib(1), tests |
| `kunglao_log.py` | structured JSONL event log | lib(4), tests |

## Support libraries & utilities

| Script | Role | Referenced from |
| --- | --- | --- |
| `gate_telemetry.py` | gate telemetry wrapper (decorator + ledger) | lib(8) |
| `confidence_schema.py` | ICD-203 confidence schema | tests |
| `content_hash.py` | fact/content hashing (golden capture too) | tools, tests |
| `normalize_trace.py` | dynamic trace normalization | tools, tests |
| `fixture_excerpt_lint.py` | fixture excerpt lint (standalone CLI) | tests, docs |
| `references_recall.py` | references scored-recall CLI over the layered index — scenario → primary/supplementary; keyword → top-K ranked rows with score (no file dumps); `--list-categories` / `--scene-map` | tests, docs |
| `wire_up_settings.py` | hook REGISTRY + deprecated alias -> hook_activation.register_hooks (#445; retirement #446) | hooks, lib(1), tests |
| `shell_defaults.py` | reusable CLI: idempotent shell env-default line management (check/apply/remove, powershell+bash; #276) | lib(1), tests |
| `template_gen.py` | deterministic script-template generator CLI (templates/scripts/*.tmpl; exit 2/3/4/5, #278) | templates, tests, docs |
| `template_render.py` | shared {{param}} render + leftover-detection engine (single source for template_gen + kunglao-init, #362) | lib(2), tests |
| `hook_exit_codes.py` | hook exit-code constants | hooks, tests |
| `lib_kunglao.py` | shared helpers for hooks/ + scripts/ | hooks, tests |
| `env_file.py` | CLAUDE_ENV_FILE loader — single sanctioned entry (#309, #304 init linkage) | tests |
| `toolchain.py` | type-aware toolchain probe matrix (#304) with probe tiers presence/liveness/capability + jdwp handshake (#474) | lib(1), tests, docs |
| `toolchain_install.py` | ask-then-install: per-item install commands by platform + MCP registration + re-probe (#408) | CLI, lib(1), tests |
| `decision_pending.py` | pending-decision list schema + serialization (stdout JSON, exit 8, `--resolve` answers; shared intake channel #455/#449/#451) | lib(2), tests |
| `log_setup.py` | shared stdlib-logging facade (FileHandler + stderr StreamHandler, idempotent; #454/#459) | lib, tests |
| `platform_paths.py` | platform-correct analyzeHeadless + venv python resolution (#409) | lib(2), tests |
| `chunker.py` | length-measured batch chunking (#309) | tests |
| `cost_estimate.py` | pre-dispatch cost estimator (#309) | lib(1), tests |
| `event_taxonomy.py` | 25-class event taxonomy (#309) | tests |
| `function_kg.py` | minimal function-level knowledge graph (#309) | tests |
| `recov_metrics.py` | symbol/type recovery quality metrics (#309) | lib(1), tests |
| `tool_error_policy.py` | same-tool consecutive-error hysteresis (#309) | tests |

## Release & CI support

| Script | Role | Referenced from |
| --- | --- | --- |
| `release_receipt.py` | release receipt generation + CLI probe | CI, tests |
| `release_check_selfcheck.py` | release-check self-verification | CI |
| `check_global_rule_subset.py` | global-rule subset compliance check | CI, tests |
| `structural_check.py` | repo structure + broken-link + index drift check | CI, tests |
| `re_pin_references.py` | references/_INDEX.yaml pin regeneration — re-run after ANY references/ edit (drift fails test_replay_gate) | docs, tests |
