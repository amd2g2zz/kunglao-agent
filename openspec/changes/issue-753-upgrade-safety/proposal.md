# Proposal: upgrade 执行序安全 — git 先行/dirty 拒绝/结构化事件/reload-plugins 提示/收尾原子性 (#753)

## Why

现场事故（#753 原始记录）: 事件日志见 `upgrade_item`×5 applied + stamp 刷新，但总结事件
（`_emit(ws,"upgrade",...)`）缺失、`ensure_git_snapshot` 的第一个动作（写 .gitignore）未发生、
`.git` 不存在——进程在 stamp 之后被外杀，无回滚点、无现场痕迹（`_emit` 是 try/except pass
静默面）。用户裁决（2026-08-27，原文）:

> "升级前要先检测 git 检测未提交，然后 commit 之后再执行 upgrade，不然坏掉了都无法回滚"

即: **migrate 前必须 git commit，坏掉能回滚**。

## What Changes

- **B1 git 先行锚点**: `upgrade()` 在执行 migration items 之前:
  - workspace 有 `.git` 且 dirty（`git status --porcelain` 非空）→ 新 `RC_DIRTY_WORKSPACE=6`
    拒绝，stderr 给出 commit/stash 指导；已有 .git 且干净 → 直接进 migration
  - workspace 无 `.git` → 先 init + 一次 pre-migration commit（复用 #739 的身份/签名约定，
    commit message 标 pre-upgrade anchor），迁移完成后再落一次 post-upgrade state commit，
    保证 migration 后可 `git revert` 回锚点
- **B2 结构化事件**: stderr line-based emitter `[event] name=<name> status=ok|warn|fail detail=<...>`，
  覆盖 gate-dirty/git-anchor/migration-start/item/iron-rule/stamp/summary/git-snapshot；
  stdout 人类可读输出保持既有
- **B3 reload-plugins 提示**: 成功路径（RC_OK 前）打印 `/reload-plugins` 提示；init 成功 tail 同款
- **B4 收尾原子性**: 尾部（stamp → summary → git snapshot）包成显式阶段；summary 事件未发出时
  main 返回新 `RC_INCOMPLETE=7` 而非静默 RC_OK。进程级中断由 B1 锚点（可 revert）+ B2 事件流
  （死前最后事件可追溯）共同兜底

## 铁律（不变）

七个用户数据目录对账语义逐字节保持: rc=4 判定不动；锚点的 `.gitignore` 属框架脚手架不参与
digest（digest 只扫七目录）。

## 安全面

- dirty owned-repo 不再被升级动过（rc=6 先拒绝）
- legacy no-git workspace 升级前获得回滚锚点（此前唯一快照在升级之后——中断即裸奔）
- 中断可观测: stderr 事件流 + 非零退出码，不再有"stamp 后静默死亡"
