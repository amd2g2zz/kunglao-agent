# Tasks: issue-818-logging-schema (batch 1)

## 1. SDD

- [x] 1.1 proposal.md + tasks.md（本目录）

## 2. TDD

- [x] 2.1 先写 `tests/test_logging_schema_818.py` 5 例并跑红（emit TypeError / null 键缺失 / version KeyError / decide 快照 0 条）
- [ ] 2.2 实现 emit 四字段（arm/epoch/version=git SHA 自动填充/hypothesis_ref）+ `_repo_sha()`（缓存、失败→None）
- [ ] 2.3 EMIT_ACTIONS 增加 `decision_snapshot`
- [ ] 2.4 decide() emit decision_snapshot（状态计数 + top-5 (id,score)，fail-open）
- [ ] 2.5 全绿 + 全仓回归

## 3. 质量门与交付

- [ ] 3.1 本地质量门：pytest 全量 + ext-scan + deploy_manifest
- [ ] 3.2 push + PR→dev（验收清单+复现命令），不 merge
