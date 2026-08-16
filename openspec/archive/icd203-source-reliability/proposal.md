# icd203-source-reliability
## What
build_evidence_index.py 每条 index entry 加 `source_reliability`(Admiralty A-F × 1-6)。机械默认按 type 赋值;`--rel reliability_map.yaml` 可覆盖。度量脚本报告覆盖率。
## Why
ICD-203 Tradecraft #1 要求描述源质量/可靠性。P1 index 每条有 type 但缺 source_reliability,不合规。
## Scope
- tools/build_evidence_index.py: 加 source_reliability 字段 + 机械默认 + `--rel` 选项
- 新增 `_default_reliability(type) -> str` 和 `_apply_reliability_override(entries, rel_map)`
- tools/measure_blind_coverage.py: 扩 `--reliability` 模式报告 index 中 source_reliability 覆盖率
- 不碰 scripts/provenance_gate.py(P2 并行)
## Acceptance
- 全部 index entry 有 source_reliability 字段
- 机械默认:capture/trace/dump/binary→A1, decompile/disasm→A2, yara-scan→B2, json→B3, CTI→C5, sandbox→D3
- `--rel` 自定义 map 覆盖默认
- 217+ tests green
