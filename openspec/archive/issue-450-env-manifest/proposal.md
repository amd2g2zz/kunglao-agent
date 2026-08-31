# Env Manifest: 环境事实单一真相源 + 文档生成 (#450)

## Why

Issue #450(milestone v0.1.2,D3 环境模型缺位;分层条目 L4-1~L4-8)。
环境属性没有机器可读载体,分散在文档缓存(会过期)、快照隐含状态
(无人记得)、口头经验(不传承);每个新会话用撞墙法重新发现。三份
证据:

1. **环境事实散落五处**(2026-08-17/18 实测清单):分析 VM 身份
   (work_env=C:\vms-tmp\...,靠用户口头纠正,agent 曾自选 D:\vms VM 并
   改其配置被打断)/ VM IP(vmr-shell SKILL.md 写死 .128,DHCP 实际
   租约三轮变化,文档首轮即错)/ frida 启动方式(SKILL.md 引用不存在
   的 Desktop\start-frida.cmd)/ 快照语义(analysis-ready 无 autologin,
   登录态修复链永不触发)/ VPMC 兼容性(宿主嵌套不支持
   vpmc.enable=TRUE,两台 VM 自 08-13 无法开机,17 号才再次撞上)/
   guest exec 通道差异(runProgramInGuest 在 legacy Tools 12416 下永久
   挂死,runScriptInGuest 秒回,多次挂死才试出)。
2. **布局字面量嵌在逻辑里**:`hooks/dispatch_gate.py` `_resolve_workspace`
   的 `cwd / "malware-analysis-workspace"`、`scripts/convergence_check.py`
   `_resolve_ws` 的同名固定名、worker 扫描的 `.wt-*/.kunglao-worktree`
   glob 与 `runs` 固定名(#444 后收编在 `hooks/lib_kunglao.py`)——
   布局约定以字符串散布于 hooks 与 scripts 两层。
3. **checklist 缺失的直接后果**(时序):VM 通道修复耗时 ~40 分钟、
   4 次开机循环;而全部所需事实(哪台 VM/什么快照/怎么起服务/已知坑)
   以只读方式列出只需 3 条命令(vmrun list / listSnapshots / 读 VMX)。

#449 已落地需求侧(`requirements_from_task_spec` / `Requirements`):
"要不要 VM"由 task_spec 派生。本件落**事实侧**:VM 是哪台、什么快照、
怎么起服务、已知坑——机器可读 env manifest。

## What Changes

- **manifest 数据模型**(`scripts/env_manifest.py`,新文件):
  `EnvManifest` frozen 数据类(vm 身份 vmx_path / ip_discovery(DHCP
  live-discovery 强制,禁缓存 IP)/ snapshot 语义(autologin /
  rollback_fix)/ vpmc_compatible / frida 启动方式数据字段;guest 通道
  差异 preferred+notes;`LayoutConventions` 布局约定)。**来源优先级:
  workspace env-facts.yaml(用户/探测写入;原名 env-manifest.yaml,
  2026-08-19 评审 F1 改名——与 #478 部署台账同名碰撞,台账 shape 双名
  均拒收)> #449 Requirements 推导
  (只消费 `requirements_from_task_spec`,不改其语义)> 保守默认**。
  单一加载点 `load_manifest`:absent → None;garbage / 不可读 / 非
  mapping → ValueError fail-closed(镜像 #449 M2)。具体值(IP/路径/
  启动命令)不硬编码进代码,属 manifest 数据。
- **字面量收编**:`dispatch_gate._resolve_workspace`、
  `convergence_check._resolve_ws`、`lib_kunglao.iter_worker_states`
  (.wt-* glob + runs)改为从 manifest 布局读;**缺 manifest 时行为与
  现状逐字节一致**(DEFAULT_LAYOUT = 现行字面量,向后兼容锚,既有
  测试含 golden 全绿)。hot path 走 `layout_conventions`(garbage →
  默认布局 + 一次 stderr 警告,fail-open 姿态;严格 fail-closed 面在
  load_manifest / CLI render)。
- **文档生成**:`python scripts/env_manifest.py <ws> --render` → env
  环境说明段(needs_vm / VM 身份 / IP 发现策略 / 快照语义 / VPMC /
  guest 通道差异,按 manifest 数据渲染);kunglao-init 的 CLAUDE.md
  "VM required" 行按 resolved needs_vm 条件化(替代 #449 遗留的无条件
  文案;无 manifest+无 task_spec 时逐字节不变,golden 锚定)。
- **探测入口(最小)**:`--probe` 经 seam(`_subprocess_run`)跑
  `vmrun list` / `vmrun checkToolsState` 枚举现状写入 manifest(合并
  保留用户字段);探测失败(无 vmrun / 无运行 VM)fail-open 输出保守
  默认 + 指引,不阻塞(exit 0);拒绝覆写 garbage manifest(exit 1)。

## Impact

- **代码**:`scripts/env_manifest.py`(新)、`hooks/dispatch_gate.py`
  (_resolve_workspace)、`scripts/convergence_check.py`(_resolve_ws)、
  `hooks/lib_kunglao.py`(iter_worker_states)、`scripts/kunglao-init.py`
  (CLAUDE.md VM-required 行条件化)。
- **测试**:新增 `tests/test_env_manifest.py`;既有 dispatch /
  convergence / worktree-marker / renderer-golden 测试零回归(缺
  manifest 路径逐字节锚定)。
- **不做**(见 design.md Rejected):协商菜单(#451)、vmr-shell 文档
  全量生成段(issue 验收第 2 条的完整面,#451 后继消费 render 输出)、
  checklist 读写消费面(issue 验收第 1/3 条的流程面,依赖 #451 协商)、
  其余 ~15 处 `malware-analysis-workspace` 副本(priority.py /
  heartbeat_tick.py 等,非本件证据引用的 hooks/scripts 两层收敛面)、
  #449 `requirements_from_task_spec` 语义(只消费)。

需求源: issue #450 (github.com/amd2g2zz/kunglao-agent/issues/450)
架构约束: #498(决策循环一体化)/ #449(需求侧已就位,本件为事实侧)
