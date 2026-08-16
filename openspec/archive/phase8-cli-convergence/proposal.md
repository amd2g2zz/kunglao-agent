# phase8-cli-convergence
## What
8 独立 CLI 收敛定稿: kunglao.py + kunglao-decide/verify/record/monitor/init/eval/digest。补 kunglao-digest.py wrapper (第 8 个)。
## Why
用户面 CLI 表面清晰 (plan §8: 31 散落 → 8 独立)。每 CLI 单一职责, 不共享 argparse。
## Scope
- scripts/kunglao-digest.py: thin wrapper (第 8 CLI)
- tests/test_cli_matrix.py: 8 CLI --help exit 0 + 无 kong-* 残留
## Deferred
- kunglao.py 从 subcommand 形式 (Phase 3) → 纯 loop-entry (无子命令): 更深的 orchestrator 变更, 后续
## Acceptance
- 8 CLI --help 全 exit 0; pytest 3/3 + 175 全量绿
