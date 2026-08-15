# icd203-probability-dissent
## What
confidence_schema.py 定义 ICD-203 7 档概率阶梯 enum + 旧 3 档映射; blind_gate.py REFUTE 路径写结构化 dissent(verifier_id, finding, evidence_path, ts)。
## Why
ICD-203 #2 要求 7 档概率阶梯(现有仅 3 档); #8 要求 dissent 正式记录(BLIND REFUTE 当前无结构化记录位)。
## Scope
- scripts/confidence_schema.py: 7 档 enum + map_legacy_confidence() 兼容旧 3 档
- scripts/blind_gate.py: record_dissent() 在 REFUTE 时写结构化 dissent 块
- tests/test_confidence_schema.py: 7 档校验 + 映射
- tests/test_blind_gate.py: dissent 记录测试
## Acceptance
新测试全绿 + 既有 217 全量绿(P2/P3 并行文件不碰)
