# scripts/ — script inventory & governance map

Audit deliverable for issue #230 (scripts governance, 2026-08-13).
Every `.py` in this directory is classified by role and by where it is
referenced. The reference map below is the definitive answer to "who uses
this script?" — used to keep documentation, hooks, CI, and tests in sync.

- **Total scripts**: 169 (`scripts/*.py` at #866 recon, 2026-09-02; the
  historical #318-era count lineage — 72 cataloged at #318 close; +15 by
  #236/#271/#287/#304/#309/#316; +4 by #310/#331/#336 merged after the
  #320 snapshot; +1 by #409; +2 by #477 — is superseded by the live
  per-script provenance in the tables below).
- **Orphans — test semantics**: 0 — every script has at least one live
  reference (tests/ count as references; a script referenced only by tests
  is categorized `TEST`, not orphan). This is the #230-era metric.
- **Orphans — production semantics (#866)**: 29 unwired of 205 subjects
  (scripts 29 + tools 0, ~6.0k LOC) as of the 2026-09-02 post-866-b sweep —
  the tools side was fully dispositioned by PR 866-b (all 27 pre-gate CLIs
  registered: tools/_INDEX.yaml registry mention + skills/references
  teaching; the 27-key gate baseline `devkit/.discovery-gate-baseline.txt`
  cleared to zero); the remaining scripts-side debt is ledgered in the
  "#866 unwired-live disposition ledger" section below — the honest
  counter-metric: a script/tool is production-wired
  only if hooks/, skills/, agents/, devkit/, CI, or the execution registry
  `tools/_INDEX.yaml` reaches it (transitively via real consumption
  edges); tests/openspec/docs/references, the describe-only ext index,
  and both manifests (deploy-manifest now ships 100% of both trees, so
  presence there carries zero wiring signal) do NOT count. Reproduce and
  re-baseline with:
  `python scripts/relib_audit.py --production .` (add `--json` for the
  machine payload; the unwired list is the #866 disposition ledger —
  register-or-retire per issue #866, not documentation debt).
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
| `kunglao_wait.py` | worker 自旋锁 CLI — 交付后 sleep 轮询 + WAIT flag 续写（mtime 心跳），signal 到达 UNWAIT 回工作（rc 0），K 轮无 signal self-kill 释放槽位（rc 3/4）；9 agents 统一接入 | agents, hooks/dispatch_gate (signal), tests |
| `init_channel_default.py` | default local-channel resolution + KUNGLAO_CHANNEL env contract (#727); static-only probe for local + explicit-channel-never-auto-switch; consumed by kunglao-init.write_init_report(channel=) | kunglao-init, tests |
| `kunglao-init.py` | workspace init + re-init guard + deploy_env (#478: hooks/agents/mcp-record/skills + env-manifest ledger) | CLI, tests |
| `kunglao-decide.py` | M1 DECIDE — convergence_check.decide + explore_gate + priority_ratio | CLI, tests |
| `kunglao-verify.py` | M3 VERIFY entry (thin wrapper → `kunglao_verify.py`) | CLI, tests |
| `kunglao-record.py` | M4 RECORD entry (thin wrapper → `kunglao_record.py`) | CLI, tests |
| `kunglao-monitor.py` | M5 MONITOR — heartbeat + reconcile + stuck/health watch | CLI, tests |
| `kunglao-digest.py` | digest mechanical generation (thin wrapper → `digest_build.py`) | CLI, tests |
| `kunglao-eval.py` | eval harness CLI (thin wrapper → `kunglao_eval.py`) | CLI, CI, tests |
| `_entry.py` | the shared `__main__` dispatcher for the kunglao-* entries (#585/#660): `run(globals())` resolves + calls main(); entry modules keep module-level main(argv) (#370) | lib(8 entries) |
| `error_response.py` | action-error classifier (issue #448): vmrun / init-exit / tool-install signatures → STOP/ASK/RETRY-ONCE/ESCALATE (UNCLASSIFIED = ASK, rc=2) | lib(2), CLI, tests |
| `mcp_probe.py` | MCP supply probe (#316): per-type manifest + ~/.claude.json + .mcp.json probe; `--mcp-inventory` enumeration face (#515): registered servers → `mcp__<server>__*` prefixes + manifest tier (read-only, secret-safe; consumed by `tools/ext-scan.py --with-mcp`) | CLI, lib(2), tests |

## Core executors (loop machinery — invoked by hooks / CLI / other scripts)

| Script | Role | Referenced from |
| --- | --- | --- |
| `convergence_check.py` | convergence decision (DISPATCH/DISPATCH_VERIFIER/SATURATED/BLOCKED/CONVERGED) — the every-turn gate | hooks, CLI, lib(2), tests |
| `convergence_health.py` | ledger-based HEALTHY/STALLED/SPINNING verdicts | hooks, CLI, lib(2), tests |
| `anomaly_detector.py` | anomaly observation layer (#663): score_fact 3-dim + scan_anomalies + baseline corpus load (fail-open); feeds convergence ANOMALY_DETECTED; observe_taint taint-concentration observations (#692 WP5) | lib(1: convergence_check), CLI, tests |
| `rho_checkpoint.py` | P2 ρ progress signal + V/D/ETA (#823): per-PQ grade expectation, σ(w·x+b) priors fallback chain, decide() value_signals attach (flag-gated shadow) | lib(1: convergence_check), tests |
| `rho_verifier.py` | #823-P2 ρ_t dense signal shadow — pluggable backend (deterministic default, green with no LLM), checkpoint (rho,z) pairing ledger face, Platt data path (single-source re-export) | lib(1: rho_checkpoint), tests |
| `value_replay.py` | P1 offline replay settlement (#823): z_self four-channel relabel, evidence-gated reward score, bucket priors value-priors.yaml, replay-validation gate | CLI, lib(2: rho_checkpoint, priority_ratio), tests |
| `infeasible_signal.py` | P3 doomed-trajectory signal (#823/#815): flat V × zero marginal discovery → infeasible_candidate event (shadow) | lib, tests |
| `infeasible_proposal.py` | #815 早停接线 — gated INFEASIBLE 立案（阶梯 L1/L2/L3+清单+wake_condition 要件, REJECT 零变更）+ wake 复活面; DEFERRED 自动退出派发 | hooks, tests |
| `zero_output_fingerprint.py` | P3 same-type action thrash circuit (#823/#634): (tool,target) hash streaks N=3 zero belief change → break + failure_analysis inject (shadow) | lib, tests |
| `hypothesis_seeder.py` | PQ scaffold seeder (#662) + apkid candidate extension (#669): seeds `pq:<qid>` hypotheses, appends `apkid:<cat>:<rule>` / `taint:<cat>:<api>` candidates | lib(1: digest_build), CLI, tests |
| `apkid_scanner.py` | T1 apkid pre-scan wrapper (#669): fingerprints packer/compiler/obfuscator/anti-* into evidence/apkid.json (fail-open) | CLI, tests |
| `provider_health.py` | runtime provider-failure memory (#692 WP4): record/query <ws>/provider_health.json, 24h window, fail-open; consumed by route_capability selection next round | CLI, lib(1: route_capability), tests |
| `priority_ratio.py` | sanctioned v1.9.29 dispatch ranker (R4); #823 A3 feed-side terms always-on (#51) | lib(3), tests |
| `relib_audit.py` | re-library 审查器 (#817) — 孤儿/tracker 残留/声明行缺失三类检查 + quarantine 可逆移动 + 质量度量; _INDEX.yaml pin 契约(改库必 re-pin) | hooks, tests |
| `route_capability.py` | deterministic feature→capability router (#278 P4-b; #310 specialist-first gating) | lib(1), tests |
| `failure_analysis_gate.py` | 3-question method-failure reasoning gate (no NEGATIVE without it) | hooks, CLI, lib(2), tests |
| `hook_activation.py` | THE canonical hook registration entry (#445): register_hooks/--wire-up + post-write self-check + tier activation | hooks, CLI, lib(6), tests |
| `env_check.py` | environment readiness gate (venv/toolchain/VM channel) | hooks, CLI, tests |
| `env_manifest.py` | env-facts.yaml single source (issue #450): five fact families + LayoutConventions, priority chain yaml > task-spec > defaults; --render/--probe | CLI, lib(3), tests |
| `env_state_probe.py` | env-state liveness snapshot writer → runs/env-state.json (tick step 9; #475) | lib(2), tests |
| `env_repair_l1.py` | L1 deterministic env repair (adb-reconnect/vm-rediscover/mcp-rehandshake; idempotent, safe no-op; #475) | CLI, tests |
| `heartbeat.py` | convergence-gated heartbeat bookkeeping (lib for hook_activation) | lib(1), tests |
| `heartbeat_tick.py` | heartbeat tick runner (hook-invoked + kunglao.py) | hooks, lib(1), tests |
| `heartbeat_loop_prompt.py` | loop-prompt generator for the tick loop | hooks, tests |
| `loop_scheduler.py` | durable /loop registration writer (#754): idempotent upsert of the kunglao-heartbeat entry into <ws>/.claude/scheduled_tasks.json (foreign entries preserved, unreadable/unrecognized files sidecar-backed); absorbs #616, rejects #618 crontab route | CLI, lib(1: heartbeat_loop_prompt), tests |
| `hooks_selfcheck.py` | hook registration self-check (runs hook_activation) | lib(1), tests |
| `verify_status_watch.py` | verify-stamp disk-vs-stream reconciliation — the anti-sed tamper watch (#718) | heartbeat_tick, tests |
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
| `backtrack_loop.py` | 回溯环宿主 (#882) — 三触点（dispatch 微回溯 O(1) 前车之鉴块 / register_proven_gate 结算回放 runs/<ts>-retro-<claim>.md / heartbeat_tick 策略回溯门控）+ 四产出（结算行消费 / 链回放 / 模式报告+hypothesis_store 假设种子 / 修订提案议程 retro-agenda-*.md，**不自动执行**）+ 座舱三字段（backtrack_lag/unattributed_rate/pending_proposals → cockpit_summary → statusline 快照）；kunglao-decide 经 --policy 挂入复活 | heartbeat_tick, hooks/dispatch_gate, scripts/register_proven_gate, statusline_snapshot, tuition_curve, tests |
| `blind_gate.py` | blind-verification gate on promotion | hooks, lib(1), tests |
| `calibration_gate.py` | calibration/confidence gate | tests |
| `completion_gate.py` | completion transaction gate | hooks, tests |
| `cost_gate.py` | cost tier gate (advisory/pause/HARD_PAUSE) | tests |
| `explore_gate.py` | explore-before-dispatch gate (lib for kunglao-decide) | lib(1), tests |
| `fact_contradiction_gate.py` | cross-fact contradiction detection | hooks, lib(3), tests |
| `plan_drift_detector.py` | plan↔reality drift detection | hooks, tests |
| `plan_reviser.py` | plan state machine + suggest_revision triggers + incremental revision segments | tests, SKILL contract |
| `premature_termination_detect.py` | premature-done declaration detector | lib(1), tests |
| `provenance_gate.py` | PROVEN provenance chain gate | lib(1), tests |
| `reuse_gate.py` | evidence-reuse gate | tests |
| `search_gate.py` | search-before-work gate | tests |
| `troubleshooting_gate.py` | report completeness gate | tests |
| `review_gate.py` | review evidence mint/check (key-init/mint/check) | tests, docs |
| `adversarial_gate.py` | verdict-scorer 签名前对抗门 — open challenge/链断/summary 鉴权失败/轮数低于 register 高水位一律 BLOCKED，无 override | tests |
| `adversarial_loop.py` | 对抗闭环 orchestrator CLI — begin/challenge/rebuttal/verifier-call/status/arbitrate/verify-run（相持后仲裁 + verifier 按需征召） | tests |
| `challenge_ledger.py` | 对抗账本数据层 — challenge/rebuttal/arbitration 结构化落盘（grounding 门禁 + 断言冻结 + 5 轮硬闸 + append-only HMAC 链 + keyed summary） | tests |
| `report_consistency_check.py` | report↔evidence consistency check | tests, docs |
| `write_gate.py` | write-side gate auditor (#236) — maker-checker stamp re-verification + independent anchors + defer references re-checkable | lib(1), tests |

## State & lifecycle (claim/ledger/blocker maintenance)

| Script | Role | Referenced from |
| --- | --- | --- |
| `kunglao_upgrade.py` | workspace upgrade via declarative convergence (#726): 5 idempotent migrations + version wall + user-data sha256 iron rule + dry-run/snapshot; dispatched from `kunglao upgrade` subcommand | kunglao, tests |
| `claim_expiry.py` | STALE demotion after inactivity | lib(1), tests |
| `complete_teardown.py` | full teardown helper | tests |
| `dead_letter.py` | DEAD status + dead-letter quarantine | hooks, lib(1), tests |
| `feedback.py` | feedback inbox processing | tests |
| `obligation_discovery.py` | obligation discovery from claims | lib(1), tests |
| `outcome_capture.py` | outcome ledger capture (R6) | lib(2), tests |
| `reconcile_intents.py` | plan↔claims intent reconciliation | tests |
| `reconcile_workers.py` | worker status reconciliation | lib(1), tests |
| `refutation_propagate.py` | refutation propagation across facts | tests |
| `register_proven_gate.py` | claim-register →PROVEN evidence gate (#819) — latest verify=passes + red-team ran (≠REFUTED) or justified waiver; wired as write_guard register leg | hooks/write_guard, tests |
| `stale_blocker_prune.py` | stale blocker pruning | lib(1), tests |
| `worker_death.py` | #11 worker-death event + artifact snapshot — dead-worker classification (silent > DEAD_WORKER_MINUTES) consumed by convergence_check._act_stuck_workers; writes runs/.worker-death-<stem>.json (claim/last-activity/已完成产物清单) as the resume signal; idempotent per worker | convergence_check, tests |
| `status_defs.py` | claim status constants — single source of truth | hooks, lib(13), tests |
| `statusline_snapshot.py` | #883 statusline health-snapshot writer: probe registry + semantic state machine + atomic pre-write of runs/.kunglao-statusline.json per tick (Node reads it, zero spawn); attached from heartbeat_tick, fail-open | heartbeat_tick step 11, tests |
| `liveness_policy.py` | liveness/staleness minutes constants — single source (#597: stuck 20 / heartbeat 35 / activation+env 30 / kicker+margins 10, values adjudicated) | hooks, lib(9), tests |
| `tier_rules.py` | claim tier rules | tests |
| `loop_state.py` | loop state persistence | lib(1), tests |
| `update_index.py` | facts/_INDEX.md maintenance | tools, tests |
| `lint_facts.py` | facts × malware-veri-notes aligned frontmatter lint (#336) | CLI, tests |
| `migrate_facts.py` | old-format facts → aligned schema migration (#336) | CLI, tests |
| `mechanism_scheduler.py` | 机制调度器 (#878) — mechanisms.yaml 注册表（schema `kunglao.mechanisms/1`，trigger.gate/cost_class/cockpit_signal 三项上线前置缺一即拒，**不入册不许跑**；册坏 fail-closed 整轮拒跑 + `mech_reject` 落账）+ 单宿主调度（heartbeat_tick 唯一时间宿主，廉价门先行→cost_class 排队→单 tick time cap，默认 90s `KUNGLAO_MECH_BUDGET_S`；runner 注入保留 tick 逐脚本 seam）+ 账本事件总线（settlement/stall/plan_review 事件类 byte-offset 增量读，镜像 #883 有界读惯例）+ 座舱健康段（每机制 {last_run,next_eligible,drops} → statusline mechanisms 段 + mechanism_health 探针 [mech] 码）；一条命令 `--plan` 答"什么机制在什么时候跑"；`--check`/`--status`/`--run` 同文件；**只调度提案类机制，不改任何决策权归属**（hooks 通道不迁移） | heartbeat_tick, statusline_snapshot, tests |
| `mechanisms.yaml` | 机制注册表数据 (#878) — 13 条目（8 机制入口裁定 + tick advisory 子步骤迁入），schema/词表由 mechanism_scheduler.validate_registry 机械校验（tests/test_mechanism_scheduler_878.py 守卫） | mechanism_scheduler, tests |
| `retract_claim.py` | RETRACTED terminal state + dependency blast-radius reopening (#331) | CLI, tests |
| `progress_report.py` | one-block progress report | tests |
| `init_state.py` | init-completeness single source of truth (#304) | hooks, lib(3), tests |
| `template_version.py` | workspace template version stamp — write/verify/upgrade-warning (#536) | kunglao-init, hooks_selfcheck, env_check, kunglao-status, kunglao-resume, tests |
| `local_gate.py` | 本地质量门统一入口 (#873) — __file__ 自定位 cwd 免疫；pytest+ext-scan+deploy_manifest 一条命令 | CLI |
| `rollup.py` | terminal-transition write loop — claim→outcome_capture+lessons+narrative+checkpoint (#524) | tests |
| `hypothesis_store.py` | hypothesis layer carrier (#528) — H-*.md parse + open→refuted/superseded state machine over `hypotheses/` | digest_build (sec_g), hooks/state_anchor, kunglao-init stub, tests |
| `verifier_identity.py` | verifier machine-identity extraction + verdict anchoring (#825) — md header / l2 field; ledger verdict_anchor append-only | register_proven_gate, write_gate, tests |
| `dual_gate.py` | #868 双门验证引擎 — redteam 反例切分(disclosed/held-out) + verifier 正向核验 + 失败签名分流(CEGAR/Goodhart) + N=3 升级; 宪法隔离只出裁决 | hooks, tests |
| `user_signal.py` | #868 用户信号核心 — 本体三分类（意愿/事实/元）路由 + 意愿域 repin 生效 + 事实域双门立案 + 座舱数据面 | hooks, tests |
| `notes_writer.py` | notes/ result-layer writer (#528) — supersedes-chain enforcement + verify_status reset on corrections | tests; write-path contract behind hooks/write_guard (#532) |
| `write_guard_unlock.py` | #820 连坐解锁通道 — lint 打击面按目标文件归因; unlock/quarantine/list 三命令全落账 | hooks, tests |
| `carrier_consistency.py` | 跨载体一致性门 (#829) — register/_INDEX/facts/notes 五规则断言; decide() CONVERGED 前置降级 + carrier_drift 落账 | hooks, tests |
| `mission_ledger.py` | 主线欠账表 + V_m (#823-P1, shadow) — PQ 三态 CRUD + 防傻断言(边角料全 PROVEN→增量=0) + mission_snapshot 落盘 | tests |
| `mission_stall.py` | 主线停滞指纹 + PARK 合法化 (#634) — ΔV_m 平坦×K 检测 / PARK 必带 wake_condition / revive 通道(落账 claim_revive) | convergence_check, hooks(carrier rule f), tests |
| `notes_discriminator.py` | notes 结构判别器 (#834) — 复制即拒/零引用/悬空引用三规则; completion_gate NOTES_FAKE 面 (would-PASS 拦截, 双笼 fail-open) | hooks, tests |
| `encoding_lint.py` | 裸 IO 编码扫描器 (#811) — AST 版 write_text/read_text/open/subprocess 无 encoding 检出; 残留清零后挂机械门防复发 | tests, CI |
| `emit_gate.py` | EMIT_ACTIONS 双向门 (#880) — 正向: 词表孤儿扫描(每个 action 须有 ≥1 生产发射者, quoted-literal 宽网); 反向: emit-site literal 未注册扫描(#459 pattern 表); CI 挂 tests/test_emit_gate_880.py | tests, CI |
| `utf8_boot.py` | CLI 入口 UTF-8 双保险 (#811) — PYTHONUTF8 setdefault + stdout/stderr reconfigure; 全入口 __main__ 接线 | hooks, tests |
| `optimizer_core.py` | #833 θ 数值通道 — PARAM_SPEC(opt-theta-v1)+宪法隔离(CONSTITUTIONAL_KEYS 不可入 spec/提案)+SPSA(衰减步长)+replay_loss 规则近似+提案 JSON(只出提案不生效) | tests |
| `optimizer_bandit.py` | #833 机制开关通道 — β-Bernoulli 后验(arm=机制×泳道)+ledger 归因+demotion_queue(四阶段门降级候选,不直接生效) | tests |
| `plan_stages.py` | plan 阶段模型 (#822) — runs/plan-stages.yaml 工件 + BIG_BANG_PLAN 检测(校验面 fail-closed) + 盘点裁决 maintain/adjust/replan(adjust/replan 必带 reason) + plan_review 落账 | CLI, tests |
| `think_seat.py` | waiting-period THINK seat (#759) — mechanical wait detection + runs/.think-<ts>.md three-section artifact + stall counter (suggested_searches); orchestrator fills the thinking | heartbeat_tick step 10, tests |
| `tuition_curve.py` | 学费曲线聚合器 + 座舱 V/D/ETA 数据面 (#823-P4) — settled rho_pair → mission 记录, stratum 聚合, got_cheaper 判定, cockpit_summary | tests |
| `tuition_refit.py` | Platt 系数重拟合面 (#823-P4) — ledger (ρ,z_self) 对 → fit_platt → optimizer_core 提案（只提案不生效, 宪法隔离继承） | tests |

## Observability sidecar (issue #287)

| Script | Role | Referenced from |
| --- | --- | --- |
| `kunglao-status.py` | status panel CLI — renders claims board + active workers + convergence trend (SKILL.md §Status panel; ANSI auto-degrade) | docs, tests |
| `kunglao_status.py` | disk-rendered TUI status panel implementation | lib(1), tests |
| `kunglao_log.py` | structured JSONL event log | lib(4), tests |
| `kunglao_resume.py` | /kunglao-agent:resume — crash-recovery brief (read-only: health/13-source summary/open-hypothesis pointers/table-lookup next-step; issue #466, #528) | CLI, tests |
| `heartbeat_touch.py` | lightweight heartbeat timestamp refresh — companion to heartbeat_tick.py (one-shot, no side effects; #534) | hooks, tests |
| `strategy_metrics.py` | strategy convergence four metrics — regret / cost-to-slope / P(faster|hit) / competence (#529) | lib(1), tests |
| `summary_discriminator.py` | summary 结构合同判别器 (#826) — R1 完成词需暂定节 / R2 不确定性传播(fact-id 或 WAIVED) / R3 未答主问题节; completion_gate SUMMARY_FAKE 面 (would-PASS 拦截, 双笼 fail-open) | hooks, tests |

## Support libraries & utilities

| Script | Role | Referenced from |
| --- | --- | --- |
| `gate_telemetry.py` | gate telemetry wrapper (decorator + ledger) | lib(8) |
| `content_hash.py` | fact/content hashing (golden capture too) | tools, tests |
| `normalize_trace.py` | dynamic trace normalization | tools, tests |
| `fixture_excerpt_lint.py` | fixture excerpt lint (standalone CLI) | tests, docs |
| `references_recall.py` | references scored-recall CLI over the layered index — scenario → primary/supplementary; keyword → top-K ranked rows with score (no file dumps); `--list-categories` / `--scene-map` / `--ws` | tests, docs |
| `recall_metrics.py` | recall 注入质量度量面 (#814) — record/summarize over runs/.recall-metrics.jsonl (injected/skipped/no_match)；#833 优化器输入口 | hooks, tests |
| `retirement_gate.py` | 机器绑定治理门 (#861) — RETIRED 正则散副本 + DEPRECATED 活体 caller 检查; 基线棘轮（已知债务挂账 #867）| hooks, tests |
| `wire_up_settings.py` | hook REGISTRY + deprecated alias -> hook_activation.register_hooks (#445; retirement #446) | hooks, lib(1), tests |
| `install_reference.py` | multi-install reference hygiene — scanner/rewriter for stale `~/.claude/skills/<name>/` refs across `.claude/settings.json` + `CLAUDE.md` (#752; library-only: hook_activation verifier + kunglao_upgrade sweep) | scripts, tests |
| `claudemd_frame.py` | CLAUDE.md three-segment framing — G2 frame-marker pair + G3 collect-and-merge split/classify/assemble primitives (#755; library-only: init write_claudemd wrap + kunglao_upgrade merge item) | scripts, tests |
| `shell_defaults.py` | reusable CLI: idempotent shell env-default line management (check/apply/remove, powershell+bash; #276) | lib(1), tests |
| `template_gen.py` | deterministic script-template generator CLI (templates/scripts/*.tmpl; exit 2/3/4/5, #278) | templates, tests, docs |
| `template_render.py` | shared {{param}} render + leftover-detection engine (single source for template_gen + kunglao-init, #362) | lib(2), tests |
| `hook_exit_codes.py` | hook exit-code constants | hooks, tests |
| `dispatch_context.py` | structured dispatch context block (fact snapshot + priority state + validated capability + plan + siblings; #527) | lib(3), tests |
| `lessons_telemetry.py` | per-lesson CBM quartet + utility score + tombstone (#526) | tests |
| `lib_kunglao.py` | shared helpers for hooks/ + scripts/ | hooks, tests |
| `_hooks_path.py` | scripts-side bridge to hooks/_path_hygiene — the canonical by-path loader delegation (#863 Family B, #671 authority; guarded append, never reorders) | hooks, lib(13), tests |
| `ws_layout.py` | manifest-aware workspace resolution single source — resolve_quiet/resolve_strict (#863 Family C; B2 fix: all 9 former _resolve_ws copies honor layout.workspace_dir/claim_register) | lib(9), tests |
| `harness_common.py` | harness-wide time-stamp single source (#863 Family F) — utc_now (tz-aware datetime) / utc_now_z ("YYYY-MM-DDTHH:MM:SSZ", byte-equivalent collapse of the 43 strftime/isoformat copies) / utc_now_iso (+00:00 variant); 53 former def copies delegate | lib(52: scripts+hooks/heartbeat_touch+tools/static trio), tests |
| `env_file.py` | CLAUDE_ENV_FILE loader — single sanctioned entry (#309, #304 init linkage) | tests |
| `toolchain.py` | type-aware toolchain probe matrix (#304) with probe tiers presence/liveness/capability + jdwp handshake (#474) | lib(1), tests, docs |
| `tool_tiers.py` | 工具族档位表加载/选择/契约注入 (#812) — 场景×工具→四档降级链（#670 估算 + C-006 实录），dispatch_context 可选键 | dispatch_context, tests |
| `tool_value.py` | 工具价值聚合器 (#881) — 四输入（toolfirst 行/facts steps/结算+runs outcome/operation label）按 claim id join → (scene,operation,tool) cite/burn/reject + β-Bernoulli utility（先验=静态链 rank）；runs/.tool-value.json 表；CLI --report 查询；接线 tool_tiers 排序与 recall_files rerank | tool_tiers, hooks/recall_inject, dispatch_context, tests |
| `toolchain_install.py` | ask-then-install: (manager, package) data x pkg_detect detection + MCP registration + re-probe + env-facts installed ledger (#408, #477) | CLI, lib(1), tests |
| `pkg_detect.py` | package-manager detection (winget/choco/scoop/brew/apt/dnf/apk/pacman/pip/uv/npm; which-first + known-path, read-only) + unpacked-ghidra half-state (#477) | CLI, lib(1), tests |
| `deploy_shim.py` | device-side idempotent deploy (frida-server rename+custom port / android-server, re-probe gated, installed ledger) + #462 one-off shim records under scripts/shims/ (#477) | CLI, tests |
| `toolchain_negotiation.py` | init negotiation menu (issue #451): install/use-path/skip/degrade, apply_answers validate-then-act | CLI, lib(1), tests |
| `decision_pending.py` | pending-decision list schema + serialization (stdout JSON, exit 8, `--resolve` answers; shared intake channel #455/#449/#451) | lib(2), tests |
| `log_setup.py` | shared stdlib-logging facade (FileHandler + stderr StreamHandler, idempotent; #454/#459) | lib, tests |
| `platform_paths.py` | platform-correct analyzeHeadless + venv python resolution (#409) | lib(2), tests |
| `chunker.py` | length-measured batch chunking (#309) | tests |
| `cost_estimate.py` | pre-dispatch cost estimator (#309) | lib(1), tests |
| `event_taxonomy.py` | 25-class event taxonomy (#309) | tests |
| `recov_metrics.py` | symbol/type recovery quality metrics (#309) | lib(1), tests |
| `tool_error_policy.py` | same-tool consecutive-error hysteresis (#309) | tests |

## Experiment bench (kunglao-bench — #823 AB-VALUE)

| Script | Role | Referenced from |
| --- | --- | --- |
| `bench_intake.py` | fail-closed manifest gate (sha256/recency/truth-source/outside-repo) + --check-safety 3-check pre-run refusal | tests, bench_runner, COMPLIANCE |
| `bench_answer_key.py` | per-stratum key schemas, canonical IOC normalization, mechanical matchers, leak-free task-spec PQs | lib(1: bench_grade), tests |
| `bench_tokens.py` | transcript → token/wall/human-turn receipt (the bench's only metering piece) | lib, tests |
| `bench_runner.py` | lane runner — deterministic seed plans, locked budget table, terminal done/timeout/crashed receipts | CLI, tests |
| `bench_grade.py` | zero-LLM L1 scoring + z_self + arm-blind sealed map + 12-case oracle selfcheck | CLI, tests |
| `bench_redteam.py` | L2 divergent-only arm-blind red-team pipeline (briefs + merge-back) | CLI, tests |
| `bench_analyze.py` | stdlib statistics — exact McNemar, Wilcoxon, tuition slopes, H1-H4 pre-registered verdicts, --demo | CLI, tests |
| `answer_key_lint.py` | answer-key quality gate: schema + PQ-to-top-level consistency + IOC normalizability | CLI |
| `intake_one.py` | single manifest entry immediate validation (sha256/first_seen/sources/pq lists) | CLI |
| `intake_promise.py` | Phase 0 预扫描 promise 块 (#813) — apkid/DIE 探测状态显式记录 + 混淆先验(apkid.json 同源提取) + java 可达性判定(#807 死胡同面)；task_spec `promise:` 键合并 / runs 降级 | kunglao-init, CLI, tests |

## Release & CI support

| Script | Role | Referenced from |
| --- | --- | --- |
| `release_receipt.py` | release receipt generation + CLI probe | CI, tests |
| `release_check_selfcheck.py` | release-check self-verification | CI |
| `check_global_rule_subset.py` | global-rule subset compliance check | CI, tests |
| `kunglao_export.py` | workspace export by zone (contract_carriers/evidence/scratch) + manifest (#540, D5) | tests |
| `structural_check.py` | repo structure + broken-link + index drift check | CI, tests |
| `run_test_matrix.py` | matrix-style scoped pytest runs (issue-lane suites); canonical full-suite entry stays the README Quick-start pytest line | lane tooling, tests |
| `deploy_manifest.py` | deployment manifest builder/verifier - hooks+agents+scaffold closure, per-file sha256 (newline-normalized); feeds init copy-deploy and upgrade refresh | CLI, tests |
| `deployed_refresh.py` | upgrade-side framework-copy refresh - overwrite semantics with forensic backups (runs/deploy-backup-*), orphan double-confirm prune; migration item face for #783 | tests, CLI via kunglao_upgrade chain |

| `re_pin_references.py` | references/_INDEX.yaml pin regeneration — re-run after ANY references/ edit (drift fails test_replay_gate) | docs, tests |

## #866 unwired-live disposition ledger (PR 866-b, 2026-09-02)

Production-semantics verdict for the scripts side of the #866 sweep
(`python scripts/relib_audit.py --production .` -> 29 unwired scripts, tools
side cleared to 0). Per-issue disposition rule: live value -> register or
annotate; DEAD without in-flight binding -> retire. **Retirement count: 0** —
every script below is issue- or protocol-backed, test-covered, and touched
inside the last 30 days; the issue's "outdated" bucket came back empty on
per-script evidence. Two former members flipped to production-wired by the
registration itself: `content_hash.py` + `reconcile_intents.py` are consumed
by the now-registered `tools/auxiliary/capture_golden.py` golden cases
(F-13/F-15) — lib_closure, not ledger material anymore.

| Script | Binding (issue/change, status) | Disposition |
| --- | --- | --- |
| `bench_intake.py` / `bench_answer_key.py` / `bench_tokens.py` / `bench_runner.py` / `bench_grade.py` / `bench_redteam.py` / `bench_analyze.py` | #823 AB-VALUE (B1-B7), MERGED — kunglao-bench pipeline; `bench_runner` is the lane entry | REGISTERED as the kunglao-bench harness; consumer = bench runs, not repo runtime. Follow-up value channel: #881 aggregation |
| `infeasible_proposal.py` | #815 early-stop wiring, MERGED — INFEASIBLE-as-claim proposal semantics (L1/L2/L3 + evidence gate) | REGISTERED (proposal generator); consumer = orchestrator loop on recovery-ladder exhaustion |
| `plan_stages.py` | #822 plan stage model, MERGED — `runs/plan-stages.yaml` + BIG_BANG detection + inventory rulings | REGISTERED; consumer = plan-phase ritual |
| `optimizer_core.py` / `optimizer_bandit.py` | #833, MERGED — theta (SPSA-on-replay) + beta-Bernoulli arm accounting; constitutional isolation (proposal-only, zero auto-apply paths) | REGISTERED; consumers = proposal/derad queue faces; value wiring in #881 |
| `tuition_refit.py` | #823-P4, MERGED — Platt refit proposals from `rho_pair` ledger rows (proposal-only) | REGISTERED; consumer = #881 aggregation side |
| `emit_gate.py` | #880, MERGED — EMIT vocabulary double-ended gate (write-side actions must have >=1 emitter; read-side consumers must exist) | REGISTERED (CI-runnable checker); consumer = release-check extension candidate |
| `search_gate.py` | user-painpoint-driven (search-before-research gate; no issue ref) | REGISTERED as orchestrator-loop gate; consumer = post-worker fact promotion |
| `reuse_gate.py` | user-painpoint-driven (reuse-before-recompute; no issue ref) | REGISTERED as dispatch-side gate; consumer = dispatch audit chain |
| `complete_teardown.py` | search-problem abstraction (user-verbatim driven; no issue ref) — 1-call operator chain returning a fact bundle | REGISTERED as search-operator entry; consumer = deep-search scenario |
| `strategy_metrics.py` | #529, MERGED — convergence four metrics, pure functions atop `priority_ratio` | REGISTERED as lib+CLI; consumer = convergence reporting |
| `acceptance_check.py` | #6/#689, MERGED — end-to-end static acceptance | REGISTERED as milestone-acceptance entry (same family as `run_test_matrix.py`) |
| `run_test_matrix.py` | v0.1.3 acceptance orchestrator (`docs/v0.1.3-test-plan.md`) | REGISTERED as milestone-acceptance entry |
| `report_consistency_check.py` | #57, MERGED — report-INTERNAL contradiction checker | REGISTERED; consumer = report QA phase (hr-report pipeline sibling) |
| `fixture_excerpt_lint.py` | #58, MERGED — condensed-excerpt conversion/speculation lint | REGISTERED; consumer = report QA phase |
| `chunker.py` | #309, MERGED — length-measured batch chunking (kong absorption) | REGISTERED as utility lib; consumer = batch dispatch flows |
| `env_file.py` | #309, MERGED — CLAUDE_ENV_FILE loader (stdlib parser) | REGISTERED as init-path lib; consumer = env bootstrap |
| `kunglao_export.py` | #540, MERGED — workspace export by zone | REGISTERED as workspace utility CLI |
| `local_gate.py` | dev-loop infra (2026-09-01): cwd-immune unified local quality gate — pytest + Gate 9 + ext-scan + deploy-manifest verify (Gate 9 wired by PR 866-a) | REGISTERED as the per-PR local-gate entry (plan §0.5 workflow) |
| `encoding_lint.py` | #811, MERGED — AST bare-IO encoding scanner over the production IO face | REGISTERED as dev-loop linter; CI/local_gate wiring = follow-up card |
| `error_response.py` | #448, MERGED — mechanical layer of `references/error-response-taxonomy.md` (the taxonomy doc is the live LLM channel; zero code importers — 866-a verified) | REGISTERED as the taxonomy's enforcement layer; CLI wiring = follow-up card |
| `answer_key_lint.py` / `intake_one.py` | SUSPECT — docstrings bind to `COLLECTION_PROTOCOL.md` §5 steps 5/7, which does NOT exist anywhere in the repo; zero tests, zero consumers; function overlap with the merged `bench_answer_key.validate_key` (#823) | SUSPECT, not DEAD (answer-key files from `bench_answer_key` may still be linted manually). Retirement candidate for the follow-up governance card after owner ruling on the missing protocol doc |
