# Spec: dispatch-tools (#760)

## ADDED Requirements

### Requirement: dispatch tools= 声明受目标 agent allowedTools 机械约束

dispatch（经 Agent tool 派发、payload 携带 subagent_type/name，或 v1 JSON meta.agent
声明 agent）声明的 `tools=` 列表中每一项必须可解析进该 agent frontmatter allowedTools
（通配符前缀语义，大小写不敏感）。违规项 REJECT（rc=2），消息含
`tool <X> not in <agent> allowedTools`。

#### Scenario: 越界工具被拒

- WHEN payload.subagent_type=kunglao-worker 且 prompt 带 `[T1 tools=pefile-signature]`
- THEN gate rc=2 且 stderr 含 `not in kunglao-worker allowedTools`

### Requirement: 文件契约工具机械在场

`tools=` 列表非空时必含 Write/Edit 至少其一（§1c 文件契约的机械面）；
缺失 REJECT，消息含 `missing write-capable tool (§1c)`。空列表不拦
（完整 frontmatter 工具架在场）。

#### Scenario: 只读工具架被拒

- WHEN tools=Read,Grep（无 Write/Edit）
- THEN rc=2 且消息含 `missing write-capable tool`

#### Scenario: 合法工具架放行

- WHEN tools=Read,Write,Grep 且全部 ∈ allowedTools
- THEN rc=0

### Requirement: 未知/未声明 agent 不拦

解析不出 agent 名或 agents/<name>.md 不存在 → 该校验跳过，走既有路径。

## ADDED Requirements

### Requirement: TRY 梯子边界条款

worker 梯子契约与 operational-mechanics 三级梯都声明：能力不匹配（需要文件系统但只有
反编译器进程内执行等）→ 直接 ESCALATE 写 blocker；用邻近能力凑合（IDA py_eval 当
shell、decompiler 当文件读写器）是禁止项。

## ADDED Requirements

### Requirement: macos 项目类型

VALID_TYPES 三层（init_state/toolchain/mcp_probe）含 "macos"；toolchain._check_macos
零 HARD（otool/class-dump/swift-demangle WARN + Darwin 动态提示）；OS_SECTIONS["macos"]
渲染 Hard constraints；guidance 枚举串全仓同步 `windows|linux|android|web|macos`。

### Requirement: Mach-O 样本路由 ghidra-light

ghidra-light triggers.features 增加 macho/dylib 信号；Mach-O feature dict 经
route_capability 推荐命中 ghidra-light。

## ADDED Requirements

### Requirement: web-re-worker specialist

agents/web-re-worker.md 存在且结构合法（frontmatter name/triggers/allowedTools +
三段 contract marker 过 Gate 6 lint）；触发表 pipeline_order 5；release-manifest.yaml
declare 且 roster 断言同步；js/webhook/风控/bundler/deobfuscate claim 路由命中，
authenticode claim 仍归 pefile-signature，apk/dex/smali 被 exclude。
