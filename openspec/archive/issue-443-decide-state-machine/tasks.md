# Tasks — decide() 一等状态机 (#443)

## 1. SDD

- [x] openspec/changes/issue-443-decide-state-machine/proposal.md
- [x] openspec/changes/issue-443-decide-state-machine/design.md(含 §5 回归锚定策略)
- [x] openspec/changes/issue-443-decide-state-machine/tasks.md

## 2. RED

- [x] tests/test_decide_regression_anchor.py: 输入矩阵 builder(~30 case,
      覆盖每分支 + 交织 + 优先级序 + #495/#497 交织)+ 活基线通道
      (git show c5cb1ae 提取老版并行运行比对)+ 冻结快照通道断言
- [x] tests/decide_anchor_c5cb1ae.json: 由 c5cb1ae 基线机器生成(design
      §5 命令),非手写
- [x] tests/test_decide_state_machine.py: 行为测试(表完整性 / catch-all /
      终态映射 / 零 elif 元守卫 / 双梯同判 / 确定性 / #495 三产物谓词)
      —— RED: 新符号(State/Event/TRANSITIONS/STAGE_PROBES)不存在,
      断言失败(非 import error)
- [x] RED commit (9aa1761)(哈希记入 PR body,可检出重放)

## 3. GREEN

- [x] scripts/convergence_check.py: State/Event/VERDICTS/STAGE_PROBES/
      _EVENT_PREDICATES/TRANSITIONS + _decide_inputs + _run_machine;
      decide() 查表执行,13 分支 elif 链删除,action 构造器逐字节保文
- [x] 事件词汇消费: FAILURE_ARTIFACTS_DUE ← _failure_blocked(#495
      validated_capability/identified_obstacle);
      LADDER_EXHAUSTED_BLOCKER ← ask_for_direction_gate.
      find_ladder_exhaustion(#497 标记,fail-open 归 LADDER_REQUIRED)
- [x] 输出 shape 不变(字段集合 / 字段名 / exit 语义),调用方零改动

## 4. 验证

- [x] `uv run python -m pytest -q -m "not load_sensitive"
      tests/test_convergence_completeness.py tests/test_convergence_rules_file.py
      tests/test_decide_schema_routing.py tests/test_completion_transaction.py
      tests/test_decide_state_machine.py tests/test_decide_regression_anchor.py` 绿
- [x] 锚定双通道全等(冻结快照 + 活基线,逐 case)
- [x] `uv run ruff check .` 零红
- [x] `uv run python devkit/quality_gates.py 1 3 4 5` ALL-PASS
      (Gate 5: .subagent-review/2026-08-19-443.json,
      verified_by=pending-443-reviewer,reviewer 回填)
- [x] .review/RUNBOOK.md(改动清单 / 测试映射 / 自认风险;永不提交)
