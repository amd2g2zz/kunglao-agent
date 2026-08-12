# kunglao-agent 吸收与缺陷研究 Round 2

> 9 subagent 代码深挖综合(5 第一批: reverse-skill/AgentSec/auto-re-agent/ctf-skills + kunglao 能力全貌; 3 第二批: 架构/实现可靠性/死代码批判审查)。
> 所有关键判断指向 file:line 证据。本轮纠正了 Round 1 基于 README 的"覆盖完整"判断。

## 核心结论(诚实修正)

前几轮"成熟完整"判断被代码深挖推翻。kunglao = **功能丰富 + 真 bug + 架构债 + 误导性死代码(纸老虎)**。

四维共识别: ① 外部盲点 6 ② 实现缺陷 15 ③ 架构问题 17 ④ 死代码 10 类。

---

## ① 外部盲点(C8-C13, 4 仓库代码深挖, kunglao 完全没有且 C1-C7 未覆盖)

| ID | change | 来源 | 治本点 |
|---|---|---|---|
| C8 | fact 引用图(KnowledgeGraph 式) | auto-re-agent | fact 间引用/重叠/影响传播/邻域矛盾(kunglao claim_deps 是 claim 级, cites 是 fact 对级, 无图查询) |
| C9 | 结构完整性 CI 门(合并) | reverse-skill + ctf-skills | re-library 孤儿/断裂链接/锚点(ctf 4 不变量) + INDEX vs fact drift(reverse-skill) + specialist 描述可区分性回归(ctf)。C6 结构前提 |
| C10 | 状态机硬前置 + deterministic 转换 | AgentSec | PROVEN 转换机器化前置(blind_gate 事前阻止 vs 现事后降级) + exit code 直接驱动不可覆盖动作 |
| C11 | 数据化 task 路由 + 双向 Pivot | reverse-skill + ctf-skills | regex must/mustAll/exclude + 回归(task 级 vs C7 claim 级) + specialist 间假设错误路由 + 双向性测试 |
| C12 | 优雅能力降级 | auto-re-agent | 预声明能力(BackendCapabilities 探测) + 降级消费 vs deferred 阻塞(收敛速度) |
| C13 | 操作级 audit log | AgentSec | 谁何时 DEFERRED/覆盖 PROVEN/改权重(ledger 是收敛轨迹非操作级) |

**中价值并入既有**: evidence provenance 字段→C2 / write-once→C5 / 借口反驳表+prompt注意力→C6 / publication projection→C3 / 文件级路由+归因→C6

---

## ② 实现缺陷(F1-F15, 2 HIGH + 5 MED + 8 LOW)

### HIGH
- **F1**: `hooks/worker_budget.py:26` `TERMINAL_STATUS` 5-value 副本(**从不 import `status_defs`**), `status_defs.py:71` 是 8-value(#34 统一化 STALE/SUPERSEDED/DEAD)。`dispatch_gate`/`worker_pulse`/`state_anchor` 同样不 import。后果: hook 把 DEAD/SUPERSEDED/STALE 当 open → tier gate 错误阻塞。`test_status_defs.py` guard **只扫 scripts/ 不扫 hooks/**。
- **F2**: `schemas/decide-output.json` required(top_actions/blocked/failure_blocked/stale/drifts/explore_mode/selfcheck)与 `convergence_check.decide()` 实际输出(open_claims/partial_facts/...)完全不匹配 → schema 契约失效。

### MEDIUM
- **F8**: `kunglao_record.py:113-136` record_event 全量重写 ledger(read-modify-write)→ 并发竞态, 后写者覆盖先写者, 事件丢失。`_atomic_write` retry 是 bug。对比 `_append_ledger` 用 append 模式(正确)。
- **F13**: failure-modes F1-F18 **只覆盖 LLM 行为, 不覆盖脚本实现 bug**(如 F1/F8)。enforcement gates 列表无 schema 验证。
- **F3**: 三层 decide(kunglao-decide.py 190行 / kunglao.py cmd_decide / convergence_check)角色混淆, 输出 schema 不同, kunglao.py 声称 byte-identical 但不完整。
- **F5**: `priority.py rank_claims` 无回归测试(只 priority_ratio), failure-blocked/leverage-v2/gateway 无覆盖。
- **F6**: DISPATCH_VERIFIER→SATURATED 边界, partials+0-free 时文本误导。

### LOW
- F4: 16 test_*.py 错放 scripts/(pytest.ini 无 testpaths, CI 漏)
- F7: _note_layer_gaps spec 偏差(已知 DESIGN 顶 NOTE)
- F9: _set_claim_status 行解析脆弱(flow style/key 无空格/部分 id 匹配)
- F10: fact_id 三种格式(F-NNN / F<16hex> / F<NNN>-<slug>)不统一
- F11: kunglao-decide 异常写 poison row(open_count=-1)→ 假 flatline/churn
- F12: blind_gate record_dissent 用废弃 utcnow()
- F14: convergence_check 文件不存在返回 exit 64(不在 0-4 文档范围)
- F15: claim_migrator fail-closed 无 --override 恢复路径

---

## ③ 架构问题(D1-D17, 4 HIGH + 9 MED + 4 LOW)

### HIGH
- **D14**: 全局规则 `kunglao-convergence-loop.md` §7 硬禁止只 3 条(SKILL 5 条), **缺 VM-only HOST_FORBIDDEN_TOOLS** → compact 后唯一契约, orchestrator 可能在 host 执行样本 = **安全风险**。
- **D2**: 状态文件实际 **15+**(task_spec/claim-register/claim_deps/analysis_state/global_plan/progress/_INDEX/ledger/memory/blockers + .hook_state/.heartbeat/.agent-snapshot/.agent-events/task-oracle/converge-checklist)+ hooks/ 都不 import status_defs(与 F1 交叉)。
- **D6**: maker-checker **FAIL_CLOSED 三重**(blind/contradiction/inference)任一不可用阻塞 PROVEN, 与 guardrails self_caveat 降级矛盾 → **死锁**(与 F15 交叉)。
- **D1**: 契约三源(SKILL 560/DESIGN v1.8.2/全局规则 71)无机械仲裁, 全局规则不完整。

### MEDIUM
- **D8**: openspec **42+ planned**(非 7+), 无 lifecycle tracking。
- **D5**: convergence exit code advisory 非 mandatory(DISPATCH=1 无 hook 强制 must-dispatch)= F1 idle 根因。
- **D10**: PROVEN-INITIAL→FULL 硬编码(≥2 tier 或 ≥5min 多 VM)→ anti-debug/非 VM 永久不收敛。
- **D17**: 设计假设非 PE/ELF 失效(Go garble/.NET/firmware/Rust 无 specialist → meta-deferred)。
- **D3**: hook 交互非线性(worker_budget 12 子检查, 每次 dispatch 5+ subprocess, Windows 慢) + exit code 冲突(pulse BLOCKED=2 vs budget REJECT=2) + FAIL_OPEN/CLOSED 不统一。
- **D4**: SKILL.md SNR(560 行, ~200 行行为契约 + 360 行参考)。
- **D7**: worktree `.wt-*` glob 隐式耦合(无 marker, user .wt-backup 误计)。
- **D9**: DESIGN.md v1.8.2 永久落后 SKILL(v1.9.x)→ rationale 丢失。
- **D11**: decision-rights matrix 标"机械"但实际 LLM-invoked(convergence_check 非 hook)。
- **D12**: specialist 选择隐式知识(无 registry.yaml, 加新 specialist 改 5 处自然语言)。

### LOW
- D13: hook FAIL_OPEN/CLOSED 无文档化 rationale / D15: 并发写入无全局序列化 / D16: 18 F-row 只 8 有机械 enforcement

---

## ④ 死代码/未用机制(10 类, 量化)

### HIGH waste
1. **9 gates 未接入**(纸老虎): plan_drift_detector / stale_blocker_prune / claim_expiry / provenance_gate / report_consistency_check / explore_gate / failure_analysis_gate(非hook) / premature_termination_detect(非hook) / ask_for_direction_gate(非hook) — 写了 + 测了 + telemetry 装饰, 但**从不被 hook 或主流程调用**。误导: 看起来有保护其实不做。
2. **6-8 openspec planned 无实现**: convergence-completeness / tick-drift / isolation-first / phase9 / distill-heldout
3. **eval 不在 CI**: release-check.yml 只 pytest + receipt, kunglao_eval.py 手动跑

### MEDIUM waste
4. verdict-redteam agent 未 dispatch(不在 SKILL 路由)
5. orchestrator-proactive-loop learned skill 未 recall(SKILL/hooks 不引用)
6. outcome_capture 未 hook(OUTCOME 行无消费者, priority 不消费)
7. memory_capture 幻影 hook(ALL_HOOKS 列出无实现)

### LOW waste
8. confidence_schema 死代码(zero runtime imports, 只 own test)
9. 18 marginal scripts(CLI/test 有但不接 live loop)
10. re-library 只 1 agent 读(kunglao-worker; by design, 但 C6 召回更关键)

**纠正**: 双版本文件(kunglao-verify/kunglao_verify 等)是 **intentional CLI wrapper + module**, 非混乱(纠正 B2)。3 lifecycle 监控(agent_watch/worker_pulse/heartbeat_touch)不重叠(不同抽象层, 纠正 U9)。

---

## 自主拍板修复优先级

### P0 immediate-fix(真 bug + 安全风险, 先 file 5 issue)
1. **D14** 全局规则补 VM-only HOST_FORBIDDEN_TOOLS + 机械校验全局规则⊆SKILL
2. **D2/F1** hooks/ 全部 import status_defs(删 5-value 副本) + test guard 扫 hooks/
3. **D6/F15** maker-checker 统一降级(FAIL_CLOSED 三重 + self_caveat 矛盾)
4. **F8** record_event 改 append 模式(并发事件丢失)
5. **F2** decide-output.json schema 分裂或对齐

### P1 误导性纸老虎(逐个判接入 vs 删)
6. 9 gates 未接入 — 判 selective(HARD_PAUSE) vs orphan, 接入或删
7. eval 加 CI(release-check.yml)
8. memory_capture 幻影 hook 删或实现
9. outcome_capture 接入或删
10. verdict-redteam 接入路由或删 + proactive-loop 集成或归档 + confidence_schema 集成 fact schema 或删

### P2 架构债(中期)
D1 契约单源 / D8 openspec lifecycle / D5 must-dispatch hook / D3 gate chain + 统一 FAIL 策略 / D10 PROVEN-FULL 替代条件 / D17 非 PE/ELF 降级 / D9 DESIGN reconciliation / D4 SKILL 拆 RUNTIME/REFERENCE

### P3 外部吸收(C8-C13 新能力)
C9 结构 CI 门 → C10 状态机前置 → C8 fact 引用图 → C11 数据化路由 → C12 降级 → C13 audit

### P4 cleanup
F4 test 迁移 + pytest.ini testpaths / F3 decide 角色澄清 / F5 rank_claims 回归 / F10 fact_id 统一 / F11-F14 小修 / B 文件组织

---

## 退化红线(所有修复共享)

- 收敛循环 / maker-checker 盲验 / 字节锚定 + 数字口径 / failure-modes 18 F-row(不变)
- 修 9 gates: 不盲目全接入, 判 selective(HARD_PAUSE tier) vs orphan
- D14 修全局规则: 保持蒸馏版 < 150 行, 机械校验非复制全文
- C12 降级: 降级证据 ≠ 完整 PROVEN(标 PROVEN-INITIAL 非 FULL)
- C10 deterministic: LLM 仍做策略决策, deterministic 只绑状态转换门
- C11 数据化路由: regex 只用于工具链类型分类, 不改 claim priority

---

## 执行模式(继承 /goal)

- 一 issue 一 PR 一 branch 一 worktree(worktree dir MUST = `kunglao-agent` for test_status_defs.py)
- SDD(openspec) + TDD(RED→GREEN), 合 dev 不合 master
- 最多 5 并行隔离 subagent, maker-checker(subagent=maker, orchestrator=checker 盲验)
- 预存 2 test 失败永不修: test_acceptance_overall_passes / test_skill_lte_500_lines
- dev = 86cbdbc(当前), 本地部署已同步

## Source Ledger

- 第一批 subagent: reverse-skill / AgentSec / auto-re-agent / ctf-skills 代码深挖 + kunglao 能力全貌(7 类)
- 第二批 subagent: kunglao 架构(D1-D17) / 实现可靠性(F1-F15) / 死代码量化(10 类)
- 定点确认: knowledge_graph.py(C8) / blind_gate.py 392行(C10) / malware-phase-routing.md 30行(C11) / .github/workflows 只 release-check.yml(F1-eval)
