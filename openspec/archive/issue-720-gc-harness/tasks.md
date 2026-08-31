# GC Harness v1 — Tasks (#720)

## 1. SDD
- [x] proposal.md（三目标 + 验收 + out-of-scope）
- [x] design.md（D1-D9 取舍）
- [x] specs/gc-harness/spec.md（契约）
- [ ] tasks.md 本文件

## 2. RED（tests/test_gc_harness_720.py）
- [ ] spec orphan 超 90d → ARCHIVED（--apply 写状态）
- [ ] spec 有代码引用零测试引用 → SUSPECT
- [ ] spec search 输出 Existing + Decision
- [ ] 重复 spec 只报告不自动合并
- [ ] test last_failure>180d → 候选
- [ ] quarantine 移动+restore 恢复
- [ ] quarantine 超 30d → 删除候选（--apply 删）
- [ ] worktree merged+7d → 候选；abandoned+14d → 候选（tmp git repo）
- [ ] budget 观察: 超预算 WARN；justification 文件放行说明
- [ ] init 登记只登记不裁决

## 3. GREEN
- [ ] gc-harness/_common.py（config/registry/日期）
- [ ] gc-harness/spec_gc.py（search/scan/init）
- [ ] gc-harness/test_gc.py（scan/quarantine/restore/expire/experiment/record/init）
- [ ] gc-harness/worktree_gc.py（scan/--apply）
- [ ] gc-harness/config.yaml（§11 默认值）
- [ ] .gitignore + .agent/ 约定
- [ ] devkit/quality_gates.py 观察区 _observation_artifact_budget

## 4. 门与 dogfood
- [ ] 全 7 门（host 账本仅 probe_tiers×2）
- [ ] 本 PR 净增统计过自己的 budget 门（数字入 PR 正文）
