# GC Harness v1 — Design (#720)

权威设计: issue #720 spec-of-record comment（用户 2026-08-26）。本文记录实现级取舍。

## D1 放置与文件树

设计说"在 devkit 引入"且最小树写 `gc-harness/`（仓库根）。裁决: **按最小树落仓库根** `gc-harness/`——它是独立 CLI 工具族而非 gate 库（gate 只有一处接入点在 devkit/quality_gates.py 观察区），与 devkit/（gate 实现集合）职责不同。附 `_common.py`（config/registry/日期 ~40 行共享块）——第 5 文件是对"只需要 4 个"的最小偏离，3×复制比 1 个 40 行共享块更违背"比被治理对象简单"原则。

## D2 Metadata（.agent/，gitignore）

`.agent/{specs,tests,worktrees}.yaml`——本地生命周期登记册，**不入库**（gitignore 新增 `.agent/`）。schema 最小字段: id/path/status/created/last_modified/关联（specs.linked_tests[]；worktrees 记 commit_hash/branch/pr_link 快照）。禁止字段: score/embedding/AI 判断结果。缺 registry = 空（fail-open），scan 不因登记册缺失报错。

## D3 引用计数口径（Rule 1/2 的"关联"）

- 代码引用: spec 的 id 或 path 词干在 `scripts/ hooks/ tools/ gc-harness/`（排除 openspec/ 自身与 .agent/）的 grep 命中数
- 测试引用: 同 token 在 `tests/` 的命中数
- 全部 fail-open: grep 异常按 0 计并 WARN，不阻塞

## D4 Test GC 候选判定的数据源

`last_failure` 无既有数据源（v1 不接 CI 历史）——只认 `.agent/tests.yaml` 里登记的 `last_failure`（由 `test_gc.py record <id> --failed` 维护）。无记录 = 不候选（**宁可漏删不可错删**，fail-safe 方向记录）。重复判定: 完全相同的测试函数名出现在两个文件（近似"覆盖完全重复"，不分析内容——铁律）。删除实验: `experiment` 子命令只打印协议（mutmut 前后对比命令），不内建 runner。

## D5 Quarantine 语义

`quarantine <file>`: git mv 到 `tests/quarantine/`（保留 git 历史）+ 登记 quarantined_at/original_path。`restore <id>` 反向。`expire`: 超 quarantine_days → 删除候选；`--apply` 才删（git rm + 状态 REMOVED）。默认 dry-run 报告。

## D6 Worktree GC 判定

- merged: `git merge-base --is-ancestor <branch> origin/dev` 为真 且 最后 commit 日期超 merged_days
- abandoned: `git rev-list --count <base>..<branch>`==0（无自有 commit）且 worktree 目录 mtime 超 abandoned_days
- `--apply`: `git worktree remove` + `git branch -D` + 记录行入 .agent/worktrees.yaml（commit_hash/branch/pr_link——PR link 用分支名推 `gh pr list --head` 一次性查，查不到记 null）
- 主 worktree（裸 dev）永不候选

## D7 Budget 观察接入（WARN 不 HARD）

`devkit/quality_gates.py` 观察区（pass_rate 同级）新增 `_observation_artifact_budget`:
- 基线: `origin/dev`（不存在则 HEAD）→ `git diff --name-status <base>` 统计 added:
  - 新 spec = openspec/changes/ 下新增目录数
  - 新 test = added 的 tests/test_*.py 数
  - 新 file = added 总数
- 预算源: gc-harness/config.yaml（max_new_spec/max_new_test/max_new_files）
- 超限且 `.agent/budget_justification.md` 为空/缺失 → `[warn]` 输出（要求 justification: "Existing artifact cannot satisfy because / New artifact justification"）；有 justification → `[observe]` 带说明输出
- **不改变 exit code**（观察区语义，WARN 起步——#720 P1；HARD 化一个版本后按数据裁决）

## D8 与既有设施关系

- #520（测试治理: 通过率/有效性）——本卡是其体量维度补集，互不重叠
- #716/守卫先例——budget 观察复用"观察区不拦门"模式
- openspec 归档执行（changes→archive 移动）不在 v1——spec_gc 只给状态面（SUPERSEDED/ARCHIVED），归档动作归 #720 P2

## D9 Weekly GC（v2 面，仅记录）

每日 worktree cleanup / 每周 test+spec / 每月 deep consolidation——v1 提供 CLI（cron 直接可调），调度不建。
