# Proposal — cross-chapter report-INTERNAL consistency checker (#57)

## Why

a2b5e25c 客户 2026-08-11 反馈**问题 3**：`report_final.docx`（客户看到的 40 页
版本）**同文档内部矛盾全部漏检**，三组矛盾各自跨章节共存：

1. **§3.3 / §3.4 / §4.1 — HandleCommand 路由三说不一致**。§3.3「不经过通用的
   HandleCommand 处理地址」(NEG) vs §3.4 代码清单 3 标题 `HandleCommand.func12`
   (POS) vs §4.1「先经过 func12 函数解析」(POS)。同一符号在三个章节被赋予冲突
   的路由语义。
2. **§5.4 / §6.1.3 — 命名管道 vs 共享内存**。§5.4「编码后的视频流通过命名管道或
   共享内存通道写入预定义回传路径」(命名管道 POS) vs §6.1.3 代码清单 9
   （`wire_WriteMsg` / `webrtcpub_WriteH264` = 共享内存）——命名管道全文零证据。
3. **§1.1 / §2.3 / 摘要 — 注册表持久化既否认又主张**。§1.1「运行全程不依赖系统
   注册表实现持久化」(NEG) vs §2.3 Run 键表 (POS) vs 摘要「通过 Run/Startup 路径
   建立持久化机制」(POS)。

外加**负面发现口径跨章节放大**：F035 负面发现（`OVERLORD_*` 环境变量不落盘 =
**配置存储口径**）被放大为「持久化不依赖注册表」（**持久化机制口径**）——不同
口径，前者不支撑后者。

P4 审校按 `ch_sNN` 逐节切分、**无跨节视角**（实验 H-D 证明：给整段跨节内容
agent 即能发现矛盾——能力存在，流程没给范围）。

#50 已建跨「报告代码清单 ↔ 原始反汇编字节」的 byte-exact 校验（`tools/disasm_constant_check.py`），但那是**报告↔二进制**层；**报告内部跨章节一致性**仍无
机械门禁。hr-report skill 的 `APPENDIX_A_HARDENING.md` 有 `g6_contradiction_check.py`
雏形，但在 a2b5e25c 管线**未启用**，且它只抓 token 重复/局部上下文矛盾，抓不到
跨节路由语义/口径放大。

## What Changes

- **`scripts/report_consistency_check.py`**（新，pure stdlib）：读一份报告文件
  （markdown，`## N.N Title` 章节标记；fenced code block 为代码证据区），运行 3
  类跨章节一致性检查，输出 JSON 报告：
  - **CC1 same-symbol polarity contradiction**（issue check 1 / 回归组 1）：同一
    函数符号跨章节被赋予冲突极性（某章 NEG「不经过/bypass」、另一章 POS「是
    handler/被路由」）。极性由符号近邻的路由否定词触发（`不经过|未经过|绕过
    |bypass|skip`），无否定词则默认 POS。
  - **CC2 negative-finding scope amplification**（issue check 2 / 口径放大）：
    一个**窄口径**负面（配置存储：`环境变量|env|配置|不落盘`）与一个**宽口径**
    负面（持久化机制：`持久化|注册表|Run 键|Startup|不依赖`）跨章节共存，且宽口
    径负面章未带同口径独立证据 → 标记潜在口径放大（warning，供人工裁定）。
  - **CC3 conflicting-conclusion divergence**（issue check 3 / 回归组 2+3）：
    同一机制/主题跨章节极性冲突（注册表 NEG vs POS —— 组 3）**或**互斥机制对双
    POS（命名管道 vs 共享内存 —— 组 2）。
  - **CONFLICT 标记逃生口**：报告作者可用 `<!-- CONFLICT: ... -->` 或 `CONFLICT`
    字样显式承认一组张力；命中的矛盾记为 `acknowledged: true`（单独计数，不计入
    `inconsistency_count`），呼应 issue「相互矛盾的结论必须收敛或显式标注」。
- **模块 docstring 承载调用契约**（不另起 references doc，避免与既有
  failure-modes-* 冲突）：cross-reference #50（报告↔二进制）与全局规则
  `~/.claude/rules/common/numeric-fidelity.md`（口径保真），并写明 hr-report 管线
  后续接入本工具的 3 步契约（BLOCK CC1/CC3、WARN CC2）。hr-report skill 强制接入
  是跨仓库 follow-up，不在本 PR。
- **`tests/test_report_consistency_check.py`**（新，RED first）：(a) 回归 fixture
  含 3 组矛盾 → 全部检出；(b) 口径放大检出；(c) 干净一致报告 → 0 矛盾；(d) CLI
  exit 0/1/2；(e) CONFLICT 标记 → acknowledged；(f) 模块 docstring 交叉引用 #50
  与 numeric-fidelity。

## Non-goals

- **不改 hr-report skill**（跨仓库 scope；本 PR 只交付 kunglao-agent 工具 + 调用
  契约文档；把工具强制接入报告管线是 follow-up）。
- **不读二进制 / 不调 LLM / 不联网**——纯 stdlib 文本检查。报告↔二进制 byte-exact
  是 #50 的职责（互补，不重叠）。
- **不做语义仲裁**——CC2 标"潜在"口径放大而非断言错误（机械检查无法判定口径
  意图，只暴露跨章节口径漂移供人工裁定）。recall/precision 取舍见 design.md (D5)。

## Capabilities

### Added Capabilities

- `report-consistency-check`: 报告**内部**跨章节一致性机械检查。3 类检查
  （CC1 符号极性 / CC2 负面发现口径放大 / CC3 冲突结论分歧），markdown 章节切分，
  JSON 报告 + CLI exit 0/1/2。互补于 #50（报告↔二进制 byte-exact）。

## Impact

- `scripts/report_consistency_check.py`：新，~340 行（章节切分 + 极性引擎 + 3 检
  查 + CLI）。
- `tests/test_report_consistency_check.py`：新，~280 行（~14 测试）。
- 调用契约与 cross-reference 写进模块 docstring（不新增 references 文件，避免与
  既有 failure-modes-* 维护冲突）。
- Suite impact（baseline at `fd53d93`）：`scripts/` 226 passed → 226 不变（检查器
  是 scripts/ 模块，由 tests/ 测试覆盖，scripts/ 自身无新 test_ 脚本）；`tests/`
  350 passed + 1 skipped + 6 pre-existing failures → +N new passes，6 个
  pre-existing failures 不变。
- Related: #50（`tools/disasm_constant_check.py` 报告↔二进制 byte-exact — 交叉
  引用，不重叠）、全局规则 `numeric-fidelity.md`（口径保真，CC2 的规则源头）。
