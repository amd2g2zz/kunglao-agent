# issue-809 migrate_facts 毒化修复 — proposal

## 背景
豆包现场：通用迁移脚本携带为样本 865e8eb4 定制的 FACT_MIGRATION_MAP，按工作区本地序号 F<NNN> 撞键，6 个 fact 被另一样本语料覆盖（title/source/slug/promotion_gate 全套）。SAMPLE_HASH 定义了但从未参与校验；_INDEX.md 头硬编码他样本哈希；migrate 全程零审计。

**边界声明**：本卡原始现场的用户 WIP 已丢失（2026-08-31 确认），本实现基于 HEAD 的 migrate_facts.py。

## 变更
1. **毒表迁出通用脚本**：内置 FACT_MIGRATION_MAP/SAMPLE_HASH 删除；curated map 改为 `--map <path.json>` 显式加载（`{"sample_sha256": ..., "facts": {...}}`）。无 map = 纯 conservative defaults。
2. **样本指纹 gate**：--map 加载后先算 `bins/` 内容指纹，与 map.sample_sha256 不匹配 → map 整体 inert + 响亮 warning + `env_incident` 落账；匹配才应用 curated 语义。
3. **malformed map 预检 fail-closed**：JSON 损坏/形状错误 → 在任何写入前退出（exit 1），留审计。
4. **_INDEX 头去他样本哈希**：`regenerate_index` 硬编码 865e8eb4 → 通用头。
5. **审计面**：migration start/done/inert 全部 kunglao_log.emit（claim_migrate/env_incident，均注册词）；模块头装饰性 emit（NameError 吞掉）删除。
6. **Bash 通道纳管**：新 hooks/bash_fact_guard.py（PostToolUse/Bash，recorder 姿态 fail-open）——命令写了 facts/*.md 即逐文件 lint，违规 → write_blocked 落账 + additionalContext 响亮提示；接 hook_activation。

## 既有件确认
- #809-P1 "write_guard 增量化" 已由 #820 合入件覆盖（lint 归因化），本 PR 不重复。

## 验收
- 撞键/异样本属性测试：map 样本指纹不匹配 → title/source/body 零变化
- 指纹匹配 → curated 应用；无 map → conservative；malformed → exit 1 零写入
- 重跑幂等；Bash 通道违规写 → 落账 + 上下文告警；合规/无关命令静默
