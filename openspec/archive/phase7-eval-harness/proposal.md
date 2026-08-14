# phase7-eval-harness
## What
eval harness 确定性核心: oracle 10/10 自检 + 三臂 A/B/C 配置 + 五类故障注入定义。
## Why
重构有效性需可证明 (G5)。oracle 自检是确定性基线 (harness 能正确判别 orchestrator 行为); 三臂真实测量 deferred (需 #5/#6 完成后跑完整 orchestrator)。
## Scope
- scripts/kunglao_eval.py (module) + kunglao-eval.py (thin CLI wrapper)
- oracle_selfcheck: 10 已知答案例 (leverage/discriminator/novelty/cost/dispatchable/determinism)
- ARM_CONFIGS A/B/C + FAULT_TYPES 五类 + inject_fault (impossible 已验证)
- tests/test_eval_harness.py: 6 测试
## Acceptance
- oracle 10/10; pytest 6/6 + 172 全量绿
## Deferred
- 三臂 A/B/C 真实测量 (均值+容差判据, 需完整 orchestrator run)
- 防污染三探针; 其余四类故障注入的真实应用
