# Tasks: ghidra-light 重演注入测试 (#493)

- [x] 1. SDD 三件套(openspec/changes/issue-493-replay-injection/)
- [x] 2. RED:`tests/test_subagent_injection.py` — 场景①无 review
      HARD_PAUSE + 路径点名 + 等价类变体;dispatch 交叉断言三例(真打);
      场景②合法引用参数化 rc=0;场景③不可解析引用参数化 rc=2 +
      `_tool_resolves` 解析类单元;场景④独立性三例;真实仓库 pin
      (合法引用可解析 / 事故路径不可解析 / 已跟踪 gate5 review 三引用)
- [x] 3. GREEN:`devkit/subagent_review.py` — `WORKSPACE_TOOL_NAMESPACE` /
      `RESOLVABLE_ROOTS` / `_index_tool_names` / `_tool_resolves` +
      `_validate_one` 接线(非数组 fail-closed;错误信息含三合法类)
- [x] 4. `devkit/docs/subagent-review.md` 契约同步(tools_used 行 + 执法规则)
- [x] 5. 快检:`uv run python -m pytest -q -m "not load_sensitive"
      tests/test_subagent_injection.py tests/test_subagent_review.py` 全绿
- [x] 6. 门:`uv run ruff check .` 零红;
      `uv run python devkit/quality_gates.py 1 3 4 5 6 7` ALL-PASS;
      Gate 5 review JSON `.subagent-review/2026-08-20-493.json`
      (verified_by=pending-493-reviewer,待 reviewer 回填)
