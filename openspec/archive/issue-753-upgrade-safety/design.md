# Design: upgrade 执行序安全 (#753)

## D1 — 用户裁决（2026-08-27，原文）

> "升级前要先检测 git 检测未提交，然后 commit 之后再执行 upgrade，不然坏掉了都无法回滚"

推论: git 锚点是 migration 的**前置条件**，不再是收尾装饰。#739 的"升级后快照"
在 #753 语境下重排为: 无 .git 的 workspace 升级前先 init+commit 锚点。

## D2 — 执行序（upgrade() 非干跑路径）

```
read stamp → plan
dry-run 分支（零写入铁则不动，不触 git）
B1 gate/anchor:
    _workspace_dirty(ws)                       # git status --porcelain 行数；无 .git → None
    dirty>0 → RC_DIRTY_WORKSPACE=6 + stderr commit/stash 指导（先拒绝，什么都不写）
    dirty==0 → 继续（干净 owned repo）
    None → _create_pre_upgrade_anchor(ws)      # .gitignore → init/add/commit(pre-upgrade anchor)
pre digest → runs/upgrade-snapshot.{ts}.json   # 位置不变
migration items（顺序不变）
post digest 对账 → rc=4 不动                   # iron rule 语义不变
B4 tail 显式阶段:
    stamp_workspace → [event] stamp ok
    _emit(upgrade)                              # jsonl 遥测位置不变（吞异常不改）
    print 人读总结 → [event] summary ok
    anchor created ? post-state commit : ensure_git_snapshot()（恢复路径）
    → [event] git-snapshot
    [event] 任一环节异常 → RC_INCOMPLETE=7（fail event + stderr INCOMPLETE 行），绝不静默 RC_OK
B3 reload-plugins 提示（仅真迁移成功路径）→ return RC_OK
```

## D3 — 锚点与 post-state commit

- 锚点 message: `kunglao-upgrade: pre-upgrade anchor (rollback point before migration)`，
  含字面 "pre-upgrade anchor"；身份/签名沿用 #739 约定
  （`-c user.name=kunglao-upgrade -c user.email=kunglao-upgrade@localhost` + `--no-gpg-sign`）
- post-state commit: `kunglao-upgrade: post-upgrade state commit (migration applied)`——锚点由本 run
  创建时才落（owned repo 不代提交）。它保证验收项 "migration 后可 `git revert` 回锚点"：
  revert HEAD 即还原全部迁移效果；同时让树回到 clean，后续 re-run 不误触 rc=6
- `.gitignore` 先于首次 add（复用 `_GITIGNORE_BODY`）；属框架脚手架，digest 只扫七目录，
  对账不受影响（判定依据见 proposal 铁律节）

## D4 — 失败面取舍

| 场景 | 行为 | 依据 |
|---|---|---|
| owned repo dirty | rc=6 拒绝，零写入 | 用户裁决：未提交不可升 |
| git binary 缺失/失败（gate 与 anchor 共因） | WARN 大声 + 降级继续；tail 仍尝试 ensure_git_snapshot 兜底 | 保持 #739 既定语义与既有 pin 测试；
  是否硬拒列为产品 follow-up |
| 尾部阶段任一异常 | fail event + RC_INCOMPLETE=7 | B4；monkeypatch `_emit` 抛 = 模拟 |
| 进程被外杀（进程内不可捕获） | B1 锚点可 revert + B2 死前最后事件可追溯 | 验收的中断模拟组合 |

## D5 — 实现者裁量（偏离任务字面处，需 reviewer 注目）

- **start/ok 配对不实现**: 任务 B4 字面"每阶段前 emit start、后 emit ok/fail"。改为**每节点恰好一行、
  严格有序 + flush=True**：kill 后最后一行 name 即精确暴露死亡位点（stamp 与 summary 之间死 ⇒
  末行必为 stamp ok），可观测性等价且符合 B2 格式契约 status=ok|warn|fail（不引入 start 态）。
- **遥测词汇冻结**: `.jsonl` 侧不加新 action（新增 `git_anchor_skipped` 于 EMIT_ACTIONS 仅用于
  anchor 无法创建的审计对齐，与 `git_snapshot_skipped` 并列）。
- **hint 只出现在真迁移成功**: already-current/dry-run 不提示 /reload-plugins（包未变）。
- init 侧 B3 以"成功 tail 结构性存在"断言验证（init 全功能调起成本过高，列入遗留点）。

## D6 — 退出码与 envelope

| rc | status label | 场景 |
|---|---|---|
| 0 | ok / already-current / dry-run | 不变 |
| 3 | refused | 不变 |
| 4 | iron-rule-violation | 不变 |
| 6 | refused-dirty | 有 .git 且 dirty |
| 7 | incomplete | 迁移已应用但收尾序列中断 |

SKILL.md exit-code 表与 JSON envelope 枚举同步加行（消费方是 slash-command UX）。
