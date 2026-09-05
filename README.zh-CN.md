# kunglao-agent

**kunglao-agent 是一套自主逆向工程系统：你给它目标和待解问题，它自己把问题做上几小时到几天 —— 自己规划路径，worker 死了能补位，崩溃了能续跑；只有当每个答案都从原始证据推导出来、并扛过机械校验门控之后，它才收敛交卷。**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](.) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](.) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](.)

**简体中文** · [English](README.md)

它目前以 Claude Code 插件的形式分发 —— Claude Code 是你对话的界面，但不是产品的本体。产品是这套循环：专家 worker 先做静态分析，独立验证者从原始证据盲重推每一条事实，机械门控决定分析何时算完成。交付物是一个事实库：每条 claim 都有字节锚定、独立验证、证据索引 —— 信任靠机器执行，不靠口头约定。

> **术语约定**：`kunglao-agent`、`PROVEN`、`RED-CHECKER`（独立验证者）、`fact`、`claim`、`MCP`、`task_spec.yaml`、`claim-register.yaml`、`evidence/_index.json` 等已建立术语保留英文原文，其余均为中文。

## 为什么是 kunglao-agent

- **长时程是设计目标。** 一次分析可以无人值守跑上几小时到几天：定时心跳让循环一直活着，死掉的 worker 会被补位、其问题重新排队，崩溃后从落盘状态续跑，卡住的任务能自愈。收敛了你再来读结论 —— 不用一步步盯着。见[长时程自主运行](#长时程自主运行)。
- **答案值得信。** 任何 fact 在独立验证者从原始证据盲重推一致之前都不能叫 `PROVEN`；每条 fact 都通过 `evidence/_index.json` 锚定到带 sha256 的原始证据。
- **覆盖完整的逆向光谱。** Windows/Linux 原生二进制、Android APK、Web/JS、协议分析、固件仿真、风控对抗 —— 一套系统，不是单领域工具。
- **静态优先的成本观。** 能静态闭环的任务绝不碰动态工具；每一次升级都要显式声明、受门控约束、留下审计。
- **复用知识，而不是重复推导。** 内置持续扩充的注册工具目录（crypto 解码、反汇编流水线、图查询），系统优先调用成熟工具而不是临时手搓脚本；每次运行沉淀下来的是可复用的事实库，而不是一段会蒸发掉的聊天记录。
- **会恢复，而不是死掉。** worker 死亡、API 断连、进程崩溃都是一等公民事件：循环检测到它们、快照已完成的产物、从断点续派，而不是从零重来。
- **你的环境你做主。** VMware、ssh、docker、adb、或者纯静态 —— 系统驱动你已有的执行通道，没有哪种是"降级模式"；不需要执行的任务绝不会向你要一台虚拟机。

## 快速开始

kunglao-agent 跑在 Claude Code 里。从磁盘上的样本到 verdict：

| 工具 | 作用 | 安装 |
|---|---|---|
| **Claude Code** | kunglao-agent 的运行环境 | 按 Anthropic 官方文档 |
| **Python 3.10+** | 插件自带 `uv` 管理的锁定环境，你不用动 | 系统装或 `uv` 管 |
| **`uv`** | 锁定环境解析器 | `pip install uv` 或 [astral.sh/uv](https://astral.sh/uv) |
| **Ghidra 或 IDA** | 二选一，作为反编译器 | 见[按目标类型分工具链](#按目标类型分工具链) |

### 1. 装插件

在任意目录下，进入 Claude Code：

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

（开发模式也可以：`claude --plugin-dir /path/to/kunglao-agent`。）

### 2. 初始化工作区

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` 搭好工作区、写好 `CLAUDE.md`、按你选的 `--type` 探测工具链、生成 `.mcp.json`。你选的类型有 HARD 工具缺失时，init 会 **HARD-reject** —— 修复指引就写在错误块里。

### 3. 提出任务

```
/kunglao-agent
> 主问题：(1) imports 对应哪些能力类别，
> (2) 它怎么持久化，(3) 回连哪些主机？
> 成功标准：每个答案都落成带复现命令的 PROVEN fact。
> 约束：只做静态 —— 本周没有 VM。
```

把需求写成第三方能据此评判结果的程度：**分析目标**（你要知道什么）、**验证逻辑**（凭什么信答案——比如"同一输入必须能重推出同样签名"）、**约束**（比如"宿主机上不许执行"）。全部记入 `task_spec.yaml`，之后循环自己推进。

### 4. 看交付物

```
claim-register.yaml   # 每条 claim 都 terminal，带验证者签核
facts/F<NNN>.md       # 字节锚定、可复现、frontmatter 契约
evidence/_index.json  # 每个 fact 对应一份原始证据（sha256 + 路径）
runs/                 # 会话审计轨迹
```

## 子命令

| 命令 | 什么时候用 | 做什么 |
|---|---|---|
| `/kunglao-agent:init <路径> --type <windows\|linux\|android\|web\|macos>` | 开始一次分析 | 搭建工作区，按类型探测工具链，写 `CLAUDE.md` 和 `.mcp.json`；HARD 工具缺失时 HARD-reject，错误块里带修复指引 |
| `/kunglao-agent` | 每次干活 | 跑收敛循环：一次性 intake → 派工 / 验证往复 → 收敛出报告 |
| `/kunglao-agent:resume <路径>` | 崩溃、重启之后，或任何"我刚才跑到哪了" | 只读的断点简报（健康状态、open claim、在跑 worker、崩溃时间线）加上状态机给出的下一步 |
| `/kunglao-agent:upgrade <路径>` | 工作区版本戳落后于插件版本 | 把脚手架迁移到当前版；用户数据（claims、facts、evidence）绝不触碰 |
| `/kunglao-agent:help` | 其他情况 | 路由到各子命令文档 |

## 一次分析长什么样

*一次分析的"形状" —— 你敲什么、拿到什么、去哪看。* 一个小型 Windows dropper 落在 `~/cases/synth-dropper`：

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # 探测 Ghidra、VM 可达性
/kunglao-agent
> "这个二进制干了什么，回连到哪里？"
```

接下来循环自己跑 —— 路线随样本实际情况调整，不是固定剧本。你可以走开（见[长时程自主运行](#长时程自主运行)）。收敛之后读下面的交付物。

## 场景演练

再给两条端到端的路径 —— 挑一条匹配你的目标（普通 Windows PE / Linux ELF 二进制就走上面的示范案例）。

<details>
<summary><strong>Android APK —— 用户敲什么、产物落到哪</strong></summary>

```bash
/kunglao-agent:init ~/cases/sample.apk --type android
/kunglao-agent
> "capability / persistence / network entry points"
```

```bash
/kunglao-agent:init ~/cases/sample.apk --type android
/kunglao-agent
> "这个 APK 有没有动态加载和反调试？如果有，代码藏在哪，做了什么？"
```

- **产物落在哪：** `bins/<sha256>`（APK 本身）、`facts/`（类图谱、native `.so` 清单）、`evidence/`（抓包、dump）。
- **"完成"长什么样：** 每个问题都有可复现的证据支撑。
- **路线由系统定。** 有的 APK 纯静态 DEX 分析就能闭环，有的必须上真机调试 —— 取决于样本实际是什么。

</details>

<details>
<summary><strong>Web / JS —— 解包 → 去混淆 → 带签参数重放</strong></summary>

```bash
/kunglao-agent:init ~/cases/example-site.com --type web
/kunglao-agent
> "XHR 签名是怎么算的，nonce 从哪来？"
```

- **产物落在哪：** `evidence/`（抓包、去混淆后的代码）、`facts/`（签名密钥、nonce 推导）。
- **注意：** `web` 是 beta 阶段目标 —— 工具链门槛刻意放得很低；能力缺失由循环在实际需要时浮出来，而不是 init 卡住。

</details>

## 你得到什么

一个声明登记加事实库，信任靠机器执行，不靠口头约定：

- **验证式收敛** —— `PROVEN` 要求独立盲验证者逐字节重推一致；`CONVERGED` 要求每个主问题都有字节级证据、零孤立 claim、不空转。
- **证据完整性** —— 每条 fact 都能通过 `evidence/_index.json` 追到原始证据（capture / trace / dump / 二进制）。按设计排除派生摘要。
- **Maker-checker** —— worker（maker）写事实，redteam 验证者（checker）盲重推。永远是不同的 agent。

没有任何 claim 能靠作者自己说了算：必须由独立验证者盲重推一致，并通过一组机械门控。完整门控设计见 [`docs/design/loop-engineering.md`](docs/design/loop-engineering.md)。

跑完之后，各文件回答不同的问题：

| 问题 | 去哪看 |
|---|---|
| 做完了吗 | 循环的退出码 —— `CONVERGED`（0）表示每个主问题都有已验证的答案；逐条 claim 状态在 `claim-register.yaml` |
| 找到了什么 | `facts/F<NNN>.md` —— 一条 fact 一个文件，由 `claim-register.yaml` 映射回 claim |
| 怎么复现 | `evidence/_index.json` —— fact → 原始证据（路径 + sha256）；每条 fact 带 `reproduce:` 命令 |
| 具体发生了什么 | `runs/` —— 逐 tick 的 ledger 和 worker 状态 |

fact 样例：

```yaml
id: F061
status: VERIFIED-BY-W01-static-byte-recheck
claim_id: C-401
provenance:
  - {role: sample, path: bins/<sha>}
  - {role: capture_log, path: runs/c329-inner-pe.bin}   # 经 evidence/_index.json 引用
reproduce: python -c "import struct; ..."               # 对着引用的证据跑
verifier_sign_off: {verifier: kunglao-redteam, verdict: CONFIRMED}
```

## 长时程自主运行

真实的分析不是二十分钟的聊天。kunglao-agent 能一直钉在问题上，不需要人一步步带着走：

- **一跑几小时到几天，无人值守** —— 定时心跳让循环在你的两次到访之间持续干活；循环停摆会被标记出来，而不是无声烂掉。
- **失败能自愈** —— 死掉或卡住的 worker 会被补位，其问题重新排队；被阻塞的任务走自愈流程，不会干等。
- **崩溃和重启之后能续** —— `/kunglao-agent:resume <工作区>` 从落盘状态重建断点现场，并给出下一步动作。
- **记忆在磁盘上，不在聊天里** —— claims、facts、证据索引、完整审计轨迹都落在工作区，任何会话都能把分析接回去。

你给它目标和问题；它把问题做上几小时到几天，从故障里恢复，收敛了你来读结论。

## 用好它

- **喂静态可解的目标。** 循环是静态优先的：已解包的 APK、未混淆的 bundle、未剥符号的二进制收敛得快得多；逼它走动态就慢。
- **提前把动态那条腿搭好。** 如果主问题注定要执行样本，先选好 channel（见[自带分析环境](#自带分析环境)）—— 动态任务配 `local` 会被 init HARD-reject。
- **分清"在干活"和"卡住了"** —— `runs/` 里有新条目说明循环活着；心跳死了、或同一决策反复出现而没有新 fact，就是卡了 —— `/kunglao-agent:resume <工作区>` 给出诊断和下一步。

## 按目标类型分工具链

init 时选的 `--type` 决定哪些 HARD 工具必须装。指引默认折叠 —— 展开你的目标。**所有类型都需要两个 MCP server：** `ghidra`（`claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe`）和 `sequential-thinking`（`claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking`）。

<details>
<summary><strong>windows（PE32+ x86-64）</strong> —— Windows 原生二进制</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `pefile`（Python） | `pip install pefile` |
| HARD | `die`（Detect It Easy） | `KUNGLAO_DIE` 环境变量或在 PATH —— [ntinfo.com](https://ntinfo.com) |
| HARD | `floss`（FLARE FLOSS） | 按 [flare-floss 文档](https://github.com/mandiant/flare-floss) 装 |
| HARD | Ghidra 或 IDA | 二选一；见[内部](#内部) |
| HARD（T2/T3） | VMware + vmr-shell，或 ssh/docker channel | 见[自带分析环境](#自带分析环境) |
| HARD（T2/T3） | `frida-server`（改名，自定义端口） | 设备/VM 侧二进制，默认端口 1337 |

Windows 的 T3 动态还要用 `x64dbg` MCP；`volatility`（内存取证）和 IDA-Pro MCP 可选 —— 见[内部](#内部)的 MCP 清单。

</details>

<details>
<summary><strong>linux（ELF）</strong> —— Linux 原生二进制 / 固件 / 内存镜像</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `file`、`readelf`、`objdump` | `binutils` 包 |
| HARD | Ghidra 或 IDA | 二选一 |
| HARD（T2/T3） | VMware + vmr-shell，或 ssh/docker 控制平面 | 见[自带分析环境](#自带分析环境) |
| HARD（T2/T3） | `frida-server`（改名，自定义端口） | 设备端二进制，端口 1337 |
| WARN | `gdbserver`（主机侧 PATH）、`strace`、`ltrace` | 可选补充 |

`ssh-mcp` 给远程 / 云 / docker 主机开 ssh 控制平面。

</details>

<details>
<summary><strong>android（APK / DEX / native .so）</strong> —— 难度最高、HARD 项最多</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| HARD | `aapt` 或 `aapt2`（或 `unzip` 兜底） | Android SDK build-tools |
| HARD | `jadx`（DEX → Java 反编译器） | [skylot/jadx](https://github.com/skylot/jadx) |
| HARD | `apktool`（APK 资源解码 / 重打包） | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| HARD | `gitnexus`（反编译后图谱） | `npm i -g gitnexus` |
| HARD | Ghidra 或 IDA | 仅当 APK 含 native `.so` |
| HARD | `adb` + **已 root 设备**，`ro.debuggable=1` | platform-tools + 设备端自定义 frida |
| HARD | `frida-server`（改名，自定义端口 1337） | 设备端二进制 |
| HARD | `android_server`（IDA 远程调试） | 设备端二进制，端口 23946 |
| WARN | `apkid` | `pip install apkid` |
| WARN | `baksmali` | 从 [smali releases](https://github.com/baksmali/smali/releases) 下载 |

</details>

<details>
<summary><strong>web &amp; macos（beta）</strong> —— 最小工具链，按设计没有 HARD</summary>

| Tier | 工具 | 安装 |
|---|---|---|
| WARN | `camoufox-reverse` MCP（web） | 反检测 Firefox（hook / trace / 网络抓包） |
| WARN | `docker`（web channel 默认） | Docker Desktop，或显式 `KUNGLAO_CHANNEL=ssh` |
| WARN | `lipo`、`otool`、`nm`、`codesign`、`xattr`（macOS） | Xcode Command Line Tools |
| WARN | `ghidra` MCP（macOS） | 推荐 —— 见[内部](#内部)的清单 |

两者都是 beta 阶段目标：能力缺失由循环在实际需要时浮出来，而不是 init 卡住。macOS 的动态分析走 `ssh` channel（连到 Mac 主机）；要用可选的 x64dbg 浏览器侧调试，就按上面的 Windows 工具链装。

</details>

以上所有内容的统一真源 —— 随时可探测：`python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>`（退出码 1 = HARD 缺失）。

## 自带分析环境

动态调试需要一个 agent 能驱动的执行控制平面。`KUNGLAO_CHANNEL` 在五个一等公民 channel 里选一个 —— 你环境里已有什么就用什么，没有降级模式：

| Channel | 驱动什么 | 前置 |
|---|---|---|
| `vmr`（默认） | VMware 驱动的 VM，**任何客户机系统** —— snapshot/revert 工作流是它不可替代的价值 | vmr-shell 技能；`KUNGLAO_VM_HOST` + 端口 9876/1337 |
| `ssh` | 任何 ssh 可达的机器：远程裸机、云 VM、Mac、远程 docker 主机 | 密钥认证 —— 探测会真的跑一次 BatchMode `ssh ... true` |
| `docker` | 本机或远程 docker daemon —— `docker exec` 等价于任何控制路径 | `docker version` 绿；可选 `KUNGLAO_DOCKER_CONTAINER` |
| `adb` | 安卓模拟器或真机 | `adb devices` 能看到设备；`adb forward tcp:1337 tcp:1337` 给 frida |
| `local` | **仅主机侧静态分析** | 无 —— 见下面的红线 |

> **`local` 红线：** local 只为**静态**工作准备 —— 绝不在主机上执行、调试、注入样本。任何动态需求都把 `KUNGLAO_CHANNEL` 切到 `vmr`/`ssh`/`docker`/`adb`；动态任务配 `local` 会被 init HARD-reject。

channel 探测只对动态任务跑（纯静态任务直接跳过）。`ssh` channel 上的执行流过 **ssh-mcp** 控制平面（`npm i -g ssh-mcp`）；裸 CLI ssh 是兜底。远程 docker 走 ssh 时，设 `KUNGLAO_DOCKER_CONTAINER`。

## 配置

四个变量覆盖大多数场景：

| 变量 | 默认 | 含义 |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | 未设 | 必须保持未设或 `0` —— 真值会让派工走 teammate channel，会被拒绝 |
| `KUNGLAO_CHANNEL` | `vmr` | 动态分析执行控制平面：`vmr` \| `ssh` \| `docker` \| `adb` \| `local` —— 见[自带分析环境](#自带分析环境) |
| `KUNGLAO_VM_HOST` | 未设 | 动态分析的 VM/主机（vmr-shell :9876，Frida :1337） |
| `GHIDRA_HOME` | 未设 | Ghidra 安装根目录（要含 `support/analyzeHeadless.bat`） |

很少用到：`KUNGLAO_DOCKER_CONTAINER`（`ssh`/`docker` channel 的 docker 执行目标）、`KUNGLAO_FRIDA_PORT`（默认 1337）、`KUNGLAO_DIE`（DIE 路径，兜底 PATH）、`KUNGLAO_CLAUDE_JSON`（用户级 MCP 注册表的测试覆盖）。

## 安全

- 样本绝不在主机上执行 —— `block_malware_exec` hook 强制；动态只跑在 VM/容器/设备里，且要求逐会话授权。
- 真相等级：原始证据 > 本地工具 > 沙箱 > 威胁情报（CTI 是可证伪的假设，不是真相）。
- Maker-checker：worker 永不自我验证；验证者永不读 maker 的结论。
- bins、settings、hooks 永不入库；密钥与工作区、仓库隔离。

## 开发

欢迎贡献。流程：从 `dev` 切分支，一个改动一个分支，PR 回 `dev`。

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q
gh pr create --base dev
```

设计文档在 `docs/` 与 `specs/`。见[许可证](#许可证)。

## 内部

<details>
<summary><strong>MCP 供应（完整清单）</strong></summary>

单一真源：`scripts/mcp_probe.py`；`kunglao-init` 在缺失时生成工作区 `.mcp.json`（`--no-mcp` 跳过；已有文件绝不覆盖）。探测：`python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>` —— 退出码 1 = HARD 缺失，2 = 仅 WARN 缺失。

| MCP server | Tier | Scope | 用途 | 注册 |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | 所有 type 必需 | 反编译 / 静态分析 | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | 所有 type 必需 | 结构化推理 | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 动态 | 动态调试（VM 远程） | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | 内存取证 | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | 选 IDA 时 | 远程 IDA 分析 | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android 图谱构建 | 反编译后知识图谱 | `claude mcp add gitnexus -- gitnexus mcp` |
| `virustotal` | WARN | CTI | 威胁情报（家族归属假设） | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `ssh-mcp` | WARN | channel | ssh 执行控制平面 | `claude mcp add ssh-mcp -- ssh-mcp` |
| `camoufox-reverse` | WARN | web（beta） | 浏览器 JS 逆向（hook / trace / 网络抓包） | `claude mcp add camoufox-reverse -- python -m camoufox_reverse_mcp` |

</details>

<details>
<summary><strong>工作区布局</strong></summary>

一个工作区对应一次样本分析：

```
<workspace>/
├── bins/<sha256>              # 样本（gitignore）
├── task_spec.yaml             # primary_questions / scope / constraints / success_criteria
├── claim-register.yaml        # claim C-NN（OPEN/PROVEN/STAMP/...）
├── claim_deps.yaml            # claim DAG
├── facts/                     # 字节锚定 fact F-NNN.md + _INDEX.md
├── evidence/                  # 原始证据 + _index.json（eid → 路径 + sha256）
├── runs/                      # worker-status、plan、ledger、.heartbeat.json
├── blockers/                  # 每个 claim 的失败归因记录
└── CLAUDE.md                  # 工作区规则，kunglao-init 生成
```

kunglao hook 只落在工作区层级；你的全局 `~/.claude/settings.json` 永远不会被写入。

</details>

---

## 许可证

双协议许可：**AGPL-3.0** 用于个人、学术、内部使用（免费 —— 见 [LICENSE](LICENSE)）；闭源或 SaaS 商业使用需要**商业许可** —— 见 [LICENSE-commercial.md](LICENSE-commercial.md)。
