# issue-600-capability-dormant — capability_guard 静默失效 → dormant 可观测化

## Why

`hooks/dispatch_gate.py:_capability_guard`（②(a) 能力卡牙）从 `claim-register.yaml`
读取 `obstacle_for` 计算能力卡作用域。该字段是可选语义（仅 #497/#495 trajectory-1
promote 时写入）：operator/agent 生成的 register 通常没有任何 claim 带 `obstacle_for`，
此时 `capability_switch_violation()` 对每次 dispatch 恒返 `None`——②(a) 牙静默 no-op。
与 #594/#596 同类（"operator 没写的字段让门哑火"），但发生在安全侧 enforcement 面。
修复 = dormant 状态可观测化（一次性 WARN + 指路文案），**不是**把字段变必填
（那会破坏全部 greenfield workspace）。

## What Changes

1. **词表**：`scripts/event_taxonomy.py` `EMIT_ACTIONS` 新增 `capability_dormant`
   （受控词表锚定测试要求 sorted + unique，按字母序插入）。
2. **guard 入口一次性 dormant 告警**：`hooks/dispatch_gate.py` `_capability_guard`
   入口处检查全 register——claims 非空且无任何 `obstacle_for` → 一次性
   `capability_dormant` WARN（stderr + additionalContext + unified log trace，
   形状镜像同文件 #772 `redo_leak_warn` face），含指路文案（#496 能力卡需要
   `obstacle_for` 才生效）。一次性由 sentinel 文件
   `runs/.capability-dormant-warned` 保证（hook 是短命子进程，模块级 flag 无效；
   sentinel 先例 = `runs/.retry-counter.yaml`）。
3. **测试（TDD 两态）**：register 无 `obstacle_for` → 恰好一次 dormant 告警
   （第二次 dispatch 不重复）；有 `obstacle_for` → 零告警且 enforcement 照旧
   （既有 REJECT 测试继续绿）。

## Impact

- 受益：operator 对 ②(a) 牙的真实武装状态有可观测信号，不再误信静默 no-op 为
  "capability_switch enforced"。
- 风险：低——WARN 面不改变任何 rc/REJECT 语义；sentinel 写失败 fail-open
  （降级为下次重复告警，可接受），emit 本身全程 try/except 不阻塞 dispatch。
- 边界：register 不可读/为空 → 不告警（不猜）；空 register（0 claims）不告警
  （无 enforcement 期望，避免噪声）。

## Recon

### 锚点表（计划/issue 锚点 vs 实测，2026-09-01 @ 1266078）

| 符号 | issue/计划锚点 | 实测锚点 | 偏航 |
|---|---|---|---|
| `_capability_guard` | dispatch_gate.py:424 | `hooks/dispatch_gate.py:484` | 已知行号漂移（§0.7），符号定位无碍 |
| `obstacle_for` read | dispatch_gate.py:446-455 | `hooks/dispatch_gate.py:504-513`（`parent = (target or {}).get("obstacle_for")` at :509） | 同上 |
| `_emit_trace` | —（issue 未锚） | `hooks/dispatch_gate.py:352`；WARN 面调用样式 `_emit_trace(ws, "<action>", claim_id, "<detail>")` 无 exit_code（对比 :533/:870） | 无 |
| guard 主入口调用点 | — | `hooks/dispatch_gate.py:975`（`rc = _capability_guard(...)`） | 无 |
| `EMIT_ACTIONS` | — | `scripts/event_taxonomy.py:160`；锚定测试 `tests/test_event_stream_adoption.py`（要求 sorted+unique，:129） | 无（新约束：新词必须按字母序插入） |

### 镜像样例

- **WARN face 形状**（同文件）：`redo_leak_warn` #772 at
  `hooks/dispatch_gate.py:850-871` —— stderr `dispatch_gate: WARN ...` +
  `hookSpecificOutput.additionalContext` JSON + `_emit_trace(...)` 三件套。
  dormant 告警完整镜像此形状（一次性约束下三件套都只发一次）。
- **一次性 sentinel 先例**：`runs/.retry-counter.yaml`
  （`hooks/worker_budget_core.py:38` `RETRY_COUNTER_FILE`、
  `hooks/worker_budget_gates.py:273`）。hook 每次 dispatch 是新进程，
  一次性必须落盘 → `runs/.capability-dormant-warned`。
- **dormant 措辞先例**：`scripts/hook_activation.py:1164`
  `"NOTE: hooks wired but dormant - ..."`。
- **词表注册先例**：`install_reference_scan` / `git_snapshot_skipped` 等
  WARN-only face 词 + 行内 `# #NNN ... face` 注释。

### 基线

- `python -m pytest tests/test_decision_teeth.py tests/test_event_stream_adoption.py -q`
  → 48 passed（2026-09-01 @ 1266078）。

### 实现级偏离记录（允许，WHAT/WHY）

- WHAT：一次性机制用 sentinel 文件而非 issue Option (a) 伪码里的裸 emit。
  WHY：issue 伪码每 dispatch 都 emit（刷屏），违反计划验收"一次性而非每
  dispatch 刷屏"；hook 短命进程 → 必须落盘 sentinel。
- WHAT：emit 三件套（stderr + additionalContext + trace）而非仅 trace。
  WHY：镜像同文件 #772 WARN face 的完整形状；计划要求"trace 行断言"，
  additionalContext 保证 operator 在 dispatch 上下文里能看到指路文案。
- WHAT：空 register（0 claims）不告警。WHY：无 claims 即无 enforcement 期望，
  告警是噪声；issue 场景主体是"claims 非空但全无 obstacle_for"。

### 偏航判定

无规格级偏航（RECON-DEVIATION 触发条件均未命中）：方案 Option (a) 可按计划
落地，锚点漂移属 §0.7 已知预期。
