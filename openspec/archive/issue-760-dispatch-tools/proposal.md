# Proposal: dispatch 工具面 — tools= 校验 / TRY 边界 / macos 类型 / web-re-worker (#760)

## Why

现场根因（mm_x86.dylib）：worker 被 dispatch 的 `tools=` 前缀收窄到只剩
ida-pro-mcp——自由文本、零校验。worker 的 frontmatter allowedTools 白名单里根本没有
ida-pro-mcp，更没有 Bash/Write：无文件系统工具就无法履约 §1c 文件契约
（worker-status / facts/Fxxx.md）。LEARN→TRY→ESCALATE 梯子又被误用：
"能力不存在"被当成"需要探索"，worker 用 IDA 进程内 Python（py_eval）当 shell 凑合，
产物不可信也不可审计。叠加问题：init 类型矩阵没有 macos（Mach-O 样本无处落型）、
web RE 领域没有专职 specialist worker。

## What Changes

- **I1（T1）**: `hooks/dispatch_gate.py` 增机械校验——dispatch 声明的 `tools=` 列表
  必须可解析进目标 agent frontmatter allowedTools（通配符语义），且必含文件契约工具
  （Write/Edit 至少其一，§1c 机械面）。违规 REJECT（rc=2 + stderr +
  additionalContext fix guidance）。agent 身份来自 Agent tool payload
  （subagent_type/name）或 v1 JSON meta.agent；解析不出 agent 名或未知 agent →
  走既有路径不拦（向后兼容既有 v0 自由文本派发面）。
- **I2（T2）**: `agents/kunglao-worker.md` 梯子段增边界条款——TRY 只适用于能力可能
  存在但需探索的场景；能力不匹配直接 ESCALATE 写 blocker；把 IDA py_eval 当 shell /
  把 decompiler 当文件读写器是禁止项。`references/operational-mechanics.md` 三级梯同款。
- **I3（T3）**: `VALID_TYPES` 增 "macos"；toolchain 增 `_check_macos`
  （Mach-O 最小面：otool/class-dump/swift-demangle presence 探测 + Darwin 动态环境
  提示，全 WARN——labs 语义，与 #728 web 同形状）；kunglao-init OS_SECTIONS["macos"]
  Hard constraints 模板；ghidra-light triggers.features 补 macho/dylib 信号；
  全仓 type-union 守门扫描同步（guidance 字符串 + 测试 pin 同步更新）。
- **I4（T4）**: 新 agent `agents/web-re-worker.md`——镜像 ghidra-light 结构
  （frontmatter + trigger 表 + allowedTools），领域契约为 web-re-quickref 五节方法论
  内化：解包→去混淆→索引→签名追踪→验证 loop；frontmatter allowedTools 列
  mcp__camoufox-reverse__* + mcp__gitnexus__*；release-manifest.yaml declare。

## 用户裁决（2026-08-27）

1. **无头优先**：web 动态分析默认 headless；headfull 仅作风控升级的最后手段。
2. **调试插桩是一等能力**：调试插桩不是 fallback，是与静态分析平级的一等方法。

## 与并行波分工

- #751（并行波）：registry/quickref/路由层（js:semantic-query/js:call-graph tag）
  —— 本波 web-re-worker 的 allowedTools 列 mcp__gitnexus__*，领域契约引用 tag 时
  标注"registry 见 #751"，tag 未合不影响 agent 文件合法性（validate_index 管
  tools/_INDEX.yaml，不管 agents/）。
- tools/_INDEX.yaml 本波不动（#751 领地）；不改真实 workspace。

## Out of scope

K2 沉淀契约消费侧（#762 已建 notes/<claim-id>.md 机制，web-re-worker 直接引用）；
macos 的 VM 通道语义（#698 channel matrix 领地）；js:* registry 落库（#751）。
