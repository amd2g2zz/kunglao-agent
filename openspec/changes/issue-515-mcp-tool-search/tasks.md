# Tasks — issue-515-mcp-tool-search

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/515` 分支 `v012/issue-515-mcp-tool-search`(基 `origin/dev` @087da92)
- [x] 1.2 必读: #515 正文三验收项 / #476 评论区范围裁决 / scripts/mcp_probe.py(#316) / hooks/worker_budget.py:37-53+665-694 / tools/ext-scan.py + tools/_INDEX.ext.yaml + tools/tool-search.py --find / devkit/subagent_review.py(_index_tool_names) + devkit/doc_sync.py(Gate 7 子检 d)

## 2. SDD

- [x] 2.1 proposal.md(Why + 三验收项映射 + 不做什么)
- [x] 2.2 design.md(D1 枚举面裁决 / D2 --with-mcp 接线+提交态环境无关 / D3 mcp__ 前缀单一规则 / D4 溯源存在性语义 / D5 通配覆盖 + R1-R3)
- [x] 2.3 tasks.md(本文件)

## 3. RED(测试先行)

- [x] 3.1 SDD commit → RED 哈希(该哈希下新测试不存在, pytest 红)
- [x] 3.2 五处测试先行: test_mcp_supply(TestMcpInventory) / test_ext_index(TestMcpWiring) / test_worker_budget(mcp dispatch 三组) / test_doc_sync(TestExtIndexMcpProvenance) / tests/test_mcp_env_e2e.py(全链一条)

## 4. GREEN(实现)

- [x] 4.1 scripts/mcp_probe.py `--mcp-inventory`(三注册面枚举 + 密钥卫生 + 与 --json/--reproduce 互斥)
- [x] 4.2 tools/ext-scan.py `--with-mcp <probe-json>`(条目生成 + 冲突护栏 + exit 1/2 语义)
- [x] 4.3 tools/tool-search.py --find 的 mcp kind 投影(mcp__ 前缀规则)
- [x] 4.4 devkit/doc_sync.py Gate 7 环境条目溯源分支(ENV_PROVENANCE_SOURCES)
- [x] 4.5 hooks/worker_budget.py 通配覆盖语义(精确名 6 项不动)
- [x] 4.6 再生成 tools/_INDEX.ext.yaml(header 更新) + scripts/README.md / tools/README.md 目录登记(#451/#466 教训)

## 5. 门禁

- [x] 5.1 `uv run ruff check .` 零 finding
- [x] 5.2 快检 `uv run python -m pytest -q -m "not load_sensitive"` 相关测试文件全绿
- [x] 5.3 `uv run python devkit/quality_gates.py 1 3 4 5 6 7` ALL-PASS
- [x] 5.4 Gate 5 JSON: `.subagent-review/2026-08-20-515.json`(verified_by="pending-515-reviewer")

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(RED 哈希 / 测试映射 / 门禁结果 / 自认风险)— 永不提交
- [x] 6.2 硬约束核验: 无 push / 无 PR / HOST_FORBIDDEN_TOOLS 6 项名与 REJECT 语义零改动 / mcp 探测只读
