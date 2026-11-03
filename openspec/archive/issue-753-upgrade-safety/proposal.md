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


## Amendments (2026-10-19 — spec text synced to the as-built code per the §8.2 audit, docs/architecture/kunglao-technical-doc.md)

### Amendment A — B1: on the main migration path the dirty state is committed AS the snapshot; RC 6 is the no-snapshot/refresh-path face (§8.2 M4.2)

**Frozen text**: B1 "workspace 有 .git 且 dirty（`git status --porcelain`
非空）→ 新 `RC_DIRTY_WORKSPACE=6` 拒绝 … 未提交不升"; design D2
"dirty>0 → RC_DIRTY_WORKSPACE=6 + stderr commit/stash 指导（先拒绝，
什么都不写）"; design D4 "owned repo dirty | rc=6 拒绝，零写入".

**Owner ruling (2026-08-27, unchanged and still governing)**: "升级前要先
检测 git 检测未提交，然后 commit 之后再执行 upgrade，不然坏掉了都无法
回滚" — the ruling demands a rollback anchor BEFORE migration; it does not
mandate refusing when one can be created. The as-built reading: the
snapshot commit IS the rollback point — "the old RC 6 refusal on the
migration path is gone: the snapshot commit IS the rollback point the #753
ruling demanded, and committing beats refusing"
(scripts/kunglao_upgrade.py:1410-1413).

**New semantics**:

- Main migration path (upgrade, non-dry-run): a dirty owned repo is not
  refused — `git add -A` + identity commit land the current state
  (uncommitted work included) AS the pre-migration snapshot
  (`status: "committed"`). Clean repo: HEAD itself is the snapshot
  (`status: "clean-head"`). Repo-less: bootstrap init + anchor commit
  (`status: "created"`), #739 posture unchanged.
- RC_DIRTY_WORKSPACE=6 now fires in exactly two faces: (a) when NO
  snapshot can be taken (git broken / commit refused / zero-commit repo —
  `_refuse_no_snapshot`, "no rollback anchor — migration refused",
  REFUSED BEFORE any mutation), and (b) the #783 early-exit refresh path,
  which keeps the original dirty refusal via `_refuse_dirty`
  ("#753 B1 refusal face — shared by the main migration path and the #783
  early-exit refresh").
- The absolute rule stands in its ruling form: no snapshot -> NO migration
  (scripts/kunglao_upgrade.py:2188-2191).

**Implementing code**: `scripts/kunglao_upgrade.py:1403-1426`
(`_snapshot_pre_migration`; docstring 1404-1416),
`scripts/kunglao_upgrade.py:1430-1482` (`_snapshot_pre_migration_inner`;
dirty-commit face 1456-1477, "dirty state committed" event 1472-1474),
`scripts/kunglao_upgrade.py:1484-1497` (`_refuse_no_snapshot`),
`scripts/kunglao_upgrade.py:2188-2191` (main-path call + refuse),
`scripts/kunglao_upgrade.py:1284-1298` (`_refuse_dirty`) with the
early-exit caller at `scripts/kunglao_upgrade.py:2116`.

**Invariant**: INV-008 (`upgrade-transactional-flow`) — "upgrade =
snapshot, prune, deploy, configure, selfcheck, reload-prompt-or-rollback —
in that order, self-gated (#774)". This amendment redefines the SNAPSHOT
leg: the snapshot exists by construction (commit) or the run refuses;
an unsnapshotted migration is unreachable.

**Integration contract**: caller = `upgrade()`'s non-dry-run transaction
(scripts/kunglao_upgrade.py:2188), before the intake anchor backfill and
every migration item; trigger = every real upgrade run; firing
fingerprint = `[event] snapshot ok` (status committed / clean-head /
created) in the structured stderr stream, `git_snapshot_skipped` warn +
RC 6 on the no-snapshot face, `gate-dirty fail` + RC 6 on the
early-exit refresh face.

### Amendment B — 铁律: the rc=4 reconciliation is append-tolerant for the kunglao event-log class (#764) (§8.2 M4.5)

**Frozen text**: 铁律 "七个用户数据目录对账语义逐字节保持: rc=4 判定
不动" (byte-for-byte reconciliation semantics, rc=4 unchanged).

**Owner ruling (#764, implemented in PR #765)**: the iron rule tolerates
LIVE APPENDS to the kunglao event log while still rejecting rewrites,
reorderings, and deletions — verbatim from the implementing docstring:
"Kunglao event logs: append-tolerant — the pre-side filtered lines must be
an order-preserving prefix of the post-side filtered lines, so appends by
any live writer (the parent session's hooks, TTL renewals) pass while a
rewritten, reordered, or deleted protected line still trips"
(scripts/kunglao_upgrade.py:1057-1063).

**New semantics**:

- Non-log rels: ANY digest difference remains a violation (unchanged).
- Kunglao event logs (the `_is_log_rel` class): compared as filtered line
  sequences, not digests. The filter (scripts/kunglao_upgrade.py:980-999
  `_filtered_log_lines`) drops ONLY this tool's own rows
  (`actor=kunglao_upgrade`) and the TTL machinery's renew rows
  (`action=renew`); every other analysis event stays protected. PASS iff
  the pre-side filtered lines are an order-preserving prefix of the
  post-side filtered lines (scripts/kunglao_upgrade.py:1082); a rewrite,
  reorder, or deletion of a protected line still trips rc=4.
- Edge faces: a log created during the window has no pre-side key
  (nothing to protect — passes); a log over the capture cap falls back to
  the strict sha comparison; an unreadable post-side file yields no lines
  (violation).

**Implementing code**: `scripts/kunglao_upgrade.py:1055-1085`
(`_iron_violations`, #764) and `scripts/kunglao_upgrade.py:980-999`
(`_filtered_log_lines`).

**Invariant**: INV-006 (`iron-log-append-tolerance`) — "the upgrade iron
rule tolerates live appends to the kunglao event log and still rejects
rewrites/deletions (#764)"; the registry pins the check
`uv run pytest tests/test_upgrade_iron_log_764.py -q` (present in-tree,
tests/test_upgrade_iron_log_764.py).

**Integration contract**: caller = the post-digest reconciliation step of
`upgrade()`'s migration transaction (pre-digest vs post-digest over the
seven user-data dirs, scripts/kunglao_upgrade.py:2246-2260); trigger =
every completed migration run; firing
fingerprint = `[event] iron-rule fail` + rc 4 on a true violation; a
live-append window passes silently (rc 0 face) with the log rel absent
from the violation list. Issue 764 has no in-repo openspec directory of
its own — this section is the recorded home of its spec refinement, per
the §8.2 audit finding that the refinement lived only in code.
