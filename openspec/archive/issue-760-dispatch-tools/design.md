# Design: issue #760 dispatch 工具面

## D1 — 用户裁决（2026-08-27，原文口径）

1. **无头优先（2026-08-27）**：web 动态默认 headless；反无头指纹信号出现时先指纹
   仿真，headfull 只是风控升级的最后手段。
2. **调试插桩一等能力（2026-08-27）**：调试插桩（XHR wrap / CDP WS 帧 / eval 断点
   栈回溯）是平级方法，不是静态走不通的 fallback。

## D2 — I1 校验挂载点与 agent 身份来源

**身份来源优先级**：`tool_input.subagent_type` → `tool_input.name` → v1 JSON
`meta.agent`。worker_budget_sinks.py:424 已经用 `tool_input.name` 读 agent 名
（既有惯例），dispatch_gate 沿用同一组字段。

**为什么不拦 v0 裸文本**：v0 regex（`[T1 tools=grep] claim C-3`）从不携带 agent
身份——payload 里没有 subagent_type 的历史派发面全部不拦（`未知 agent 走既有路径
不拦`）。这保证了既有套件（test_decision_teeth / test_dispatch_protocol 等，
payload 不带 agent 名）零漂移，同时真实编排器经 Claude Code Agent tool 派发一定带
subagent_type——机械校验恰好在真实攻击面上通电。

**挂载点**：与 #567 mcp_prefix gate 同一条"结构性违规不休眠"走廊（activation
检查之前）。allowedTools 是 skill 自带的 agents/*.md 静态契约，与 workspace 状态
无关；一个越界工具架不该等 activation 才被拒绝。

**frontmatter 解析 helper**：dispatch_gate 本地实现（正则取 `---...---` +
yaml.safe_load 取 allowedTools）。不 import scripts/route_capability._parse_frontmatter
——hooks 不依赖 scripts 私有 API（#671 边界；route_capability 同形 twin 已是先例）。

**匹配语义**：
- pattern 无 `*`：工具名大小写不敏感全等（Read/read 视为同族——历史派发惯用小写）；
- pattern 以 `*` 结尾：startswith 前缀匹配（mcp__ghidra__* 家族）；
- 未声明任何 tools=（空列表）：不拦——agent 保持完整 frontmatter 工具架，§1c 可满足；
- 文件契约项：Write/Edit 至少其一（大小写不敏感全等，字面口径——§1c 是文件写入契约，
  Bash 间接写不算）。

REJECT 走 `_reject_with_guidance`（stderr REJECT + additionalContext fix + rc2），
消息含 "not in <agent> allowedTools" / "missing write-capable tool (§1c)"。

## D3 — I2 TRY 边界的定位

梯子是行为升级协议，不是能力替换协议。TRY 的前提是"目标能力可能存在、只是我还不会
用"；能力结构性缺席（有反编译器但没有文件系统）属于 ESCALATE。凑合产物不可信：
进程内执行环境里写出的"文件"没有 workspace 字节锚，verifier 无法独立复算——这正是
W-15 教训的镜像形态。

## D4 — macos 最小面（labs 形状）

三层 VALID_TYPES 拷贝（init_state / toolchain / mcp_probe——#728 先例是"deliberate
layer copy"注释）同时增 macos。macos 完全照 #728 web 的 labs 口径：

- toolchain `_check_macos`：零 HARD。otool/class-dump/swift-demangle presence 探测
  （WARN）；Darwin 动态环境检测（非 darwin host → WARN 提示动态面不可用而非阻断）；
  `_check_mcp(report, ws, "macos")`（manifest 对 macos 零条目 → 空 checks PASS）。
- CHECK_SETS["macos"] 声明实际发射项；NEVER_CHECKS["macos"] pin
  vm_reachable/remote_debugger 缺席（VM 通道是 windows/linux 契约，#455 先例）。
- OS_SECTIONS["macos"] Hard constraints 最小集（Mach-O 分析需 class-dump/otool 系；
  动态需 Darwin 环境）。
- env_check：check_ghidra_typed 把 macos 并入 windows/linux 分支（Mach-O 反编译期望
  与 ELF 同型；FAIL 也是 DEGRADED 非 blocking），其余 else 分支自然回落。
- guidance 字符串守门同步：kunglao-init/init_state/kunglao_resume/env_check_gate/
  mcp_probe docstring/SKILL.md/skills/*.yaml/README 的 type 枚举串统一
  `windows|linux|android|web|macos`；test_web_labs_type_728.py 四处源码 pin +
  SKILL.md pin 同步更新（pin 测的是"字符串存在"，两侧同 PR 内一致更新即守门语义
  不变）。

## D5 — web-re-worker 结构

镜像 ghidra-light：frontmatter（name/description/triggers/allowedTools/
disallowedTools/isolation: none）+ 三段 contract marker（Gate 6 lint 要求）。
pipeline_order 5（go-symbols 1 / pefile-signature 2 / floss-filter 3 /
ghidra-light 4 之后，verdict-scorer 9 之前）。

触发词冲突在 trigger 表设计内双向裁决：`'签名'` 子串会同时命中浏览器域的"签名参数"
claim（web 域的核心工作面，quickref 第二节）——单向靠 pipeline_order 让 PE 特化通吃
会把所有 web 签名 claim 错派给 Authenticode 专家。裁决：**web-re-worker
（order 5）持有完整 web 触发族；pefile-signature（order 2）exclude 列表补
webhook/deobfuscate/bundler/前端/网页/风控/爬虫 七个浏览器域 token**——纯 PE 签名
claim 不含这些 token，行为不变；混合措辞让给 web-re-worker。两向 precedence 都有
路由测试 pin 死。js:* tag 引用标注 "registry 见 #751"。

allowedTools 按任务书列全（Read/Write/Edit/Glob/Grep/Bash + WebFetch/WebSearch +
mcp__camoufox-reverse__* + mcp__gitnexus__* + sequential-thinking）。js:* tag 引用
标注 "registry 见 #751"——tag 未合不影响本文件合法性。

## D6 — registration 与守门

release-manifest.yaml assets.agents 增一行（#691 先例：undeclared asset 红 CI）
+ tests/test_release_receipt.py MANIFEST_AGENTS roster 同步（declared == roster 全等断言）。
tools/_INDEX.yaml 不动。test_agents_lint 的 real-repo 断言是子集式（expected <= names），
新文件自动被 Gate 6 lint 覆盖，不改该测试。
