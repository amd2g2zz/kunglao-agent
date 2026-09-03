# Design: env_check 现代化 (#757)

## 用户裁决（原文 + 日期）

- **2026-08-27（F5 判）**："web 不需要任何控制通道，可能有新类型就是 MCP，
  web 只要求浏览器可以通" → channel=mcp 后端：web 的动态面是 MCP 可达性
  （= mcp_registered），不是任何命令控制平面。
- **2026-08-27（F6 判）**："KUNGLAO_VM_HOST 只适用于 windows" → 该变量只在
  channel=vmr 的探测分支被读取（windows/linux 工作区）；docker 分支明文
  "no KUNGLAO_VM_HOST required"（#698 D4 原文）；android 不产生 vm 行；
  web/mcp/local 均不读取。

## A1 — 上下文读取链（T1/T4）

```
project_type: .kunglao-init.json marker (primary, #625) → init_state.read_project_type()
channel 记录链（按优先级，取第一个非空）:
  1. KUNGLAO_CHANNEL env / <ws>/.env 有效视图（load_dotenv 合并，env 赢）
  2. runs/.init-report.json 顶层 channel.selected（#727 新 init 写入）
  3. analysis_state.txt 的 `KUNGLAO_CHANNEL=<value>` 行（#728 web 默认写入处）
  4. 全无 → 运行时推导 init_channel_default.resolve_init_channel(ws)
     （探针只读；结果只进报告，绝不落盘——持久化归 #755 upgrade item，
      报告注明 "derived — run /kunglao-agent:upgrade to persist"）
```

归一化与 #698 D2 口径一致：strip/lower；未知值回落 vmr 且 note 指名原值。
优先级理由：环境变量是"当下显式意图"（#698 变量跟通道走），压过持久化旧
记录；记录链存在的意义正是变量未设时的回看。

## A2 — web 类型强制 mcp 面（adjudication）

project_type=web ⇒ 生效通道一律 mcp。即使 analysis_state.txt 携带 #728 写入的
`KUNGLAO_CHANNEL=docker` 行也视为对 web 无意义——用户裁决原文"web 不需要
任何控制通道"。该忽略行为在报告 context.channel_source 里注明。
（web 无显式记录时同样得 mcp——mcp 是 web 正常态，local 才是 static-only
降级语义，二者不可混。）

## A3 — type-aware 检查清单矩阵

| check | windows | linux | android | web |
|---|---|---|---|---|
| init_complete / agent_teams_flag / hooks_deployed / venv_sample / template_version | ● | ● | ● | ● |
| python_version（WARN-only） | ● | ● | ● | ● |
| vm_reachability | 按 channel（A4） | 按 channel（A4） | **不产生行**（#455 NEVER_CHECKS 先例：缺席=不适用，优于伪造 skip 行） | **不产生行** |
| ghidra | 现语义（GHIDRA_HOME 存在性） | 现语义 | 类型化：jadx/baksmali 主判定；`_probe_native_so`（#756 central-directory 版）为真才加要求 decompiler（GHIDRA_HOME ∥ idat64 ∥ MCP ghidra/ida-pro-vm 注册任一） | **不查**（decompiler trials meaningless for web — #728 design D5 原文） |
| mcp_registered | desktop 口径（B2） | desktop 口径 | info 口径（B2） | camoufox 口径（B2） |

## A4 — vm_reachability 按 channel 重写

- `vmr`：现逻辑原样提取（KUNGLAO_VM_HOST 未设 → FAIL；TCP 双端口现语义）。
- `ssh`/`docker`/`adb`：复用 toolchain `_vm_probe_*` 函数而非重写（任务原文）；
  调用前同步 toolchain.VM_SHELL_PORT/FRIDA_PORT 为 env_check resolve_ports 的
  结果（env+​.env 口径，toolchain 只有 import 时 os.environ 口径）。ssh 需要
  KUNGLAO_VM_HOST 作为远端主机名（D4 ssh 语义——这是主机名不是 VM 租约，
  F6 裁决不收窄它）；docker 完全不读 KUNGLAO_VM_HOST。
- `local`：FAIL(degraded) 固定 detail "local static-only channel ... static
  proceeds"。env_check 没有 task_spec needs 面，无法走 D3 的 WARN/HARD 二分，
  取保守 degraded-Fail 行让 loop 自觉降级。
- `mcp`：无命令通道探测。desktop+mcp 时探测面留空（执行层未落地，#698 D5
  声明性）；web 不进此分支（type 先分流）。

## B1 — FAIL 分级机械化（T3）

```python
BLOCKING_CHECKS = ("init_complete", "agent_teams_flag", "hooks_deployed",
                   "venv_sample", "template_version")   # 现语义全保
DEGRADED_CHECKS = ("vm_reachability", "ghidra", "mcp_registered")
```

- 每项报告条目增 `blocking: true|false` 字段（schema 同步）。
- blocking FAIL → overall=FAIL（exit 1，现语义）。
- degraded FAIL → overall 仍 PASS + 顶层 `degraded: [names]` +
  该项 detail 前缀 "T3-restricted: "（机器可读锚点）。
- adjudication：venv_sample/template_version/python_version 不在任务枚举的
  degraded 三件套里；前两者保持现行 HARD-overall 行为（"既有项不动"字面
  遵守 > 反推扩权）。python_version 本就 WARN-only。

`.env-check.json` schema 增量：

```json
{
  "context": {"project_type": "windows|null", "channel": "...",
               "channel_source": "env|.init-report.json|analysis_state.txt|derived"},
  "checks": {"<name>": {"status": "PASS|WARN|FAIL", "detail": "...",
                         "blocking": true}},
  "overall": "PASS|FAIL",
  "degraded": ["vm_reachability"]
}
```

## B2 — mcp_registered 口径（T2）

三面注册扫描复用 mcp_probe.registered_names（user ~/.claude.json 全局+
project-scoped + workspace .mcp.json；KUNGLAO_CLAUDE_JSON 可注入测试）：

- web：期望 {camoufox-reverse}。缺 → FAIL(degraded) + register 命令 fix 文本；
  有 → PASS（detail 注明 registry-only）。
- android：无硬性 MCP 期望 → PASS-with-info（gitnexus 由 toolchain face 验证）。
- windows/linux：ghidra/ida-pro-vm 任一注册 → WARN "capability unverified"
  （#474 同口径：registry read ≠ capability，probe 到不了 MCP session 内部）；
  都没注册 → FAIL(degraded)，fix 列 Ghidra 安装 / idat64 / MCP 注册三选一。

blocking=False 恒成立；"web 缺 camoufox → degraded 不 blocking"（任务原文）。

## B3 — gate 第三检查（hooks/env_check_gate.py）

插在 flag + init 之后、默认放行之前：

```
report = ws/runs/.env-check.json
absent / corrupt / 解析失败            → 放行（gate 不能变成新的死锁源）
ts 缺失或 age > 600s                    → 放行（stale fail-open）
任何 check status==FAIL 且 blocking===true → REJECT(2) 指导修复（重跑 env_check）
其余（含 legacy 报告：无任何显式 blocking 字段）→ 放行
```

adjudication：legacy（pre-#757）报告没有 blocking 字段——若按"缺省即
blocking"解释，VM 不通的旧报告会让 gate 复活成 dispatch 死锁。故 REJECT 仅
认 modern 报告里显式 `blocking:true` 的 FAIL 行。新鲜窗口 600s 与
SKILL Phase 0 "先跑再进场"节奏一致。

## C1 — channel 枚举增 mcp（T5）

- `scripts/toolchain.py::_channel_backend`：`"mcp"` 进合法值集合（不再触发
  unknown-note 回落）。`_check_dynamic_channel`：mcp + dynamic(needs_vm) →
  双 item FAIL/HARD 固定 detail 指路 vmr/ssh/docker/adb，零 subprocess
  （D9 fail-closed；桌面动态的命令平面不存在于 mcp 后端）；static-only 任务
  继续走通用零探测 WARN 行（含 mcp），与 local 分支同构。
- `scripts/init_channel_default.py`：常量体系增 `MCP = "mcp"` +
  `ALL_CHANNELS = REMOTE_CHANNELS + (LOCAL, MCP)`；显式 `KUNGLAO_CHANNEL=mcp`
  视为一等显式选择（同 explicit-local：不探测不告警）。自动探测序不含 mcp
  （init 时无可执行的 MCP liveness 探测——探针面是 env_check/mcp_probe 的域）。
- web 的 channel resolve 归属 env_check 推导层（A2），不动 #728 的 init
  写盘行为及其 test_web_labs_type_728 钉子。

## C2 — 守门全扫结论（KUNGLAO_CHANNEL / vmr.*ssh.*docker）

`grep -rn 'KUNGLAO_CHANNEL\|vmr.*ssh.*docker' tests/ scripts/ tools/
--include='*.py'` 命中面：test_dynamic_channel_698（vmr 枚举钉子，untouched）、
test_init_channel_default_727、test_web_labs_type_728（KUNGLAO_CHANNEL=docker
写盘钉子——A2 明确不改写盘行为）、test_toolchain* 枚举表。本次只扩枚举不
改既有值语义；#698 byte_identical 钉子（unset→vmr 现行为不变）逐字保留。

## C3 — 测试计划（RED first, tests/test_envcheck_modern_757.py）

1. T5：`_channel_backend("mcp")` → ("mcp", None)；unknown 仍回落+note；
   unset→vmr 不变；init_channel_default 显式 mcp 无 warn。
2. T4：记录链四源各命中一次；derive 路径只读（resolve 被调、无写盘断言）。
3. T1：android+VM_HOST 未设 → 无 vm_reachability 键；web → 无 vm/ghidra 键
   且 channel=mcp；desktop+docker → 探测走 docker（monkeypatch tc._run_cmd
   断言 argv 含 docker version、且无 KUNGLAO_VM_HOST unset 文案）。
4. T2：三口径 × 注入 KUNGLAO_CLAUDE_JSON。
5. T3：分级矩阵 + degraded 前缀 + gate 三路径（fresh REJECT / stale 放行 /
   absent 放行 / corrupt 与 legacy-schema 放行补强）。
6. 迁移：test_env_check.py 场景 2（vm unreachable）改为 degraded 语义断言；
   all-pass 用例 stub mcp 检查以隔离 env 漂移。

## C4 — 与 #755 并行的边界

env-manifest / CLAUDE.md / 任何 workspace 写盘归 #755（其
`_item_env_manifest_refresh` 负责持久化）；#757 全程只读推导、唯一写盘是
既有的 runs/.env-check.json 快照路径本身（schema 增字段向后兼容：新键可被
旧 reader 忽略）。
