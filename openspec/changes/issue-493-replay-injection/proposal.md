# ghidra-light 重演注入测试 — Gate 5 拦截面回放 (#493)

## Why

#462 证据 1(2026-08-18 ghidra-light 现场):worker 在工作树自造
`scripts/ghidra/DecompileFuncs.java`(184 LOC)+
`scripts/decompile_funcs_headless.py`(201 LOC),而 `ls scripts/re` 即可看到
25+ 现成 RE 工具。Gate 5(commit 时 `.subagent-review/*.json` 校验,
`devkit/subagent_review.py`)已落地,但**没有重演测试**:

- 不知道下次同类事件是否真的被拦 — 执法面无行为回放,回归不可证;
- 现行 `_validate_one` 只查 tools_used **非空**,不查**可解析性** —
  一份五字段齐全、`verified_by` 独立的 review 仍可引用自造路径放行。
  issue #493 明确要求:齐全 review + 自造工具引用 → 仍 HARD_PAUSE。

## What Changes

- **`tests/test_subagent_injection.py`(新)** — 行为等价类重演,非逐字拟合
  (计划风险表 "双轨迹重演测试过度拟合" 的缓解:负例取行为类,不取文件名拼写):
  - **场景①(自造工具无 review)**:staged `scripts/ghidra/DecompileFuncs.java` +
    `scripts/decompile_funcs_headless.py` 等价物,无 `.subagent-review/*.json` →
    HARD_PAUSE(rc=2)+ 具体错误点名触域路径;等价类变体(不同文件名)同样触发。
    **配套 dispatch 层**:派发 prompt 意图工具族(ghidra/decompile)与 #495
    `validated_capability` 能力卡在 Agent 工具面交叉断言(#496 guard 真打:
    同族放行 / 异族 REJECT + `capability-disproof` 指引 / 出示 disproof 放行)。
  - **场景②(合法 review 放行)**:tools_used 引真实工具 — `scripts/re/`
    工作区命名空间、`tools/_INDEX.yaml` 注册名与 `#anchor` 路径、
    `tools/` `references/` 现实文件 → rc=0。
  - **场景③(齐全 review + 自造引用)**:五字段齐、`verified_by` 独立,但
    tools_used 引不可解析路径(`scripts/decompile_funcs_headless.py` 等)→
    仍 HARD_PAUSE — **本变更的实现增量**(RED 由此红)。
  - **场景④(负例 SUFFICIENT / 独立性)**:三场景互相独立 — 合法 sibling
    review 不得掩盖不可解析引用;各场景在无其它场景 fixture 时照常触发。
- **`devkit/subagent_review.py`(改)**:`_validate_one` 增 tools_used
  可解析性校验。合法解析类:
  1. `scripts/re/**` — 工作区 RE 工具命名空间(three-point check 第 1 点,
     按 engagement 部署,skill 仓库内永不出现 → 按前缀信任);
  2. `tools/_INDEX.yaml` 注册名(bare 逻辑名);
  3. `scripts/` `tools/` `references/` 下的现实文件(`#anchor` 后缀允许 —
     既有 review JSON 的 `tools/_INDEX.yaml#<name>` 约定)。
  禁 `..` traversal / 空段 / 锚点单独出现;tools_used 非数组 → fail-closed。
  错误信息给出三合法类作为修正路径。
- **`devkit/docs/subagent-review.md`(改)**:契约表 `tools_used` 行与执法规则
  同步可解析性语义(schema 单源)。

## Impact

- 执法面收紧,既有测试不放松:`tests/test_subagent_review.py` 全绿保留
  (其 fixture 引 `scripts/re/` 命名空间与真实 `scripts/kunglao.py`,均在
  合法类内);已跟踪的 `.subagent-review/2026-08-19-gate5.json` 三条引用
  (`scripts/check_global_rule_subset.py` / `scripts/references_recall.py` /
  `tools/_INDEX.yaml#subagent-review`)均真实存在,不受影响(有测试钉住)。
- 与 test_subagent_review.py 互补:那边测 schema 边界,这边测真实注入场景
  (issue 验收原话)。
- 不动 Gate 6(agents lint)/ failure_analysis_gate(三产物)/
  ask_for_direction_gate(TYPE_E)— 本件只回放/收紧 Gate 5 与 dispatch
  guard 的既有行为,不新增决策面。
