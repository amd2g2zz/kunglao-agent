# scripts/ — script inventory & governance map

Audit deliverable for issue #230 (scripts governance, 2026-08-13).
Every `.py` in this directory is classified by role and by where it is
referenced. The reference map below is the definitive answer to "who uses
this script?" — used to keep documentation, hooks, CI, and tests in sync.

- **Total scripts**: 72 (70 at #230 close; +1 `references_recall.py` by #229,
  +1 `shell_defaults.py` by #276).
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

## Core executors (loop machinery — invoked by hooks / CLI / other scripts)

| Script | Role | Referenced from |
| --- | --- | --- |
| `convergence_check.py` | convergence decision (DISPATCH/DISPATCH_VERIFIER/SATURATED/BLOCKED/CONVERGED) — the every-turn gate | hooks, CLI, lib(2), tests |
| `convergence_health.py` | ledger-based HEALTHY/STALLED/SPINNING verdicts | hooks, CLI, lib(2), tests |
| `priority.py` | legacy dispatch ranker (v1 direct-cap formula, kept for compatibility) | hooks, lib(1), tests |
| `priority_ratio.py` | sanctioned v1.9.29 dispatch ranker (R4) | lib(3), tests |
| `failure_analysis_gate.py` | 3-question method-failure reasoning gate (no NEGATIVE without it) | hooks, CLI, lib(2), tests |
| `hook_activation.py` | hook wire-up + tier activation (--wire-up/--renew/--heartbeat-*) | hooks, CLI, lib(6), tests |
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
| `ask_for_direction_gate.py` | orchestrator 反问-pattern gate | lib(1), tests |
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
| `progress_report.py` | one-block progress report | tests |

## Support libraries & utilities

| Script | Role | Referenced from |
| --- | --- | --- |
| `gate_telemetry.py` | gate telemetry wrapper (decorator + ledger) | lib(8) |
| `confidence_schema.py` | ICD-203 confidence schema | tests |
| `content_hash.py` | fact/content hashing (golden capture too) | tools, tests |
| `normalize_trace.py` | dynamic trace normalization | tools, tests |
| `fixture_excerpt_lint.py` | fixture excerpt lint (standalone CLI) | tests, docs |
| `references_recall.py` | references progressive-disclosure recall CLI — scene/category/filename → INDEX rows (no file dumps); `--list-categories` / `--scene-map` | tests, docs |
| `wire_up_settings.py` | hook settings registration (lib for hook_activation) | hooks, lib(1), tests |
| `shell_defaults.py` | reusable CLI: idempotent shell env-default line management (check/apply/remove, powershell+bash; #276) | lib(1), tests |
| `hook_exit_codes.py` | hook exit-code constants | hooks, tests |
| `lib_kunglao.py` | shared helpers for hooks/ + scripts/ | hooks, tests |

## Release & CI support

| Script | Role | Referenced from |
| --- | --- | --- |
| `release_receipt.py` | release receipt generation + CLI probe | CI, tests |
| `release_check_selfcheck.py` | release-check self-verification | CI |
| `check_global_rule_subset.py` | global-rule subset compliance check | CI, tests |
| `structural_check.py` | repo structure + broken-link + index drift check | CI, tests |

## Test support (referenced by tests/ only)

| Script | Role | Referenced from |
| --- | --- | --- |
| `fact_graph.py` | fact graph utilities | tests |
| `test_v1_8_enforcement_gates.py` | smoke launcher for the v1.8.x enforcement suite (suite itself in tests/) | CLI (SKILL.md smoke command) |
