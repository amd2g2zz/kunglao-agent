# ISSUE-SPECS — 16 个 P0 issue 的权威实施规格

> 本文档是 GitHub issues #191-#206 的**详细实施规格**（subagent 执行时以本文为准）。
> 每个 issue 一节：背景（内联事实+复现）、变更文件、任务步骤、验收命令、依赖。
> 完整 diff 级细节见同目录 `2026-08-13-false-closure-elimination.md`（Task N 引用）。
> 调度见 `GLOBAL-DEV-PLAN.md`。

**工作流约定（所有 PR 通用）：**
- TDD：先写失败测试 → 运行确认失败 → 最小实现 → 运行确认通过 → 提交
- 提交格式：`<type>(#<issue>): <描述>`（type ∈ fix/feat/docs/ci/test）
- 分支：`fix/147-<issue>-<slug>`；PR 标题 `fix(#<issue>): <标题>`，body 首行 `Fixes #<issue>`
- 测试命令一律 `.venv/bin/python -m pytest`（系统 python 无 yaml）
- **PR 提交后若 CI/评审失败：仔细阅读错误输出，修复后推送到同一分支，不要另开 PR**

---

## ISSUE #191 — 修复 CI YAML 缩进（release-check.yml line 52-58）

**背景**：研究报告 §8 实测：CI workflow 无法解析，structural check（#141）从未在 CI 真正执行，发布门形同虚设。

**复现**：
```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/release-check.yml'))"
# YAML ERROR: while parsing a block mapping, in line 52
# expected <block end>, but found '-', in line 58
```

**机制**：line 58 的 `- name: Structural integrity check` 缩进 8 空格（嵌入了 `Upload release receipt` 步骤的 `with:` 块内）。

**变更文件**：`.github/workflows/release-check.yml`

**任务**：
1. 把 line 58 的步骤移出 `with:` 块，缩进恢复 4 空格与兄弟步骤平级（`Upload` 步骤后加空行分隔）
2. 验证：`.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/release-check.yml')); print('OK')"` → `OK`
3. 提交 `ci(#191): fix release-check.yml indentation (step nesting broke YAML parse)`

**验收**：验证命令输出 `OK`

**依赖**：无（#197 编辑同一文件，本 issue 先合入）

---

## ISSUE #192 — 修复 candidate corpus digest 漂移

**背景**：`memory/candidates/corpus/manifest.json` 的 6 个 fixture digest 全部与磁盘不符。`memory/scripts/evaluate.py::verify_manifest()` 返回 false → held-out 评估永远 INCONCLUSIVE → 学习闭环从未产出 held-out receipt。

**复现**：
```bash
.venv/bin/python - <<'EOF'
import hashlib, json
m = json.load(open('memory/candidates/corpus/manifest.json'))
for rel, want in m['files'].items():
    got = hashlib.sha256(open(rel,'rb').read()).hexdigest()
    print(rel, 'OK' if got == want else f'MISMATCH')
EOF
# 预期当前: 6 行全部 MISMATCH
```

**机制**：#81/#87 更新 eval fixtures 内容时没有重算 manifest 的 sha256 pin。

**变更文件**：`memory/candidates/corpus/manifest.json`（只重算 `files` 节；fixture 内容不得修改）

**任务**：
1. 写失败测试 `tests/test_replay_gate.py::test_candidate_corpus_digests_match_files`（遍历 manifest.files，sha256 对比磁盘，断言无 mismatch）
2. 运行确认失败（6 mismatch）
3. 重算写回：`m["files"] = {rel: sha256(Path(rel).read_bytes()).hexdigest() for rel in m["files"]}`（fixture 缺失先 `git checkout -- eval/fixtures`）
4. 运行确认通过
5. 提交 `fix(#192): re-pin candidate corpus digests after fixture drift`

**验收**：测试通过；`verify_manifest()` 返回 True

**依赖**：无

---

## ISSUE #193 — structural_check 错误输出加 ERROR 前缀

**背景**：`scripts/structural_check.py` 的 BROKEN_LINK/MISSING_* 行无 `ERROR ` 前缀，CI grep 匹配不到。§2.5 "3 断链而 index 单测通过"的连锁后果。

**变更文件**：`scripts/structural_check.py` + `tests/test_replay_gate.py`

**任务**：
1. 写失败测试 `test_structural_check_error_lines_are_prefixed`（subprocess 跑 structural_check，断言 BROKEN_LINK 行以 `ERROR ` 开头）
2. 运行确认失败
3. 修改：`for b in broken: errors.append(b)` → `errors.append(f'ERROR {b}')`
4. 运行确认通过
5. 提交 `fix(#193): prefix structural errors with ERROR for grep-parseable CI`

**验收**：测试通过

**依赖**：无（与 #194 互补：#194 消除错误本身，本 issue 保证可见）

---

## ISSUE #194 — 修复 re-library 3 个断链

**背景**：`structural_check.py` 报 3 个 BROKEN_LINK（研究 §8 实证）：
1. `references/re-library/field-notes.md:3` → `[SKILL.md](SKILL.md)`，目标在仓库根 → `../SKILL.md`
2. `references/re-library/field-notes.md:411` → `[phishing-case-study.md](...)`，目标文件**全仓不存在** → 新建
3. `references/re-library/malware-analysis-quickstart.md:68` → `[README.md](README.md)` → `../../README.md`

**变更文件**：field-notes.md（2 处）、quickstart（1 处）、新建 `references/re-library/phishing-case-study.md`

**任务**：
1. 写失败测试 `test_no_broken_links_in_re_library`（subprocess 跑 structural_check，断言无 BROKEN_LINK）
2. 运行确认失败（3 条）
3. 修复 1：`../SKILL.md`
4. 新建 phishing-case-study.md（内容：F040 同主题 PROVEN 矛盾事故——F035/F040 同 routing 主题结论相反无 supersedes，教训：同 topic-key 集多 PROVEN 结论不一致必须显式 supersedes；完成前必须全局矛盾扫描；关联 `scripts/fact_contradiction_gate.py` + `scripts/completion_gate.py`）
5. 修复 3：`../../README.md`
6. 运行确认通过（`structural_check.py .` exit 0）
7. 提交 `docs(#194): fix 3 broken links in re-library`

**验收**：`structural_check.py .` exit 0 无 BROKEN_LINK

**依赖**：无（#198/#206 依赖本 issue）

---

## ISSUE #195 — provenance gate 接入 PROVEN 唯一迁移入口

**背景**：研究 §1 场景 3：`provenance_gate.check_provenance_gate` 存在（纯函数 checker 有完整单测），但 `kunglao_record.claim_migrator` 的 PROVEN 必经链**不调用它**——summary-only 事实照常晋升 PROVEN。§2.2 表中唯一"checker 存在但必经链=否"的 gate。

**复现**：
```bash
.venv/bin/python .research-tree/experiments/incident_replay.py
# "summary-without-raw-provenance": {
#   "provenance_gate_result": false,                 # checker 正确拒绝
#   "promotion_path_calls_provenance_gate": false,   # 必经链不调用它
#   "forbidden_outcome_observed": true }
```

**机制**：#78 给 PROVEN 加了 BLIND/contradiction/inference 三门（`scripts/kunglao_record.py`），provenance 从未 wire。

**变更文件**：`scripts/kunglao_record.py` + 新测试 `tests/test_provenance_wiring.py`

**任务**（完整测试代码见计划文档 Task 8）：
1. 写失败测试：fixture 中 BLIND sign-off 有效 + evidence 索引 sha256 故意错误（`SENTINEL_WRONG`）→ 断言 `kunglao_record.claim_migrator(ws, "C-001", "PROVEN", "orchestrator")` 返回拒绝且 register 状态非 PROVEN（actor 已核实：`ORCHESTRATOR_ACTORS = ("orchestrator", "main", "kunglao-orch")`）
2. 运行确认失败（当前迁移成功）
3. 修改 `claim_migrator`：在 inference-scope gate 块之后、`if not _set_claim_status(...)` 之前插入 provenance gate 块——**ImportError → `return (False, _required_gate_receipt("provenance_gate", exc, claim_id))`（fail-closed）；checker 运行时异常 → 降级 STAMP**（与三兄弟同模式）
4. 运行确认通过
5. 回归：`test_fix_98_deadlock.py test_fail_closed_gates.py test_v1_8_enforcement_gates.py` 全绿
6. 验证 replay #3 翻转（forbidden=false）
7. 提交 `fix(#195): wire provenance gate into the PROVEN migration path`

**验收**：测试通过；replay #3 forbidden=false；三门回归全绿

**依赖**：无

---

## ISSUE #196 — provenance_gate 补 CLI（F5）

**背景**：skills 审查 §12 F5：`provenance_gate.py` 无 argparse、无 `__main__`。与 #195 同一缺陷的两个视角。

**变更文件**：`scripts/provenance_gate.py`（追加 CLI）+ `tests/test_provenance_gate.py`（追加测试）

**任务**：
1. 写失败测试 `test_provenance_gate_cli_exits_nonzero_on_bad_ref`（subprocess 调 `scripts/provenance_gate.py <fact> <ws>`，eid E999 → 断言 exit 1 + 输出含 E999）
2. 运行确认失败
3. 追加 `main(argv)`（argparse：fact + ws 位置参数；输出 `OK/REJECTED: reason`；exit 0/1）+ `__main__`
4. 运行确认通过；`--help` exit 0
5. 提交 `feat(#196): provenance_gate CLI entry point (skills-review F5)`

**验收**：测试通过；CLI exit 语义正确

**依赖**：无

---

## ISSUE #197 — CI YAML repo-owned 自检

**背景**：CI 损坏只能线上发现。加 repo-owned YAML lint（#191 的教训：本地无复现手段）。

**变更文件**：新建 `scripts/release_check_selfcheck.py` + `.github/workflows/release-check.yml`

**任务**：
1. 新建 `release_check_selfcheck.py`（遍历 `.github/workflows/*.yml`，`yaml.safe_load`，错误输出行号到 stderr，exit 1 若有误——完整代码见计划文档 Task 10）
2. 验证：exit 0 无输出（#191 已修前提下）
3. workflow 在 `Set up Python` 后插入步骤 `CI YAML selfcheck (issue #147)`：`uv run python scripts/release_check_selfcheck.py`
4. 提交 `ci(#197): repo-owned YAML lint so CI breakage reproduces locally`

**验收**：故意改坏 yml 再跑 → exit 1 + 行号

**依赖**：**#191 先合入**（同一 workflow 文件）

---

## ISSUE #198 — 结构性参考索引（references/_INDEX.yaml + drift 检查）

**背景**：P2 的 recall 引擎需要机器可读索引前置。references/ 共 52 个 md，目前只有人类索引 `references/INDEX.md`，无脚本可消费入口（研究 §13.1）。

**变更文件**：新建 `references/_INDEX.yaml` + `scripts/structural_check.py` + `tests/test_replay_gate.py`（追加）

**任务**：
1. 写失败测试 `test_references_index_pins_all_reference_files`（每个 `references/**/*.md` 被 pin + digest 匹配 + structural_check 无 INDEX_DRIFT）
2. 运行确认失败（_INDEX.yaml 缺失）
3. 生成 `_INDEX.yaml`：schema `references-index/1`；`files` = 52 个 md 的 sha256 pin；`symptom_map` = F-row/症状 → 文件（F1/F5/B1c/PT1→failure-modes-lifecycle.md；F11/F12/W-15/W-27→failure-modes-monitoring.md；F14/F18→failure-modes-state.md；drift/spinning→convergence-loop.md；vm_network/dhcp→dynamic-re-tool-priority.md）
4. `structural_check.py` 加 `check_references_index_drift(root)`（缺索引/不可读/文件缺失/digest 不符 → ERROR 行），main() 接线
5. 运行确认通过
6. 提交 `feat(#198): machine-readable references index + structural drift check`

**验收**：52 文件全 pin；改任一 references md → structural_check 报 INDEX_DRIFT

**依赖**：**#194 先合入**（断链修复后 digest 才是最终态）

---

## ISSUE #199 — 移除 second-stop 无条件放行（hook 侧）

**背景**：研究 §1 场景 4：`hooks/completion_gate.py:85-88` 对 `stop_hook_active=true` 的第二次停止**无条件 return 0**。一次 block 后第二次停止直接放行。

**变更文件**：`hooks/completion_gate.py` + 新测试 `tests/test_completion_gate_optout.py`

**任务**（测试完整代码见计划文档 Task 12；注意 `.hook_state.json` 真实 schema 为 `ts/tier/phase/active_hooks/paused_hooks/user_override/expires_at`，参考 `tests/test_state_anchor.py:98-103`）：
1. 写失败测试：`_activated_state(ws)` helper + `test_second_stop_without_oracle_sanction_blocks`（oracle adjudication 为 `second_stop: false` → 断言 rc != 0）+ `test_second_stop_sanctioned_passes`（`second_stop: true + last_decision: PASS` → 断言 rc == 0）
2. 运行确认失败
3. 修改 `process_event`：删除无条件 `return 0`，改为读取 oracle 的 `adjudication.stop_hook_active`——仅 `second_stop: true 且 last_decision == "PASS"` 时 return 0；否则 fall through 到正常 judge 路径（block）
4. 运行确认通过（2 passed）
5. 提交 `fix(#199): remove unconditional second-stop pass-through`

**验收**：两测试通过

**依赖**：无（replay #4 的翻转由 #200 完成——本 issue 只改 shim）

---

## ISSUE #200 — no-oracle 放行收紧 + replay #4 fixture 修正

**背景**：两个事实（本 issue 必须一并修）：
1. `hooks/completion_gate.py::_resolve_workspace`（line 42-49）**以 task-oracle.yaml 存在为 workspace 标记**——"激活但无 oracle"的 workspace 无法解析 → 静默 return 0。这是 no-oracle 放行的真正机制。
2. `.research-tree/experiments/incident_replay.py` 的 replay #4 **`forbidden_outcome_observed` 被硬编码为 `True`**（从不重新计算），且 fixture 不是激活态 workspace——测的是 D9 放行而非真 bypass。

**变更文件**：`hooks/completion_gate.py` + `.research-tree/experiments/incident_replay.py` + `tests/test_completion_gate_optout.py`（追加）

**任务**（完整代码见计划文档 Task 13 修正版 + Task 17 的 replay 部分）：
1. 写失败测试：`test_activated_workspace_without_oracle_blocks`（激活态 + claim-register.yaml 无 oracle → 断言 rc != 0）+ `test_unactivated_dir_without_oracle_still_passes`（无任何 marker 的目录 → rc == 0，D9 不变）
2. 运行确认失败
3. `_resolve_workspace` 改为按 workspace MARKERS 解析（`claim-register.yaml` 或 `.hook_state.json` 存在即解析，不再以 oracle 为标记）
4. `process_event` 加 no-oracle 分支：激活态 + `task-oracle.yaml` 不存在 → 打印 block JSON + `return 3`
5. 运行确认通过（含 #199 的 2 个测试）
6. 修 replay #4：建 `activated_ws`（claim-register + 真实 hook_state + 未满足的 oracle）与 `activated_ws_no_oracle`（同但无 oracle）；`no_oracle_rc = process_event({"cwd": no_oracle_ws})`；`second_stop_rc = process_event({"cwd": activated_ws, "stop_hook_active": True})`；判定式改为 `forbidden_outcome_observed = (no_oracle_rc == 0 or second_stop_rc == 0)`（删除硬编码 True）
7. 运行 replay 确认翻转（forbidden=false）
8. 提交 `fix(#200): block activated-workspace-without-oracle + fix replay #4 fixture`

**验收**：4 测试通过；replay #4 forbidden=false（非硬编码）

**依赖**：**#199 先合入**

---

## ISSUE #201 — 模板 + oracle 模板（calibration + adjudication）

**背景**：交付门（#204）需要 task_spec 声明 calibration；second-stop 持久裁决（#199/#200）需要 task-oracle 标准形态。

**变更文件**：`templates/state/task_spec.yaml`（追加）+ 新建 `templates/state/task-oracle.yaml` + `tests/test_completion_gate_optout.py`（追加 2 测试）

**任务**：
1. 写失败测试：`test_task_spec_template_declares_calibration_requirement`（calibration.require_confidence/require_falsifier == true）+ `test_task_oracle_template_has_persistent_adjudication`（adjudication.stop_hook_active 含 second_stop 键）
2. 运行确认失败
3. `task_spec.yaml` 追加 `calibration:` 节（require_confidence: true / require_falsifier: true / confidence_scale: 0-1，注释：#147 交付 claim 必须带两者，否则视为未完成）
4. 新建 `task-oracle.yaml`（task_text / open_items / deferrals / adjudication.stop_hook_active.{second_stop,last_decision,last_decision_at}）
5. 运行确认通过
6. 提交 `feat(#201): calibration + oracle templates (persistent anti-loop anchor)`

**验收**：两模板测试通过

**依赖**：无

---

## ISSUE #202 — completion 全局矛盾重算（judge + decide）

**背景**：研究 §1 场景 2：两条同主题 PROVEN 事实结论相反（"payload is shellcode" vs "payload is not shellcode"）时，`decide()` 的 CONVERGED 分支不扫描全局矛盾、`judge()` 不重算——仍返回 CONVERGED。

**复现**：replay #2：`detected_conflicts` 非空 + `current_decision: CONVERGED` + forbidden=true

**机制**：`fact_contradiction_gate.scan_conflicts` 只被 `claim_migrator` 在单 promotion 时调用（且只查与该 claim 相关的 pair）；完成判定路径从不全局扫描。

**变更文件**：`scripts/completion_gate.py` + `scripts/convergence_check.py` + **新测试 `tests/test_completion_transaction.py`**（注意：新文件，不与 #199/#200/#201 的 `test_completion_gate_optout.py` 冲突）

**任务**（测试完整代码见计划文档 Task 15/16；fixture：F001/F002 均 PROVEN、同 sample_refs、结论相反、claim-register 两条 PROVEN 均 answer q1）：
1. 写失败测试：`test_judge_blocks_on_global_contradiction`（oracle 带 `workspace_path` → `cg.judge(oracle)` 断言 code != 0 且 reason 含 CONTRADICTION）+ `test_decide_downgrades_converged_on_contradiction`（断言 decision != CONVERGED 且 action 含 CONTRADICTION）
2. 运行确认失败
3. 修改 `scripts/completion_gate.py::judge` 函数体最前插入：有 `workspace_path` 时 `fact_contradiction_gate.scan_conflicts` 重算，有冲突 → `return (1, "GLOBAL CONTRADICTION: ...")`；异常 → fail-closed `return (1, ...)`（import guarded，无 workspace 时保持纯）
4. 修改 `scripts/convergence_check.py` CONVERGED 分支（`else:` 块）替换为：矛盾重算 → 有冲突 → `BLOCKED`；扫描异常 → fail-closed BLOCKED；干净 → CONVERGED
5. 运行确认通过
6. 回归：`test_convergence_completeness.py test_convergence_rules_file.py test_completion_gate.py` 全绿
7. 验证 replay #2 翻转
8. 提交 `fix(#202): completion transaction — zero global contradictions required for CONVERGED`

**验收**：新测试 + 回归全绿；replay #2 forbidden=false

**依赖**：无（#203 编辑同一 `else:` 分支，本 issue 先合入）

---

## ISSUE #203 — discovery 消费（obligation_discovery + decide 接入）

**背景**：研究 §1 场景 1：事实正文写明"发现 shellcode，后续 payload 未分析"时，只要没进 claim register，`decide()` 照常 CONVERGED（replay #1 实证）。

**变更文件**：新建 `scripts/obligation_discovery.py` + `scripts/convergence_check.py` + 新测试 `tests/test_obligation_discovery.py`

**任务**（完整代码见计划文档 Task 18/19）：
1. 新建 `obligation_discovery.py`：typed disclosure patterns（`shellcode`/`downstream payload`→`payload-analysis`；`next-stage`/`second-stage`→`next-stage`）+ follow-up 检测（"payload analyzed" 等跳过）+ `scan_discoveries(facts_dir, register_path)` 确定性扫描 + CLI（exit 0 无发现 / 1 有发现）。Materiality rejection 不在 P0 范围（docstring 注明：未来 MaterialityRejected 需要 reason+policy 版本，报告 §4.2）
2. 写测试：`test_shellcode_disclosure_creates_obligation`（1 条，type=shellcode，template=payload-analysis）+ `test_no_disclosure_no_obligation` + `test_decide_downgrades_when_disclosures_unconsumed`（断言 decision != CONVERGED 且 action 含 obligation）
3. 运行确认失败（decide 返回 CONVERGED）
4. 修改 `decide()`：在 #202 落地后的 `else:` 分支开头（contradiction 检查之前）插入 discovery 检查——有未消费发现 → `DISPATCH`；扫描异常 → fail-closed DISPATCH
5. 运行确认通过
6. 回归：`test_convergence_completeness.py test_convergence_rules_file.py` 全绿
7. 验证 replay #1 翻转
8. 提交 `fix(#203): CONVERGED requires discovery consumption`

**验收**：3 新测试 + 回归全绿；replay #1 forbidden=false

**依赖**：**#202 先合入**（同一 `else:` 分支）

---

## ISSUE #204 — 交付校准门（calibration_gate）

**背景**：无人值守目标：交付的每条 claim 必须带 confidence + falsifier，不携带视为未完成——"不静默错"的机械化（研究 §5 完成不变量补充）。当前 `templates/state/claim-register.yaml` 无这两个字段。

**变更文件**：新建 `scripts/calibration_gate.py` + 新测试 `tests/test_calibration_gate.py`

**任务**（完整代码见计划文档 Task 20）：
1. 写失败测试：`test_claim_with_confidence_and_falsifier_passes` / `test_claim_missing_confidence_fails`（reason 含 confidence）/ `test_claim_missing_falsifier_fails`（reason 含 falsifier）
2. 运行确认失败（ModuleNotFoundError）
3. 新建 `calibration_gate.py`：`check_claim(claim)`（confidence 存在 + float + [0,1] + falsifier 非空）+ `check_register(register)`（PROVEN/VERIFIED 全查）
4. 运行确认通过（3 passed）
5. 提交 `feat(#204): calibration gate — confidence + falsifier required for delivery`

**验收**：3 测试通过

**依赖**：无（与 #201 配合：模板声明要求，本 issue 提供执行）

---

## ISSUE #205 — SKILL.md 契约两段式（降级→回升）

**背景**：skills 审查 §12 F1：SKILL.md:97 决策表 CONVERGED 行承诺了代码未实现的完成判定，且引用的 `handoff-check.py` 全仓不存在（hallucination gap：契约超前于实现）。

**复现**：`grep -n "CONVERGED" SKILL.md` → line 97 含 "deliver only after handoff-check.py PASS"；`ls scripts/handoff-check.py` → 不存在

**变更文件**：`SKILL.md`（line 97，两段式）+ 新测试 `tests/test_replay_gate.py`

**阶段 1（降级，无依赖，立即执行）**：
1. 写失败测试 `test_converged_contract_names_real_limitations`：CONVERGED 行必须含 "contradiction"/"provenance"/"discovery" 三词 + 全文不含 "handoff-check.py"
2. 运行确认失败
3. 修改 line 97 为："claim loop done — but CONVERGED does NOT scan global contradictions, does NOT verify provenance lineage, and does NOT consume discoveries written in fact bodies (shellcode / next-stage payloads). Before delivering, re-run the completion transaction (convergence_check + completion_gate + global contradiction scan) and confirm zero unresolved obligations"
4. 运行确认通过
5. 提交 `fix(#205): downgrade CONVERGED contract to real semantics (research F1)`

**阶段 2（回升，依赖 #202/#203/#204 全部合入后）**：
6. 更新测试为回升语义（三词仍在行内即可）
7. 修改 line 97 为："claim loop done — CONVERGED now requires zero global contradictions, zero unconsumed discoveries, and PROVEN provenance (all recomputed in scripts/convergence_check.py + completion_gate.py). STOP dispatch; deliver"
8. 运行确认通过
9. 提交 `docs(#205): re-raise CONVERGED contract to match the completion transaction`

**验收**：契约与实现一致；测试通过；不再引用不存在的工具

**依赖**：阶段 1 无依赖；阶段 2 依赖 #202、#203、#204

---

## ISSUE #206 — release receipt 绑定知识库 revision

**背景**：研究 §4.5 第 4 条 + §2.5：`release-manifest.yaml` 不含 SKILL.md/references，receipt 无法绑定确切知识库版本。

**复现**：`grep -A3 "^assets:" release-manifest.yaml` → 只有 agents/hooks/templates

**变更文件**：`release-manifest.yaml` + `scripts/release_receipt.py` + `tests/test_replay_gate.py`（追加）

**任务**：
1. 写失败测试 `test_release_manifest_declares_skill_and_references`（assets.knowledge 含 SKILL.md；assets.references 含 references/）
2. 运行确认失败
3. manifest assets 追加 `knowledge: [SKILL.md]` + `references: [references/]`（注释：目录条目由 sha256_dir 消化）
4. `release_receipt.py::build_receipt` 的 assets 字典追加 `"knowledge"`（asset() 逐文件）与 `"references"`（目录用 `sha256_dir`）
5. 运行确认通过
6. 校验：`.venv/bin/python scripts/release_receipt.py --no-tests --check` → exit 0
7. 提交 `feat(#206): bind release receipt to knowledge-base revision`

**验收**：receipt 含 references digest + SKILL.md sha256；--check 通过

**依赖**：**#194 先合入**（references digest 在断链修复后才是最终态）
