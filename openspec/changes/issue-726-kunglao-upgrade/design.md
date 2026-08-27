# Design: kunglao upgrade (#726)

## D1 — 版本戳取舍: 复用 #536，不新建 `.kunglao-version`

`template_version.py` 已是版本戳单一事实源（三载体注释行 + pyproject 权威 +
read/verify 工具齐全）。新建 `.kunglao-version` 会造第二版本文件——正是 #536
文档明令禁止的漂移源。迁移起点 = `read_workspace_version(ws)`（CLAUDE.md 主载体）；
终点 = `read_skill_version()`。

## D2 — 迁移注册表（DB migration 模式，最小形）

```python
MIGRATIONS: list[tuple[str, Callable[[Path, bool], list[str]]]] = [
    ("0.1.3", migrate_to_0_1_3),
]
```

- 应用规则: `_vkey(version) > _vkey(workspace_version)` 的项按序执行
- `_vkey`: semver → tuple ("0.1.3"→(0,1,3))；非法即 ValueError → rc=3
- 每个迁移函数返回 item 名列表（供 dry-run/报告）

## D3 — migrate_to_0_1_3 的声明差五项

| item | 手段 | 幂等来源 |
|---|---|---|
| hooks_rewire | `hook_activation.register_hooks(ws)` | #445 idempotent merge + selfcheck fail-closed |
| always_armed_repair | `hook_activation.always_arm(ws)` | #533 幂等（active_hooks 成员 ensure） |
| template_stamp_refresh | `template_version.stamp_workspace(ws)` | #536 替换/前插同戳即 no-op |
| init_report_note | `runs/.init-report.json` 加 `upgrade_history` 数组条目 | append-only，不覆盖既有 phases |
| agent_metadata_seed | `.agent/specs.yaml` 最小种子（不存在才写） | 文件存在即跳过 |

v0.1.2→当前的具体差距（实查）: WIRE_UP_HOOK_FILES 9→11
（+orchestrator_tool_guard #608、+violation_capture #718）。

## D4 — 用户数据铁律的执行机制

- `user_data_digest(ws)`: 递归哈希七个目录（relpath→sha256，排序定序）
- **戳行归一化**: `facts/_INDEX.md` 与 `claim-register.yaml` 是数据载体上骑框架戳
  （#536 设计如此，update_index 保注释）。铁律的对象是**分析数据**，故这两文件的
  哈希前剥离 `# kunglao_template_version:` 行——其余字节逐位比对
- 升级流程: pre-digest → 迁移 → post-digest → 不等即 rc=4（列出 mismatch），快照
  已先行落盘供取证；相等才写汇总事件

## D5 — 快照

`_snapshot(ws, ts)`: 受管框架文件（CLAUDE.md、workspace `.claude/settings.json`、
`.hook_state.json`，存在者）sha256 → `runs/upgrade-snapshot.{ts}.json`。
dry-run 不写快照（零写入铁则）。

## D6 — 事件

`upgrade_item`（每迁移项，detail=item 名+ok）与 `upgrade`（汇总，detail=N→M）。
EMIT_ACTIONS 按字母序插入 top1_reject 之后、verify 之前（"upgrade" < "upgrade_item"
< "verify"）。emit 全程 fail-open（try/except，日志缺失不阻塞升级——但守卫对账
不 fail-open，那是铁律不是遥测）。

## D7 — 退出码

| rc | 含义 |
|---|---|
| 0 | 成功 / 已最新 / dry-run |
| 3 | 无戳或版本不可解析（提示先 init，不清跑） |
| 4 | 铁律违例（用户数据变化）——升级判定失败，快照留档 |

## D8 — kunglao.py 接线

连字符文件名不可直接 import → importlib spec_from_file_location（与测试载
kunglao-init 同模式）。`kunglao upgrade <ws> [--dry-run]`。

## D9 — gc-harness 不复用的原因

`spec_gc.main` 的 root 取 `C.repo_root()`（仓库根探测），不接受 workspace 参数；
为 `.agent/` 种子参数化 gc-harness 超出本卡范围（记 follow-up）。本地最小种子:
`specs: []` + 生成注释。
