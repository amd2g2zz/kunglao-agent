# reverify-legacy-via-index
## What
扩 `tools/audit_legacy_proven.py`:除了原 BLIND 分类,加"经索引溯原始证据"维度——对每条 PROVEN claim,查其 fact 的 provenance 是否引了 evidence/_index.json 的条目(path+hash 校验,复用 P2 provenance_gate 逻辑)。
## Why
P1 建了 evidence/_index.json;P2 建了 provenance_gate。46 假 PROVEN 现在可批量溯——但审计工具只做 BLIND 分类,不做索引可溯性审计。本 change 补审计维度,让每条 PROVEN 的索引溯源性可清账。
## Scope
- `tools/audit_legacy_proven.py`: 加 `_classify_traceability()` / `audit_traceability()` / 扩展 `audit_workspace()` 输出 `index_traceability` 字段
- 复用 `provenance_gate.extract_provenance_refs` + `build_evidence_index.build_index` (不写盘,只构建内存索引)
- 输出每条 PROVEN 的处置: `has-raw-evidence` / `derivation-only` / `unverifiable`
- `docs/refactor/audit-2026-08-10.md`: 更新报告(46 条索引可溯性清账)
## Acceptance
- RED1: PROVEN 的 fact provenance 引索引 eid + hash 匹配 → has-raw-evidence
- RED2: PROVEN 的 fact 引派生 summary.json(不在索引)→ derivation-only
- RED3: PROVEN 无 provenance 或 path 不存在 → unverifiable
- RED4: 空不崩
- 全量 pytest 绿
