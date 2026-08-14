# Design — phase8-cli-convergence
8 CLI = 用户面; 内部模块 (gates/helpers) 不算 CLI。kunglao-digest.py 补齐第 8 (wrapper → digest_build.py module, 同 kunglao-verify/record 模式)。
kunglao.py 当前为 Phase 3 subcommand 形式 (decide/tick/health); 转 loop-entry 是 orchestrator 重构, 非本 issue 范围 (deferred, 不影响 8-CLI 表面成立)。
