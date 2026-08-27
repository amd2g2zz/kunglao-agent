# GC Harness — Agent 工程资产生命周期控制器 v1 (#720)

## Why

v0.1.2→v0.1.3 实测: 全仓净 +17.4k LOC（≈1.45×）、tests/ 净 +8.7k、tests 文件 +47、openspec/changes/ 四件套从不归档（~40+ 目录堆积）。用户 2026-08-26 指令（spec-of-record 见 issue #720 comment）: 引入资产生命周期控制器，控制三件事——

1. 禁止重复资产无限增长
2. 及时淘汰失效资产
3. 让 Agent 优先修改已有资产，而不是创造新资产

设计铁律: **GC Harness 本身必须比被治理对象简单**。不引入评分系统/知识图谱/全历史状态/AI 判断。

## What Changes

- `gc-harness/`（仓库根，5 文件——设计 §11 树 + `_common.py` 共享块，偏差见 design.md D1）:
  - `spec_gc.py`: `search`（创建前强制查询，输出 Existing + Decision: modify|create）/ `scan`（Rule 1 代码引用=0 且超期 → ARCHIVED；Rule 2 测试关联=0 → SUSPECT；Rule 3 重复只报告）/ `init`（从 openspec/changes 登记 ACTIVE，只登记不裁决）
  - `test_gc.py`: `scan`（候选: last_failure>180d 或同名重复）/ `quarantine` / `restore` / `expire`（超 30 天 → 删除候选，--apply 才删）/ `experiment`（删除实验协议打印，接口不内建 runner）/ `init`
  - `worktree_gc.py`: `scan`（merged+7d / abandoned 无 commit+14d → 候选）/ `--apply` 删除并只留 commit hash/branch/PR link 记录
  - `config.yaml`: orphan_days:90 / quarantine_days:30 / merged_days:7 / abandoned_days:14 / max_new_spec:1 / max_new_test:5 / require_existing_check:true
  - `_common.py`: config 加载 + registry 读写 + 日期工具（~40 行共享块）
- `devkit/quality_gates.py`: 观察区新增 `_observation_artifact_budget`（**WARN 不 HARD**，对齐 #720 P1）——净增 spec/test/file 数 vs 预算；超限且无 `.agent/budget_justification.md` → WARN 升级提示
- `.agent/` metadata: gitignore 约定 + `specs.yaml`/`tests.yaml`/`worktrees.yaml` 最小 schema（id/path/status/created/last_modified/关联——无 score 无 embedding）
- v1 不建 cron——Weekly GC（每日 worktree/每周 test+spec/每月 deep consolidation）记 design.md 为 v2 面

## Acceptance

- [ ] spec_gc: 孤儿 spec 超 90d → ARCHIVED；测试关联=0 → SUSPECT；重复只报告；search 输出 Decision
- [ ] test_gc: last_failure>180d → 候选；quarantine 移动+可恢复；超 30d → 删除候选（--apply 才删）
- [ ] worktree_gc: merged+7d / abandoned+14d → 候选；apply 后只留记录不留目录
- [ ] budget 观察进 quality_gates（WARN 级，有 justification 则放行说明）
- [ ] 本 PR 自身过自己的 budget 门（dogfood，净增数字入 PR 正文）
- [ ] 铁律自查: 零评分/零知识图谱/零全历史/零 Agent 自决删除

## Out of scope

- mutation runner 内建、AI 质量分、cron/CI 调度、openspec 归档执行（归档机制在 #720 P2 另行落地——本卡只提供 spec_gc 的 SUPERSEDED/ARCHIVED 状态面）
