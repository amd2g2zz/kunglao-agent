# phase9-e2e-acceptance
## What
acceptance_check.py: 端到端静态验收 (§2.3 五条静态可达项)。
## Why
证明重构核心机制就位 + 可运行 (G1-G5 静态部分)。动态真实样本 run 属生产 skill 职责。
## Scope
- scripts/acceptance_check.py: run_acceptance() → 5 checks, 写 runs/e2e-acceptance-<ts>.json
- tests/test_acceptance.py
## Deferred
动态验收 (真实样本 run + cold-start ≤38K + 用户干预计数)
