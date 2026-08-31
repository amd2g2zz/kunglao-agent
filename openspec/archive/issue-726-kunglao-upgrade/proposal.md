# Proposal: kunglao upgrade — workspace 框架脚手架迁移 (#726)

## Why

迭代速度导致老 workspace 与新特性冲突（用户 2026-08-26 指令）: v0.1.3 hooks 两扩
（violation_capture / _path_hygiene 依赖）、能力注册表、事件词汇表三增——老 workspace 缺任何
一层即新旧矛盾。#717 现场: sample-incident-01 模板戳 v0.1.2 滞后，正是三层闸门失效的放大器；L1 根因
active_hooks 漂移即 workspace 状态病。"按旧工程继续做只会更糟。"

## What Changes

- **版本戳单一事实源**: 复用 #536 既有机制（`template_version.py`，三载体注释戳，
  权威 = pyproject.toml）——不新建 `.kunglao-version`（D1 取舍）
- **`scripts/kunglao_upgrade.py`**（新）: N→M 迁移注册表
  - `MIGRATIONS: list[(version, fn)]`，线性走 `version > 工作区戳` 的全部迁移
  - 首个迁移 `migrate_to_0_1_3`: hooks 重布线（复用 `hook_activation.register_hooks`，
    9→11 hooks 含 orchestrator_tool_guard/violation_capture）、`always_arm` 修复
    ALWAYS_ARMED、`stamp_workspace` 三载体戳刷新、init-report 升级记录、
    `.agent/specs.yaml` 最小种子（fail-open）
- **`scripts/kunglao.py`**: 挂 `upgrade` 子命令（importlib 载入连字符模块，同 init 模式）
- **`scripts/event_taxonomy.py`**: EMIT_ACTIONS 注册 `upgrade` / `upgrade_item`
  （排序位于 top1_reject 与 verify 之间）

## 铁律（违反即返工）

用户数据目录 `claims/ facts/ runs/ hypotheses/ notes/ evidence/ oracle/` 迁移前后
**字节级不变**——升级内置守卫对账（sha256 树摘要，戳行归一化），违例 rc=4 硬失败。

## 安全面

- dry-run: 打印迁移清单零写入
- 迁移前快照: 框架文件 sha256 → `runs/upgrade-snapshot.{ts}.json`
- per-item 报告: kunglao_log emit（`upgrade_item` × N + `upgrade` 汇总）
- 幂等: 已最新 → no-op rc=0；无戳/未知版本 → rc=3 拒跑（提示先 init）

## Non-goals

- 不重探工具链（环境相关，属 init/renew 职责）
- 不迁移事件词汇（消费侧读码即得）
- 不做 gc-harness 的 root 参数化（`.agent/` 种子为最小本地实现，gc-harness 适配留 follow-up）
