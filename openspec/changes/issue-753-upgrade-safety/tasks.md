# Tasks: upgrade 执行序安全 (#753)

## 1. SDD
- [x] 1.1 proposal / design 两件套（本目录）

## 2. RED（tests/test_upgrade_safety_753.py — 每 task 先写测试见其失败，再同 task 落 GREEN）
- [x] 2.1 B1: dirty owned-repo → rc=6 + stderr commit/stash 指导
- [x] 2.2 B1: 无 .git → .git 存在、首 commit 为 pre-upgrade anchor、revert HEAD 回锚点
- [x] 2.3 B1: 已有干净 repo 不被代提交、re-run 幂等
- [x] 2.4 B2: 成功路径 stderr ≥6 行 `[event]`、节点齐全、stdout 人读不变
- [x] 2.5 B2: 中断模拟（item 抛异常）→ 锚点在、末事件=migration-start
- [x] 2.6 B3: 成功 stdout 含 /reload-plugins；already-current 不含；init 成功 tail 结构性存在
- [x] 2.7 B4: monkeypatch `_emit` 抛 → rc=7（incomplete）、summary=fail 前有 stamp=ok
- [x] 2.8 envelope: rc6→refused-dirty / rc7→incomplete

## 3. GREEN（scripts/kunglao_upgrade.py）
- [x] 3.1 B1 gate/anchor + post-state commit + RC_DIRTY_WORKSPACE=6
- [x] 3.2 B2 stderr emitter + 全节点接线
- [x] 3.3 B3 upgrade/init 双成功路径 hint
- [x] 3.4 B4 tail 显式阶段 + RC_INCOMPLETE=7

## 4. 同步
- [x] 4.1 tests/test_kunglao_upgrade_726.py no-git 快照测试对齐 #753 新序（单点改写）
- [x] 4.2 skills/upgrade/SKILL.md exit-code 表 + envelope 枚举加 6/7
- [x] 4.3 scripts/event_taxonomy.py 注册 `git_anchor_skipped`

## 5. 门（全绿才 commit）
- [x] 5.1 pytest 753/726/748 三套 + 全量套 + release_receipt --check + quality_gates + ruff

## 6. PR
- [ ] 6.1 push + gh pr create（base dev）+ auto squash merge
## 附注（实现中确认）
- RED 观察: 每组测试先于实现失败（B3 以 stash 双脚本验证 RED），随本 task 同 commit 落 GREEN
  （纯 RED commit 会永久违反 Gate 2 全绿门槛，故按 task 粒度合并——裁决记入 design D5/报告）
- Gate 2/5: Gate 2 的 7 个红为本 host 基线（clean HEAD 复现同集合）；Gate 5 由
  .subagent-review/2026-08-27-753-b1.json 覆盖（gitignored 本地证据）
- ruff 唯一错误 F821(devkit/quality_gates.py yaml) 为 clean HEAD 既存基线
