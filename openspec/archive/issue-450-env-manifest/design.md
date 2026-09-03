# Design — env manifest: 环境事实单一真相源 (#450)

## 问题边界

"环境事实单一真相源" = 把五类散落事实(VM 身份 / IP 发现 / 快照语义 /
VPMC / guest 通道差异)+ 布局约定收进**一个机器可读载体**
(`<workspace>/env-facts.yaml`,原名 env-manifest.yaml,2026-08-19 评审
F1 改名——旧名与 #478 deploy_env 写入每个工作区的部署台账
`{generated, project_type, components}` 同路径同名,碰撞导致 probe 重写
台账 / init 重跑清空环境事实),并提供单一加载点、文档渲染、最小
探测入口。需求侧("要不要 VM")已由 #449 `requirements_from_task_spec`
落地——本件**只消费**该函数,不改其语义。

**不是**本变更(范围外):

- 协商菜单 / install-consent(#451 领地;manifest 的写入协商走它)。
- vmr-shell SKILL.md 的文档段整体由 manifest 生成(issue 验收第 2 条
  的完整面)——本件交付 `--render` 段生成器,vmr-shell 文档改造在
  #451 后续消费;过期的 .128 IP 字面量清理属该面。
- checklist 三态脚本消费(issue 验收第 1/3 条的流程面)——依赖协商
  接口,manifest 先行。
- 其余 ~15 处 `malware-analysis-workspace` 副本(priority.py /
  failure_analysis_gate.py / heartbeat_tick.py / hooks_selfcheck.py /
  route_capability.py / search_gate.py / completion_gate.py /
  env_check_gate.py / reconcile_workers.py / convergence_health.py):
  issue 证据 2 引用的是 dispatch_gate + convergence_check 两个收敛面
  (worker 扫描经 #444 收编在 lib_kunglao);全面收编是后续机械工作,
  一次收三处(两收敛面 + glob 所在)已覆盖证据引用面。
- `requirements_from_task_spec` / `load_task_spec` 的任何语义修改
  (#449 硬约束)。

## D1. 数据模型落点:`scripts/env_manifest.py`(独立新文件)

不并入 toolchain.py(1294 行,超 800 行文件上限;且 hooks 侧消费布局
时不应拉起 toolchain 的 mcp_probe/platform_paths 依赖链)。独立模块,
仅依赖 stdlib + yaml(#449 的 toolchain 依赖在 `_derive` 内**惰性
import**,hook hot path 的布局查询不触发)。

```python
@dataclass(frozen=True)
class SnapshotSemantics:   # name / autologin: bool|None / rollback_fix: str|None
@dataclass(frozen=True)
class VmIdentity:          # vmx_path / ip_discovery="live-dhcp" / snapshot /
                           # vpmc_compatible: bool|None / frida_start: str|None
@dataclass(frozen=True)
class GuestChannel:        # preferred: str|None / notes: str|None
@dataclass(frozen=True)
class LayoutConventions:   # workspace_dir / claim_register /
                           # worker_worktree_glob / worker_worktree_marker / runs_dir
@dataclass(frozen=True)
class EnvManifest:         # needs_vm / basis / vm / guest_channel / layout /
                           # source ("manifest-file"|"task-spec"|"default")
```

**保守默认**(`DEFAULT_MANIFEST` / `DEFAULT_LAYOUT`):needs_vm=True
(basis 注明保守默认);vm 字段全 None/unknown,唯 ip_discovery=
"live-dhcp"(issue 设计方向:DHCP live-discovery 强制,禁缓存 IP——
这是**策略**不是具体值);guest_channel 全 None(渲染时输出通用
known-pitfall 指引);`DEFAULT_LAYOUT` = 现行字面量
(`malware-analysis-workspace` / `claim-register.yaml` / `.wt-*` /
`.kunglao-worktree` / `runs`)——**向后兼容锚**:布局字符串在代码中
仅存在于 env_manifest.py 一处。

**具体值不硬编码**(硬约束):IP、VMX 路径、启动命令、快照修复链
名(如 fix-c328.cmd)只出现在 manifest **数据**里;代码/默认值/渲染
模板只含通用指引("run the recorded rollback_fix step")。

## D2. 来源优先级与单一加载点

```
resolve(ws):
  raw = load_manifest(ws)          # 单一加载点,fail-closed(下)
  needs_vm = raw.needs_vm 若为 bool
           否则 requirements_from_task_spec(load_task_spec(ws))  # #449 只消费
           否则 DEFAULT
  layout   = raw.layout 合并 DEFAULT_LAYOUT(逐字段,字符串非空校验)
```

- `load_manifest(ws)`:absent → None;YAMLError / OSError(不可读,
  Windows 锁/权限,镜像 #449 M2)/ 非 mapping / version 非 1 →
  **ValueError**。fail-closed 语义:garbage 从不静默产出捏造的环境
  事实。
- **#478 台账碰撞防御(评审 F1)**:读到台账 shape(无 version 键而有
  generated/project_type/components)→ **ValueError + 指引**(该文件是
  部署台账非环境事实),双名均拒收——新名 env-facts.yaml 里出现台账
  内容、或旧名 env-manifest.yaml 本就是台账,都不静默当 manifest
  消费。旧名仅作 fallback:version 在场的改名前事实文件仍可解析;
  台账则报错。probe 只读写 env-facts.yaml,旧名台账永不触碰;故
  init 台账重写与 probe 事实写入互不干扰(三方数据保全)。
- `needs_vm` 在 manifest 文件里**可选**:探测写入时不写该键(见 D4),
  缺失即回落 task_spec 推导——一个纯默认 manifest 文件不会把
  static-only 工作区重新硬化为 VM 必需(写坏优先级链的隐患)。
- 两个包装面,失败姿态不同(与 #449 `main()` 的 WARNING+保守同构):
  - `layout_conventions(ws)`(**hook hot path,永不 raise**):resolve
    抛 ValueError → DEFAULT_LAYOUT + 一次 stderr 警告。保守 = 现行
    字面量,garbage 不产生捏造布局,也不让 dispatch_gate 崩。
  - CLI `--render`(严格面):ValueError → stderr ERROR + exit
    RC_MANIFEST_DEFECT——渲染错误环境事实是 stop event。

## D3. 字面量收编(向后兼容锚:缺 manifest 逐字节一致)

三个消费点,全部 `layout_conventions(ws)` 供名:

- `hooks/dispatch_gate.py:_resolve_workspace`:先经
  `manifest_path_for(cwd)` 自举发现(cwd 本身或
  cwd/DEFAULT_LAYOUT.workspace_dir 下的 env-facts.yaml——发现用
  默认名,**bootstrap 字面量仅在 env_manifest.py 一处**),再以
  `layout.workspace_dir` / `layout.claim_register` 逐候选探测。
- `scripts/convergence_check.py:_resolve_ws`:同上(无 payload,直接
  os.getcwd())。
- `hooks/lib_kunglao.py:iter_worker_states`:
  `ws.parent.glob(layout.worker_worktree_glob /
  layout.worker_worktree_marker)` + `wt.parent /
  layout.workspace_dir` + `layout.runs_dir`。lib_kunglao 惰性
  import env_manifest(scripts/ 入 sys.path,dispatch_gate 同款);
  import 失败 raise RuntimeError(#444 先例:hooks/ 与 scripts/ 同装
  配发,缺文件 = 破损安装,不是降级模式)。

缺 manifest → DEFAULT_LAYOUT → 候选序、glob 串、固定名与现行完全
一致(既有 test_worktree_marker / test_dispatch_* / golden 全绿锚定)。

## D4. CLI:`--render`(文档生成)与 `--probe`(最小探测入口)

`python scripts/env_manifest.py <ws> [--render | --probe | --json]`:

- **`--render`**:输出 env 环境说明段(markdown):VM 通道
  REQUIRED/NOT REQUIRED(basis)/ VM 身份(vmx_path 或 unknown +
  probe 指引)/ IP 发现策略(live DHCP,禁缓存)/ 快照语义(name /
  autologin / rollback_fix,或 unknown + 回滚前核验指引)/ VPMC(状态
  或 unknown + KB 症状指引)/ guest 通道(preferred + notes,或通用
  known-pitfall)。数据全部来自 manifest;garbage → exit 1。
- **`--probe`**(seam `_subprocess_run = subprocess.run`,#449 同款):
  `shutil.which("vmrun")` → `vmrun list` 解析运行中 vmx 路径 →
  对首个 `vmrun checkToolsState <vmx>` 记录 Tools 状态(通道差异的
  证据基线);`vmrun listSnapshots <vmx>` 记录快照名。**合并写入**
  (既有 manifest 的用户字段保留,探测只补 vmx_path / 快照名 /
  guest_channel.notes 的 toolsState);不写 needs_vm。失败面全部
  fail-open:无 vmrun / rc!=0 / 无运行 VM → 打印保守默认 + 指引,
  exit 0,不阻塞;唯一例外:既有 manifest garbage → 拒绝覆写
  exit RC_MANIFEST_DEFECT(用户数据不可静默重建)。
- 默认(无旗标):resolved manifest 的 JSON 摘要(source/basis/
  needs_vm/layout)。

## D5. CLAUDE.md "VM required" 条件化(#449 遗留收口)

`kunglao-init.write_claudemd`:type_section 渲染后,经
`env_manifest.vm_requirement_for(ws)`(resolve 的 try 包装)取
(needs_vm, basis):

- **None 或 True** → section 不动(无 manifest + 无 task_spec 时与
  现状**逐字节一致**,renderer golden 锚定)。
- **False** → 含 `- **VM required**:` 的行替换为
  `- **VM not required**: <basis> — VM channel informational (WARN),
  not a T2+ hard requirement for this task.`(行级替换,其余行不动;
  替换函数 `conditionalize_vm_required` 在 env_manifest.py,标记串
  `**VM required**` 单源)。

garbage env-facts(含 #478 台账内容,双名)→ vm_requirement_for 返回
None + stderr 警告(保守 = 无条件行;同一 garbage 在 CLI render 面已是
exit 1,双面姿态与 #449 的 gate/render 分层一致)。

## D6. 验收 → 测试映射(见 tasks.md)

| #450 面 | 测试(tests/test_env_manifest.py) |
|---|---|
| 数据模型 + 优先级链 | `test_resolve_*`(file>taks-spec>default;garbage ValueError) |
| 加载点 fail-closed | `test_load_manifest_*`(absent→None;garbage/non-mapping/unreadable→ValueError) |
| 布局收编逐字节一致 | `test_layout_defaults_are_pre450_literals` + dispatch/convergence/lib_kunglao 三消费点的缺 manifest 行为锚 |
| 布局可覆写 | `test_dispatch_workspace_custom_layout` / `test_convergence_custom_layout` / `test_worktree_scan_custom_layout` |
| hot path 不崩 | `test_layout_conventions_garbage_never_raises` |
| render 段生成 | `test_render_*`(默认/task-spec/manifest 数据三态) |
| render garbage fail-closed | `test_cli_render_garbage_exits_defect` |
| probe 最小 + fail-open | `test_probe_*`(发现写入/合并保留/无 vmrun 指引不阻塞/拒覆写 garbage) |
| CLAUDE.md 条件化 | `test_claudemd_*`(static-only → not-required 行;无输入 → golden 逐字节) |

## Rejected

- **R1 并入 toolchain.py**:文件超限 + hook 依赖链污染(见 D1)。
- **R2 probe 写 needs_vm**:探测回答"环境现状",不回答"任务要不要
  VM"(需求侧 #449);写死会把 static-only 工作区重新硬化。
- **R3 收编全部 ~20 处布局副本**:issue 证据面是 dispatch_gate +
  convergence_check(+glob 所在 lib_kunglao);一次收三处覆盖证据
  引用,其余是后续机械批量(避免本件 diff 爆炸、回归面失控)。
- **R4 布局查询 fail-closed(raise)**:dispatch_gate 在每次 Agent
  派发上跑;garbage manifest raise 会以最脆的方式破坏派发。保守默认
  + 警告 = #449 的 WARNING+保守 HARD 同构,严格面留在 render/probe。
- **R5 probe 做 CAPABILITY 级探测**(起 VM / 挂 runProgramInGuest 试
  挂死):分钟级 + 有副作用,#474 契约 init-only;probe 停在
  PRESENCE/LIVENESS(vmrun list / checkToolsState 均只读)。
- **R6 vmr-shell SKILL.md 文档段全量生成**:#451 协商面;本件先交
  `--render` 生成器。
- **R7 默认值携带具体路径/IP/命令**(如 C:\vms-tmp、.128、
  fix-c328.cmd):硬约束——具体值属 manifest 数据,代码只含通用
  指引 + 策略(live-dhcp)。
