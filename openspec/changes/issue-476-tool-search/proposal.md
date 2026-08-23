# tool-search 三方工具发现 — ext 索引(repo 内三源) + 零新信任机制 (#476)

## Why

2026-08-18 实战(issue #476 现象):worker 宣称"自动化工具跑不动"的清单
只看得见 `tools/_INDEX.yaml` 内部注册面。仓库里**实际可调用的能力**远不止
这一个注册面 — `scripts/` 的 82 个入口点 CLI(102 个 .py 中)、
`hooks/` 的 8 个执行面 gate(9 个 .py 中)、`references/re-library/` 的
29 篇能力声明域文档,全部"存在但没人知道能干嘛"。#494 已把"动手前必搜"写进 8 个 agent 契约(三点查:
`scripts/re` / `tools/_INDEX.yaml` / `references/re-library/`),但搜索
本身没有机械查询面 — 契约要求搜,却只能靠 agent 手工 ls/grep。

## What Changes

- **`tools/_INDEX.ext.yaml`(新,生成物)** — ext 索引,repo 内三源枚举:
  `scripts/*.py` 入口点 CLI + `hooks/*.py` 入口点 gate +
  `references/re-library/*.md` 能力声明文档。每条
  `name / capability / source / usage / description`。**零新信任机制**:
  ext 条目只描述、不自动执行 — 消费仍走 #494 契约的人工声明链
  (tools_used 引用 → Gate 5 可解析性判定),信任边界保持在既有
  provenance gate 的 artifact 层(raw artifact → evidence 索引 → 盲验)。
- **`tools/ext-scan.py`(新,meta-tool)** — 确定性生成器:结构化
  (AST `__main__` 入口判定,非文件名清单/regex)枚举三源,合并可选
  capability map(`tools/_INDEX.ext.map.yaml`,未映射 → `capability:
  unknown` — 发现不依赖 map),写出 ext 索引;`--check` 检测陈旧。
- **`tools/_INDEX.ext.map.yaml`(新,可选 map)** — 已知名 → capability
  标签的静态子集映射,只提升可检索性。
- **`tools/tool-search.py`(改)** — 增 `--find <关键词>` 发现模式:
  跨内部 `_INDEX.yaml` + ext 索引的子串检索(零 LLM / 零网络契约
  不变),输出 name + source + usage 行 — "动手前必搜"的机械支撑。
- **`devkit/doc_sync.py`(改,Gate 7 子检 d)** — 索引一致性门:
  ext 条目指向不存在的文件 / 模式残缺 / 与内部注册名撞名 → FAIL;
  入口点 scripts/hooks 未入索引 → WARN(修法 = 重新生成),与 #446
  三子检同风格。
- **`devkit/subagent_review.py`(改)** — `_index_tool_names` 纳入 ext
  条目名(#493 的 tools_used 可引用 ext 逻辑名,fail-closed 语义保持)。
- **`tools/README.md` + `tests/test_tools_structure_340.py`(改)** —
  根层 meta-tool 例外扩为三个(tool-search / validate_index / ext-scan),
  ext 索引入目录布局。

## 不做什么(范围边界)

- 不实现 issue 原文架构段的 `mcp_probe.registered_names` 环境侧三源与
  `mcp__*` dispatch 面(本派发按 orchestrator task spec 重定义为 repo
  内三源;环境侧枚举不可复现于测试,留待后续 issue);
- 不动 `hooks/worker_budget.py` 的 HOST_FORBIDDEN_TOOLS 安全面;
- 不改 8 个 `agents/*.md` 契约文(#494 已落地面,查询命令的契约接线
  记入 RUNBOOK 后续项);
- 不给 ext 条目任何执行通道(零新信任机制的构造性保证)。
