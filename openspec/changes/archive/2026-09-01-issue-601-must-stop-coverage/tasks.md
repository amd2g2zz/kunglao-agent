# issue-601-must-stop-coverage — tasks

## 1. TDD RED（测试先行）

- [x] 1.1 `tests/test_must_stop_coverage_601.py`：dispatch 语法面 4 类正样本 + rule id 断言
      + 4 类对照组（不命中）+ 旧 6 规则不回归 + prose 不误触发（既有钉法镜像）。
- [x] 1.2 同文件：MCP 面——`evaluate()` 模拟 PreToolUse payload（tool_name=mcp__ghidra__decompile_function /
      mcp__x64dbg__start_session / mcp__frida__attach），cwd 非 .wt-* → rc=2 + REJECT stderr +
      trace 行（action=orchestrator_mcp_reject，matched_rule 可判读）；cwd=.wt-C1 → 放行；
      Bash face 不受影响。
- [x] 1.3 同文件：精度面——现场误报样本 `cd .../jadx/bin`、`grep floss ...`、cat/sed 类
      → (0, "", None)；命令位正样本 jadx/apktool/floss/analyzeHeadless(.bat) 仍 WARN +
      emit 带 matched_rule。
- [x] 1.4 同文件：`kunglao_log.emit` additive 字段——matched_rule 落行、缺省 null key；
      `_warn_must_stop` trace 行带 matched_rule。
- [x] 1.5 同文件：登记面——register_hooks 产物含 MCP matcher 行；`_DEPLOYED_WIRING` 同帧；
      sentinel（DOUBLE_REGISTERED_HOOKS）更新后计数锚派生一致。

## 2. 实现（GREEN）

- [x] 2.1 `scripts/event_taxonomy.py`：EMIT_ACTIONS += orchestrator_mcp_reject,
      orchestrator_tool_violation（sorted 插入）。
- [x] 2.2 `scripts/kunglao_log.py`：emit() 增 `matched_rule: str | None = None` kwarg
      （null-key 缺省，#818 additive 形状）。
- [x] 2.3 `hooks/dispatch_gate.py`：`_DISPATCH_MUST_STOP_RULES`（(rule_id, pattern) 元组表，
      6 旧 + 4 新）+ `_must_stop_dispatch` 返 rule id + `_warn_must_stop` 三件套（+ws/rule 参数）。
- [x] 2.4 `hooks/orchestrator_tool_guard.py`：MCP host-channel REJECT face +
      Bash 面命令结构解析（&&/||/;/|/换行分段、段首命令位 + env-assignment 前缀跳过 +
      basename 归一）+ emit matched_rule。
- [x] 2.5 `scripts/hook_activation.py`：matcher 常量 + `_DEPLOYED_WIRING` 行 +
      `register_hooks` `_ensure` 行；`scripts/wire_up_settings.py` DOUBLE_REGISTERED_HOOKS
      + `tests/test_hook_registry_singlesource.py` sentinel 字面量同帧。
- [x] 2.6 schema 钉子同帧扩：`tests/test_kunglao_log.py` ALL_FIELDS、
      `tests/test_logging_coverage.py` SCHEMA_FIELDS 增 matched_rule。

## 3. 本地门 + 交付链

- [x] 3.1 `python -m pytest tests/ -q` 全绿（~7 个已知环境性基线失败按 stash 对照甄别）。
- [x] 3.2 `python scripts/release_receipt.py --check` 绿；`python scripts/deploy_manifest.py --write`
      → `--check` 绿（hooks 资产 hash 变更刷新）。
- [x] 3.3 小粒度 conventional commits；push 分支；`gh pr create --base dev`；CI 绿后停手（不 merge）。
