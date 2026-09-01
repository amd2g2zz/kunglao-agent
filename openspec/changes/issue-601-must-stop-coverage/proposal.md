# issue-601-must-stop-coverage — must-stop 守卫覆盖全量（四项一并）

## Why

`hooks/dispatch_gate.py` 的 must-stop 命令语法面（`_DISPATCH_MUST_STOP_PATTERNS`）只有 6 条模式，
覆盖 VM/git/publish 三族；四类危险 shell 形状（chmod 宽授权、无 VM 关键词的递归删除、
管道执行远端脚本、特权执行守卫缺口同族：
main agent 直调 `mcp__ghidra__*`/`mcp__x64dbg__*`/`mcp__frida__*` 只有 prose 禁令（rules §7.5），
PreToolUse 面零拦截；同时 orchestrator_tool_guard 在整条命令文本上正则匹配 →
`grep floss`、`cd .../jadx/bin` 类误报（豆包现场 160 WARN/25min，首 token cd×123/grep/cat/sed），
且 emit 只记命令首 token，事后无法判读真假 → 告警疲劳淹死真信号。
issue 评论明确要求四项一并纳入"守卫覆盖"主题，全做。

## What Changes

1. **词表**：`scripts/event_taxonomy.py` `EMIT_ACTIONS` 新增 `orchestrator_mcp_reject`
   （新拦截 face）与 `orchestrator_tool_violation`（#608 既有发射字面量，锚定正则因
   emit 首参 `Path(cwd)` 含括号而看不见——补注册消除潜伏缺口）。
2. **dispatch 语法面 +4 pattern（词边界+参数形状，每类配不应命中的对照组）**：
   chmod 宽授权 / 递归删除（无 VM 关键词）/ 管道执行远端脚本 / 特权执行包装器；
   语法面共 10 个 rule id（6 旧 + 4 新）。
3. **`_must_stop_dispatch` 返回 rule 标识**；`_warn_must_stop` 增 unified-log trace：
   `must_stop` action（词表已有此词）+ `matched_rule` 字段。
4. **MCP 面拦截**：扩展 `hooks/orchestrator_tool_guard.py`（镜像 #608 target-based 姿态：
   cwd 在 `.wt-*` worker worktree → 放行 worker 面；否则 REJECT rc=2 + stderr +
   unified-log trace 行）。matcher 行 = `mcp__ghidra__.*|mcp__x64dbg__.*|mcp__frida__.*`，
   `_DEPLOYED_WIRING`（hook_activation.py:790-807）与 `register_hooks`（:943-1031）双写点同帧。
5. **命令结构解析（精度）**：`orchestrator_tool_guard` Bash 面从整条文本正则 → 按
   `&&`/`||`/`;`/`|`/换行 分段、段首命令位（跳过 env-assignment 前缀 token）匹配
   分析二进制词表；emit 记 matched_rule，不再只记命令首 token。
6. **登记面**：`wire_up_settings.DOUBLE_REGISTERED_HOOKS` 增 `orchestrator_tool_guard.py`
   （同文件第二 matcher 行 = 结构性 double registration，计数锚自动跟随）；
   `tests/test_hook_registry_singlesource.py` sentinel 字面量同帧更新（有意编辑）。
7. **TDD**：新测试文件 `tests/test_must_stop_coverage_601.py`（RED 先行）：
   4 类正/负样本、MCP 直调 payload → REJECT + trace 行 + matched_rule、
   现场误报类样本（`cd .../jadx/bin`、`grep floss`）不命中、既有 must-stop 不回归。

## Impact

- 受益：派发面四类不可逆动作有停点；main agent 直调 VM-only MCP 命名空间被结构拦截
  （rules §7.5 从 prose 变 mechanism）；Bash 面误报（cd/grep/cat/sed 类）消失，真信号可判读。
- 风险：低——MCP REJECT 有 worker-worktree 放行面，worker 工作流不动；WARN/REJECT emit
  全程 fail-open（trace 失败不改变 rc）；must-stop 仍是 WARN 姿态（HARD_PAUSE 语义不变）。
- 边界：误报对照组与正样本同帧钉死，防止守卫收敛回过宽匹配。

## Recon

### 锚点表（计划/issue 锚点 vs 实测 @ f5d86a7，2026-09-01）

| 符号 | issue/计划锚点 | 实测锚点 | 偏航 |
|---|---|---|---|
| `_DISPATCH_MUST_STOP_PATTERNS` | dispatch_gate.py:241-251 / :269 | `hooks/dispatch_gate.py:276-286` | 已知行号漂移（§0.7），符号定位无碍 |
| `_must_stop_dispatch` | — | `hooks/dispatch_gate.py:289-295`（消费方 :1017） | 无 |
| `_warn_must_stop` | — | `hooks/dispatch_gate.py:298-326`（**现状零 unified-log trace**——只有 stderr+additionalContext 两件套） | 新发现：must-stop face 缺 trace 三件套第三件，本卡补齐 |
| `obstacle_for` read | dispatch_gate.py:504-513 | `hooks/dispatch_gate.py:509`（#600 已合） | 无 |
| `_emit_trace` | :352 | `hooks/dispatch_gate.py:359-374` | 微移，无碍 |
| guard 调用点 | :975 | `hooks/dispatch_gate.py:1017`（must-stop 判定点） | 无 |
| `orchestrator_tool_guard` Bash 正则 | — | `hooks/orchestrator_tool_guard.py:31-34`（`ANALYSIS_BINARIES`，整条文本匹配） | 无 |
| emit 只记首 token | — | `hooks/orchestrator_tool_guard.py:61-63`（`cmd.split()[0]` 进 detail） | 无 |
| PreToolUse hook 注册方式 | — | 双写点：`scripts/hook_activation.py:790-807`（`_DEPLOYED_WIRING`）+ `:943-1031`（`register_hooks`，orchestrator 行 :1000）；`build_hook_entry` :502-529（matcher 自由文本） | 无 |
| MCP 面（worker 面）先例 | — | `hooks/lib_kunglao.py` `check_mcp_prefix` / `hooks/worker_budget_core.py:66-73` `HOST_FORBIDDEN_TOOLS`（worker Agent 面 tools= 过滤） | 无——本卡的 main-agent MCP 面在 Bash-face 同 hook 上加 matcher 行，worker 派发过滤不动 |
| settings.json hooks 段形状 | — | `{"hooks": {"PreToolUse": [{"matcher": "...", "hooks": [{"type": "command", "command": "PYTHONUTF8=1 uv run --project <skill_root> <hook>"}]}]}}`（`build_hook_entry` :502-529） | 无 |
| `EMIT_ACTIONS` | — | `scripts/event_taxonomy.py:160-240`（`must_stop` 已在词表 :207） | 无 |
| emit 词表锚定 | — | `tests/test_event_stream_adoption.py:73-117`（`_LITERAL_PATTERNS` 扫 scripts+hooks 的 action 字面量；`orchestrator_tool_violation` 因 `.emit(Path(cwd), ...)` 首参含括号逃过 pattern-3——潜伏缺口，本卡补注册） | 新发现 |
| emit schema 字段 | #818 additive 先例 | `scripts/kunglao_log.py:79-119`（固定 kwargs，缺省→显式 null key）；钉子：`tests/test_kunglao_log.py:22-24` `ALL_FIELDS` + `tests/test_logging_coverage.py:80-84` `SCHEMA_FIELDS` | 无（`matched_rule` 按 #818 方式 additive 落，两处钉子同帧扩） |
| must-stop 测试钉法 | — | `tests/test_dispatch_protocol.py:239-246`（unit：`is not None` 断言——返回 rule-id str 兼容）；`:248-269`（hook 级 subprocess rc=2 + stderr） | 无 |
| registry/计数锚 | — | `scripts/wire_up_settings.py:57-81`；`tests/test_hook_registry_singlesource.py:60-71` sentinel；派生计数锚 `tests/test_wire_up_settings.py:34-35`、`tests/test_heartbeat_bootstrap.py:258-265`、`tests/test_canonical_chain_752.py:53` | 无（registry 按**文件**计，同文件第二 matcher 行不增文件集；计数锚从 `DOUBLE_REGISTERED_HOOKS` 派生，sentinel 有意更新即可） |

### 偏航判定

- **无规格级偏航**（RECON-DEVIATION 不触发）。规格四项与代码现实一致，全部可落。
- 实现级记录（§0.2 #3 允许，记录 WHAT/WHY）：
  1. **must-stop face 补第三件（trace）**：issue/计划只要求 emit 行带 matched_rule，但
     `_warn_must_stop` 现状根本没有 trace emit——补齐成 #600 三件套形状（stderr +
     additionalContext + `_emit_trace`）。WHAT: `_warn_must_stop` 增 `ws`/`rule` 参数 +
     `_emit_trace(ws, "must_stop", ...)`, exit_code=2。WHY: 观测出生（logging-is-product-lifeline）。
  2. **matched_rule 走 emit additive schema 字段**（非 detail 子串）。WHY: #818 batch-1
     先例（arm/epoch/hypothesis_ref），`kunglao_log.emit` docstring 自证 additive 稳定 schema；
     `test_kunglao_log.ALL_FIELDS` / `test_logging_coverage.SCHEMA_FIELDS` 两处钉子同帧扩。
  3. **MCP 面挂同一 hook 文件**（不新建 hook 文件）：registry 按文件计，不增 WIRE_UP_HOOK_FILES
     → singlesource/subset/kicker/env_check 全自动跟随；代价是 `DOUBLE_REGISTERED_HOOKS`
     sentinel 有意 +1（同文件两个 matcher 行）。WHY: #608 已有 target-based 姿态与 worktree
     放行面，同 hook 扩展面最小、登记面变化最小。
  4. **env_manifest 无 repo 侧手工刷新点**：`scripts/env_manifest.py` 与 hooks 资产面无耦合
     （grep 零命中）；资产面登记在 deploy-manifest.yaml（`kind: hook`，按文件），sha256 变更由
     `deploy_manifest.py --write` 刷新（坑提示已知：补丁后 hash 变 → 必须重跑 --write 再 --check）。
     WHAT: 提交前 `--write` + `--check`。WHY: 实测无 env_manifest 钩子，避免幻影登记动作。
  5. **`_DISPATCH_MUST_STOP_PATTERNS` 重构为 `(rule_id, pattern)` 元组表**
     `_DISPATCH_MUST_STOP_RULES`。WHY: 返回值要带 rule 标识；全仓无 import 该名的消费者
     （仅 dispatch_context.py:437 注释引用），重命名零破坏。

### 镜像样例

- **WARN/REJECT 三件套**：`redo_leak_warn`（dispatch_gate.py:940-958，#772 face）与
  `capability_dormant`（:491-541，#600 face）——stderr + `hookSpecificOutput.additionalContext`
  JSON + `_emit_trace(...)`。MCP REJECT 镜像 `_reject_with_guidance`（:342-356）rc=2 形状。
- **target-based 放行面**：`orchestrator_tool_guard._in_worker_worktree`（:43-45）——`.wt-*`
  path-part 前缀检测，worker cwd 放行、主 agent cwd 拦截。
- **词表纪律**：`event_taxonomy.EMIT_ACTIONS` sorted+unique（锚定测试 :121-129）；
  `tests/test_logging_coverage.py:70-78` ALLOWED_ACTIONS 为独立子集快照（非全等断言，
  加词不破坏）。
- **additive schema 先例**：`tests/test_logging_schema_818.py`（新增字段 + null-key 缺省 +
  ALL_FIELDS 同帧扩）。
- **基础线**：受影响测试文件 145 passed @ f5d86a7（test_dispatch_protocol 54 +
  test_hook_registry_singlesource/test_wire_up_settings/test_kunglao_log/
  test_logging_coverage/test_logging_schema_818/test_decision_teeth 91）。
