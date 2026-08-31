# Tasks: kunglao upgrade (#726)

## 1. SDD
- [x] 1.1 proposal / design / tasks / spec 四件套

## 2. 词汇
- [ ] 2.1 EMIT_ACTIONS 注册 `upgrade` / `upgrade_item`（字母序位）

## 3. RED（tests/test_kunglao_upgrade_726.py）
- [ ] 3.1 合成 v0.1.2 workspace（旧戳/9-hook settings/hook_state 缺 completion_gate/用户数据）→ upgrade 后五项全修
- [ ] 3.2 用户数据 sha256 对账（戳行归一化）前后一致
- [ ] 3.3 dry-run 零写入 + 输出计划清单
- [ ] 3.4 已最新幂等 no-op
- [ ] 3.5 无戳 rc=3
- [ ] 3.6 快照落 runs/upgrade-snapshot.*.json
- [ ] 3.7 kunglao_log 含 upgrade + upgrade_item 事件
- [ ] 3.8 铁律守卫自测（monkeypatch 迁移触碰 facts → rc=4）

## 4. GREEN
- [ ] 4.1 scripts/kunglao_upgrade.py（注册表/守卫/快照/CLI）
- [ ] 4.2 scripts/kunglao.py upgrade 子命令
- [ ] 4.3 既有 init/wire-up/template_version 测试无回归

## 5. 门
- [ ] 5.1 全 7 门（host 账本 6 红口径）

## 6. 段提交（每段停等 mint）
- [ ] 6.1 docs（本四件套）
- [ ] 6.2 RED 套件
- [ ] 6.3 GREEN 实现
