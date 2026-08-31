# Tasks — issue #759 orchestrator 认知层 (+ #762 K3 收尾)

## 1. SDD

- [x] 1.1 `openspec/changes/issue-759-cognition/proposal.md` — #711 三条现场证据 + 用户裁决 2026-08-27
- [x] 1.2 `design.md` — D1 裁决/证据 / D2 代码锚+守门 / D3 THINK 席位 / D4 价值函数 / D5 K3 接线 / D6 主动触发器
- [x] 1.3 `tasks.md`（本文件）

## 2. T1 = H1 THINK 席位

- [x] 2.1 RED `tests/test_cognition_759.py`：think_seat 等待期检测（register 存在 +
      零 dispatchable）；产物三段 schema 落盘；非等待期不产 artifact；
      e2e tick `action_taken` 含 `.think-<ts>.md` 路径且文件存在；
      席位 stdout 不可解析 fail-open；SKILL 决策表 THINK 行存在
- [x] 2.2 GREEN scripts/think_seat.py + heartbeat_tick tick 链接线（advisory，
      rc 不进 alert）+ SKILL.md 决策表 THINK 行 + commit

## 3. T2 = H2 价值函数

- [x] 3.1 RED：value-weights 注入后排序反映（dos 分降 rce 升）；无文件 =
      全 1（旧公式逐字节）；损坏/非法值 fail-open；override > value_class 字段 >
      关键词分类；to_dict 增 weight；SKILL sanctioned 通道句存在
- [x] 3.2 GREEN priority_ratio（EvidenceView 单点加载 + score×weight 解析序）+
      SKILL.md 价值通道段 + commit

## 4. T2b = K3 接线（Closes #762）

- [x] 4.1 RED：note 标记 supersedes_hypothesis: H-N → H-N open→superseded
      （superseded_by=note id）；EMIT_ACTIONS 含 hypothesis_superseded 且实际
      事件行落盘；affected_claims 含本 claim + 同 competitor_group peer；
      缺指针/非 open 抛错；CLI --supersede-hyp 形态；兼容 supersedes: 目标在
      hypotheses/ 时接受；762 seam 测试升级为已接线断言
- [x] 4.2 GREEN notes_writer.note_supersedes_hypothesis 实装 + CLI +
      event_taxonomy 注册 + hooks/消费不动 + commit（PR body Closes #762）

## 5. T3 = H3 主动触发器

- [x] 5.1 RED：think-state stall_ticks≥THRESHOLD → think 产物含
      suggested_searches 非空（websearch + reference-library 各列）；
      进展归零 SKILL 执行契约句存在
- [x] 5.2 GREEN think_seat（stall 计数 + 种子行生成 cap 3）+ SKILL.md
      契约句 + commit

## 6. Close-out

- [x] 6.1 守门 grep 全扫 + 定向套件（test_cognition_759 + test_heartbeat* +
      test_priority* + test_notes_closure_762 + test_notes_supersedes_528 +
      test_event_stream_adoption）→ 净化 PATH 全套 → receipt → quality_gates → ruff
      （结果：定向 170 passed；净化全量 4273 passed / 8 failed——2 例
       env_drift_475-noop + toolchain-android_server 已在 origin/dev 基线
       同 invocation 复现（pre-existing 机器态），ext_index×2 因新增脚本使
       已提交 tools/_INDEX.ext.yaml 过期 → 按 gate 指引重新生成后转绿，
       ghidra_async-cleanup_all 独立复跑通过（机器负载 flake，与本波无关）；
       receipt --check ok；quality_gates 1/3/4 ALL-PASS；ruff 全仓 clean）
- [ ] 6.2 evidence+mint；PR title `feat(#759,#762): orchestrator 认知层 — THINK 席位/价值函数/主动触发器 + K3 接线`，
      body `Closes #759` + `Closes #762`；CI 绿后 squash+delete
