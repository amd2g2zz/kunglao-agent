## Why

a2b5e25c 客户 2026-08-11 反馈**问题 1**：报告代码清单 10 赋值错（`frameRateNum=bitrate` 等）一路通过 fact 层（F015）和报告层，到客户才被发现。逐层有 byte-exact / 审校，但**没有跨「fact → 报告代码清单」或「fact claim → 原始反汇编字节」的机械校验**。

根因链：

- `kunglao_verify.py` 的 L1 比 fact **内** expected vs actual（fact 内闭环）——不跨 fact→report。
- 报告层审校全人工/LLM（`g6_contradiction_check.py` 只抓 token 重复/上下文矛盾，抓不到赋值语义错）。
- 即使 #49 让 fact expected 列了值断言，报告代码清单是 fact 的**二次转述**，复制/翻译时仍可能错位/typo（a2b5e25c：fixture 摘录层 `bitrate*1000` → 报告逐字复制；`gopLength=0xFFFFFFFF` 实际反汇编 `0x1ffffffff`）。
- H-A' 盲实验证明 agent 摘要可引入未证实假设（"换算/放大"）；capstone 反汇编是机械、可复现的 byte-exact 源，不依赖 LLM 判断——最后防线。

## What Changes

- **`tools/disasm_constant_check.py`**（新）：解析 fact / report 代码清单的 `field=value` 赋值断言（#49 格式）+ 行首 VA 锚点（`0x…:`），用 capstone 反汇编对应地址（文件偏移 = RVA − section delta，pefile 解析 section），byte-exact 比对：
  - **fact→disasm**：数值断言（hex/十进制）→ 指令立即数 byte-exact 相等；缩放断言 `X*K` → 该处必须有含 K 的 mul/imul；变量名断言 → 无数据流不可机械验证，记 SKIP（文档化限制）。
  - **report→fact（跨层）**：清单断言按字段名对 fact expected 表——数值 byte-exact（含缩放），变量名相等，数值-vs-变量 → MISMATCH。
  - **report→disasm**：带 VA 的清单断言直接对反汇编跑同一套规则。
- **集成**：(a) `kunglao_verify.py::verify()` 加 `binary_path` 可选参数——提供样本二进制时后置跑 fact→disasm 门禁，MISMATCH → overall REJECTED（fail-open：无 binary / ImportError 不阻断）；(b) CLI 入口 `disasm_constant_check.py --report <listing.md> --reference <fact.md> --binary <pe>` 供报告 handoff 前置调用。
- **tests（RED1-RED4 + a2b5e25c 回测）**：合成最小 PE64 fixture（.text 内嵌 `mov rax, 0x1ffffffff` / `mov eax, 0x3e8` / `imul eax,eax,0x3e8` / `mov [rsp+0x1134], r13d`）。RED1 清单 `frameRateNum=bitrate` vs fact `fps` → 拦；RED2 与反汇编一致 → 过；RED3 VA 不在任何 section → 报错不崩；RED4 空清单/无 VA → 不崩。

## Capabilities

### New Capabilities

- `disasm-constant-check`: fact/report 赋值断言 ↔ capstone 反汇编字节的跨层机械校验。数值断言 byte-exact 比对立即数；缩放断言要求对应 mul/imul；报告清单与 fact expected 逐字段比对（二次转述防错位）。

### Modified Capabilities

- `verify-note`: `verify()` 增加 `binary_path` 可选门禁——fact 的 VA 锚定数值断言与样本反汇编 byte-exact 一致，MISMATCH 拒绝提升。

## Impact

- `tools/disasm_constant_check.py`（新，~200 行）：parse_assertions / _value_kind / va_to_offset / disasm_at / check_assertion_disasm / parse_expected_map / check_fact_disasm / check_report_listing / main(CLI)
- `scripts/kunglao_verify.py::verify()`：`binary_path` 参数 + disasm 后置门禁（~15 行，fail-open）
- `tests/test_disasm_constant_check.py`（新）：RED1-RED4 + a2b5e25c 回测 + 合成 PE64 fixture 构造器
- `references/schema.md`：fact 值断言行首 VA 锚点约定 + report 清单校验入口（两行）
- 依赖：capstone 5.x + pefile（.venv 已验证；test env 可用）；ImportError 时 fail-open
- 关联：与 #49（值断言内容层）、#47/#48（收敛/分发层）互补，四者覆盖 a2b5e25c 问题 1/2 全部失守环节
- 客户事故锚点：a2b5e25c 问题 1；RCA `D:/works/samples/2026-07-28/report_work/verify-customer-feedback/RCA-customer-feedback.md`
