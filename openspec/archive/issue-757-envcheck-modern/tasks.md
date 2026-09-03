# tasks — issue #757

- [x] 1.1 openspec scaffold (proposal/design/tasks; 用户裁决原文+日期入 design)
- [x] 2.1 T5 RED: tests/test_envcheck_modern_757.py 枚举段（mcp 合法值 / unknown 回落不变 / unset→vmr 不变）
- [x] 2.2 T5 GREEN: toolchain `_channel_backend` + mcp 动态分支零探测 HARD；init_channel_default MCP 常量
- [x] 3.1 T4 RED+GREEN: env_check channel 记录链读取 + 只读推导（resolve 运行时推导、不改盘）
- [x] 4.1 T1 RED: 类型×通道矩阵断言（android 无 vm 行 / web 无 vm+ghidra / docker 不读 VM_HOST）
- [x] 4.2 T1 GREEN: run() 上下文化 + check_vm_channel 重写 + ghidra 类型化（复用 _probe_native_so/_vm_probe_*）
- [x] 4.3 既有 test_env_check.py 断言迁移
- [x] 5.1 T2 RED+GREEN: mcp_registered 三口径 + 报告行接入
- [x] 6.1 T3 RED+GREEN: blocking/degraded 分级 + degraded 前缀 + schema 字段
- [x] 6.2 T3 gate 第三检查三路径（fresh REJECT / stale 放行 / absent 放行）+ SKILL.md Phase 0 措辞
- [x] 7.1 定向套件 → 净化 PATH 全套 → release_receipt → quality_gates → ruff
- [x] 7.2 PR + CI 绿（#767 release-check pass 6m30s；squash+delete 待 orchestrator）
