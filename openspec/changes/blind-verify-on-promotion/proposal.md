# blind-verify-on-promotion
## What
claim 提升到 PROVEN 必须有独立 verifier 签字(verifier_sign_off block in fact file);否则自动降级 STAMP(不可信),不准 PROVEN。BLIND REFUTE 亦降级。加 tools/measure_blind_coverage.py 度量 PROVEN 中 BLIND 比例。
## Why
实测 47 PROVEN 中 46 条未经独立 BLIND 验证(98% 假 PROVEN)。claim_migrator 拦 worker 自提升但不拦 orchestrator 无凭据 promotion — orchestrator 可随意写 PROVEN。PRD verified-convergence M1: PROVEN = verified,无签字 = STAMP。
## Scope
- scripts/blind_gate.py(新): BLIND 签字解析 + PROVEN 门判据(纯函数)
- kunglao_record.claim_migrator: PROVEN 必经 blind_gate.check_proven_gate;无签字 → 写 STAMP 不写 PROVEN
- hooks/worker_budget.py::compare_register_change: orchestrator 经直写 register 绕 claim_migrator 时,PROVEN 无 BLIND → reject(双门)
- tools/measure_blind_coverage.py(新): claim-register + facts/ → PROVEN BLIND 覆盖率
## Acceptance
- test_blind_gate: RED1-RED4 全绿(4 tests)
- pytest 全量绿(≥182)
- openspec validate blind-verify-on-promotion PASS
