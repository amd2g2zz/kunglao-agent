# MCP Tool-Search 环境侧半边 — mcp_probe 枚举 + mcp__* dispatch 验收 + artifact→evidence e2e (#515)

## Why

#476 交付了 repo 内半边(scripts/hooks/re-library 三源 119 条 ext 索引 +
`--find` 查询面 + Gate 7 一致性子检), 评审裁决 PASS-with-followup 并将
环境侧半边拆至本件: issue 触发场景的 camoufox/gitnexus/playwright 类
**MCP** 工具零覆盖 — #476 的三源全是 repo 文件, 环境里注册的 MCP server
不在其中, "动手前必搜"(#494)对 MCP 面是盲的(#462 工具发现三要素的最后一角)。

## What Changes(issue 三验收项)

1. **mcp_probe 环境侧三源枚举**(`scripts/mcp_probe.py`): 新增
   `--mcp-inventory` 输出模式 — 从 `--claude-json` 的 mcpServers(全局 +
   `projects.*` 作用域)与 `<ws>/.mcp.json` 三注册面枚举**已注册** server:
   name / 工具前缀 `mcp__<server>__*` / 注册面 / 按型 required-optional
   (MANIFEST tier 注解, manifest 外 = environment-extra)。只读、零网络、
   零 spawn; 密钥卫生: 只出名字/来源/tier, 不出 command/args/env/url 值。
2. **ext 索引接线**(`tools/ext-scan.py`): `--with-mcp <probe.json>` 把
   probe 清单合并为 ext 条目(name=`mcp__<server>`, source=`claude-json`
   溯源标签)。**提交态索引保持环境无关**(repo 再生成不带 `--with-mcp`);
   零新信任机制不变 — mcp 条目同 #476 只描述不执行, 消费面仍是 `--find`
   打印 + tools_used 解析。
3. **dispatch 验收**(`hooks/worker_budget.py` + 测试固化):
   (a) VM 通道名(`mcp__x64dbg__connect_remote` 等)过 intended_tools 校验;
   (b) HOST_FORBIDDEN_TOOLS 6 项 REJECT 零回归(VM-ONLY 契约不动);
   (c) intended tools 含 `mcp__camoufox__*` 类通配/前缀形态的匹配语义 —
   显式通配若**覆盖** host-forbidden 名则同语义 REJECT(精确名语义不动,
   只紧不松)。
4. **三方 artifact→evidence e2e**(`tests/test_mcp_env_e2e.py`): 测试构造
   假 claude-json(camoufox/gitnexus/playwright 三 server)→ 探测枚举(产物
   落 `<ws>/evidence/`)→ ext 索引生成 → `--find` 命中 → tools_used 引
   mcp 条目过 Gate 5 校验面 — 全链一条 CI 可复现测试。

## 不做什么

- 不连接、不 spawn 任何 MCP server(探测 = 读配置文件);
- 不放宽 HOST_FORBIDDEN_TOOLS(6 项名与 REJECT 语义原样);
- 不给 mcp 条目加任何执行通道(索引是目录, 不是白名单/信任面);
- 不把本机环境面提交进仓库(提交态 ext 索引仍纯 repo 三源)。
