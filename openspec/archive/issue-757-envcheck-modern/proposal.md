# env_check 现代化 — type/channel 感知 / MCP 检查 / FAIL 分级 / channel 补建 / mcp 后端 / VM_HOST 收窄 (#757)

## Why

`scripts/env_check.py` 的 checks dict（L401-409，#757 现场）写死 7 项，与
2026-08 已落地的 type/channel 体系脱节：

- `check_vm()` 连 project_type 参数都没有——android/web 工作区照探 vmr 的
  vmr-shell 端口；现场验收案例：web workspace 被 0.1.2 init_state 误杀
  （#750 评论 5428715168），且 KUNGLAO_VM_HOST 被无条件读取。
- 零 MCP 检查——init 侧已有 mcp_probe（#407/#316），Phase 0 却看不见。
- FAIL 分级只存在于 SKILL 叙事文本；真正拦 dispatch 的 hooks/env_check_gate.py
  只查 agent_teams_flag + init 完整性两项。
- #727 的 channel 决策只写新 init 的 .init-report.json；老 workspace 现场
  channel:null——没有运行时推导。
- #698 用户裁决"变量跟通道走，docker 明文 no KUNGLAO_VM_HOST required"，
  env_check 却无条件读 KUNGLAO_VM_HOST。

## What Changes

- **T1 (F1+F6)**：run() 读 workspace 上下文（project_type 经 init_state；
  channel 经 显式 env/.env → .init-report.json channel 块 → analysis_state.txt
  行的记录链）。vm_reachability 重写为 channel 感知：仅 vmr 探测
  （KUNGLAO_VM_HOST + TCP 9876/1337 现语义）；ssh/docker/adb 复用 toolchain
  探测函数（`_vm_probe_ssh/_vm_probe_docker/_vm_probe_adb`）；local →
  static-only 说明；mcp/web → 不探测。ghidra 检查类型化：android 主判定
  jadx/baksmali + native .so 才要求 decompiler（复用 #756 `_probe_native_so`
  central-directory 版）；web 不查 ghidra（decompiler trials meaningless for
  web — #728 design D5 原文）。其余既有项不动。
- **T2 (F2)**：新检查 `mcp_registered`（mcp_probe.registered_names 三面）：
  web 期望 camoufox-reverse；android 无硬性期望 PASS-with-info；
  windows/linux ghidra/ida-pro-vm 任一 WARN "capability unverified"
  （#474 同口径）。FAIL 一律不 blocking。
- **T3 (F3)**：每项 check 增 `blocking: true|false` 字段；blocking FAIL
  （agent_teams_flag/init_complete/hooks_deployed）→ overall=FAIL（现语义）；
  degraded FAIL（vm_reachability/ghidra/mcp_registered）→ overall 仍 PASS +
  `degraded: [names]` + detail 前缀 "T3-restricted: "。gate 增第三检查：
  读 runs/.env-check.json——存在且 blocking FAIL 且新鲜（10min）→ REJECT；
  stale/absent/corrupt/legacy-schema → fail-open 放行。
- **T4 (F4)**：workspace 无 channel 记录时运行时推导
  （复用 init_channel_default.resolve_init_channel）——**只写报告不改盘**
  （持久化归 #755 upgrade item；避免两 PR 撞写路径），报告注明 derived。
- **T5 (F5)**：channel 枚举增 `mcp`（toolchain `_channel_backend` 合法值 +
  init_channel_default 常量体系 + env_check 分支）。web 默认通道语义：
  动态面=MCP 可达性（= mcp_registered 结果），无命令通道探测。

## Acceptance（tests/test_envcheck_modern_757.py）

1. android workspace + KUNGLAO_VM_HOST 未设：vm_reachability 不出现（不再 blocking FAIL）
2. web workspace：无 vm/ghidra 探测、mcp_registered 查 camoufox、channel=mcp
3. blocking/degraded 分级矩阵（blocking: true/false 字段全量落报告）
4. gate 第三检查三路径：fresh-blocking REJECT / stale 放行 / absent 放行
5. 既有 test_env_check.py 断言迁移（vm 场景按 channel+分级改写）

## Out of scope

- 持久化推导出的 channel 到盘（归 #755 upgrade item）
- env-manifest / CLAUDE.md 写盘（#755）
- toolchain 对 mcp 后端的执行层实现（#698 D5 execution layer 声明性内容）
