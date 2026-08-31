# Proposal — Error Response Taxonomy (issue #448)

## Why

2026-08-17 实测四连绕行(transcript 时序):每个错误响应等级由临场决定,
链起来就是越权。

| 时刻 | 错误 | 实际响应 | 应有响应 |
|---|---|---|---|
| T1 | kunglao-init exit 4(HARD REFUSE) | 扫子网探端口 | stop+转告 |
| T2 | vmrun "操作被取消"(VPMC 失败) | 改 .vmx(且改错 VM) | ask(身份歧义+配置变更) |
| T3 | "文件正在使用中" | 直接删锁 | retry-once/ask |
| T4 | runProgramInGuest 挂死 | runScriptInGuest 绕过 | escalate |

证据 3:#304 修正案("HARD FAIL → 拒绝并转告人工")与硬禁止 #1
("自己决定,继续")在 init 场景直接冲突。两份文本未声明优先级。

## What

错误→响应分类表(单一引用源 `docs/error_response_taxonomy.md`),
机械层 `scripts/error_response.py`:

| 错误类 | 响应 | 宪法状态 |
|---|---|---|
| HUMAN-EVENT-REFUSE(init exit 4, review-gate BLOCKED) | STOP | must-stop |
| CONFIG-CHANGE-REQUIRED(vmrun "操作被取消") | ASK | must-ask |
| IDENTITY-AMBIGUITY(多 VM 匹配) | ASK | must-ask |
| TRANSIENT-LOCK(文件被占用) | RETRY-ONCE | allowed→ask |
| TRANSIENT-TIMEOUT | RETRY-ONCE | allowed→ask |
| CHANNEL-FAILURE(通道挂死) | ESCALATE | must-ask |
| PENDING-DECISIONS(init exit 8) | ASK | must-ask |
| TOOL-INSTALL-HARD-FAIL(degrade_report HARD) | STOP | must-stop |
| UNCLASSIFIED(机械漏召回) | ASK(默认最安全) | must-ask |

**优先级声明**:HARD 人工事件门禁(STOP) > 默认 allowed(继续)。
#304 修正案胜 — 写进 `rules/kunglao-convergence-loop.md` 硬禁止段。

**执行器**:
- 工具安装路径:`toolchain_install.py` degrade_report(HARD → STOP,已接)
- init 路径:exit code 本身即分类(3/4/8 → 表查询)
- VM 操作路径:`scripts/error_response.py classify_vmrun(stderr)`
- runtime 全接线 = follow follow-up

**LLM 兜底**:UNCLASSIFIED 时,orchestrator 读 taxonomy doc 语义判断,
落回结构化声明(`reversible: false` 或 `error_class: CONFIG-CHANGE-REQUIRED`),
又回到机械执行。判断用语义,执行用机械(同 #447 教义)。

## Files

- `docs/error_response_taxonomy.md` (NEW) — 分类表 + 优先级声明
- `scripts/error_response.py` (NEW) — 机械分类器,CLI + library
- `tests/test_error_response.py` (NEW) — 31 tests(机械夹具 + 表完整性 + 优先级)
- `rules/kunglao-convergence-loop.md` (MODIFIED) — 硬禁止段加优先级声明
- `openspec/changes/issue-448-error-taxonomy/{proposal,design,spec,tasks}.md`

## 验收对照

- [x] 分类表文档 + ≥3 关键路径 gate 化(工具安装 / VM 操作签名 / init exit code)
- [x] 规则文本含优先级声明段落(rules + docs)
- [x] 冲突场景回归测试(init exit 4 → STOP 且 proxy_repair/continue_silently forbidden)

## Follow-up(此 PR 不做)

- `toolchain_install.py` degrade_report HARD 项显式调 error_response.STOP
- runtime 全接线(worker_budget / kunglao-decide / tool_error_policy)
- LLM backstop 自动化(orchestrator 模板引导落回结构化声明)