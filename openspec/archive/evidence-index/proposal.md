# evidence-index
## What
build_evidence_index.py 扫 evidence/ + analysis_artifacts/ 注册 raw 证据(排除派生),写 _index.json(权威)+_INDEX.md。
## Why
无索引层 → 原始存在却不可溯;F023 引派生 summary.json;46 re-verify 无索引无法批量。P1 是 P2/P3/P5 的前提。
## Scope
- tools/build_evidence_index.py: build_index / build_and_write / classify / sha256
- 排除 DERIVATION_NAMES(summary/correlated/verdict/loop-state/.heartbeat/_index)
- 每条 {eid, path, sha256, size, type}
## Acceptance
6/6 测试 + 217 全量绿
