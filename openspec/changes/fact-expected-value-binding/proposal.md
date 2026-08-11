## Why

a2b5e25c 客户 2026-08-11 反馈**问题 1**: 报告代码清单 10 的 NVENC 赋值 (`frameRateNum=bitrate; frameRateDen=fps; averageBitRate=bitrate*1000; ...`) 与二进制实际 (`frameRateNum=fps; frameRateDen=1; averageBitRate=bitrate; gopLength=0xFFFFFFFF`) **全反** — 客户 5/5 REFUTED, capstone + Ghidra 12.1.2 双反汇编器字节级 5/5 CONFIRMED。

根因: F015 (PROVEN fact) 的 `expected:` 字段只列 API 调用序列, 没列赋值断言 → `kunglao_verify.py::l1_mechanical` 把语义文本当 sha256 靶点 byte-exact 比对 → **无真实赋值靶点可比** → verifier 回退到 "semantic key-calls" 复核 (known limitation) → 调用序列对就 PASS → 错赋值漏过进 fixture 进报告。与 C-020 事故同构 (锚点错则全链错: expected 缺值 → 比对空转 → 错赋值进 fixture → 进报告)。

## What Changes

- **fact schema 约定 (BREAKING for assignment/numeric facts)**: `expected:` 含赋值类内容 (字段名 / `=` / 立即数 / 寄存器 / 偏移) 时, 必须列**具体值断言** (field=value + offset/register 来源), 不止 API 调用序列。例: NVENC 初始化 fact 的 expected 必须含 `frameRateNum=fps; frameRateDen=1; averageBitRate=bitrate; maxBitRate=bitrate; gopLength=0xFFFFFFFF` 这类可 byte-exact 比对的断言。
- **`scripts/kunglao_verify.py`**: 对赋值类 `expected` 强制值断言存在 (lint-reject 缺值者); 对值断言做**定向 byte-exact 比对**, 不再把整段语义文本当单一 sha256 靶点。涉及 `l1_mechanical` / `_expected_hash` / `anchor_check` 路径。
- **tests (RED1-RED3 + 回测)**: RED1 expected 缺赋值断言 -> lint 拒; RED2 expected 列值 -> byte-exact 比对; RED3 纯序列 fact (无赋值) -> 过; a2b5e25c 回测 F015 应被新 lint 拒。

## Capabilities

### New Capabilities

- `fact-expected-value-binding`: 赋值/数值类 fact 的 `expected` 必须绑定具体 byte-exact 值断言 (不止 API 序列), 供 `kunglao_verify.py::l1_mechanical` 定向比对; 缺值断言的赋值类 fact 不得提升 (lint-reject)。

### Modified Capabilities

<!-- openspec/specs/ 当前为空, 无既有 capability 被修改 -->

## Impact

- `scripts/kunglao_verify.py` (`l1_mechanical`, `_expected_hash`, `anchor_check`): 新增赋值类 expected 的值断言解析 + 定向 byte-exact 比对 + lint-reject 路径
- fact frontmatter 约定 (`references/schema.md` 或 docs): 赋值类 expected 的值断言格式约定
- `tests/`: 新增 RED1-RED3 + a2b5e25c 回测
- **现有 fact 回填 (BREAKING)**: 含赋值内容的既有 PROVEN fact (如 F015) 在新 lint 下会被拒, 需补值断言后重新 verify — 这正是拦截 a2b5e25c 类错误的意图
- 关联 issues (互补, 不重叠): #47 fact-contradiction (分发/收敛层拦矛盾并存) · #48 inference-claim-blind-scope (BLIND 推断范围) · 本 change = **fact 内容层** (expected 必须可 byte-exact)
- 客户事故锚点: a2b5e25c 问题 1; RCA `D:/works/samples/2026-07-28/report_work/verify-customer-feedback/RCA-customer-feedback.md`
