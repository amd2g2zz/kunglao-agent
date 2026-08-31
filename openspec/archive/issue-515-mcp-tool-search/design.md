# Design — issue-515-mcp-tool-search

## D1. 枚举面裁决: 独立 `--mcp-inventory` 模式, 不并入 --json

- `--json` 是**检查面**(exit 0/1/2 由 HARD/WARN 缺失决定), inventory 是
  **枚举面**(列出环境事实, 恒 exit 0)。语义不同 → 独立 flag, 与
  `--json`/`--reproduce` 互斥(argparse error → exit 2)。既有 `--json`
  输出形状字节不变(tests/test_mcp_supply.py 已钉)。
- inventory 与 project type 无关(枚举全部注册面), 不要求 `--type` /
  `analysis_state.txt` — 绕过 check_mcp 的 ValueError 路径。
- 读入面复用 `registered_names()`(#316 既有: 全局 + projects 作用域 +
  workspace .mcp.json, 小写规范化) — 枚举不发明第二个注册面真相源。

## D2. ext 索引接线: `tools/ext-scan.py --with-mcp <probe-json>`, 提交态环境无关

- 生成入口选 `--with-mcp` flag(而非独立子命令): 复用 ext-scan 既有
  capability map / 内部注册名冲突护栏 / 确定性渲染, 少一个并行入口。
- mcp 条目字段: `name=mcp__<server>`(canonical 小写, 与 probe 匹配语义
  一致), `source="claude-json"`(**溯源标签, 不是 repo 路径**),
  `capability` 默认 `mcp:<server>`(map 可按全名覆盖), usage/description
  为描述性文本(含 `--mcp-inventory` 再生命令与 describe-only 声明)。
- **提交态 tools/_INDEX.ext.yaml 不含 mcp 条目**: 环境面按机器不同,
  提交它 = 把某台机器的 ~/.claude.json 形状钉进 repo。纯 repo 再生成与
  `--check`(不带 `--with-mcp`)保持不变; e2e 用 `--root <sandbox>` 验证
  接线。误提交的自纠路径: 下次纯 repo `--check` 报 stale。
- exit 语义: probe 文件不可读/非 JSON → exit 2(用法错); 形状违例
  (缺 servers / 重复 server / 名字形状错) → ValueError → exit 1
  (生成器级不一致, 与既有冲突护栏同级)。

## D3. mcp-ness 判定 = 名字前缀 `mcp__`(结构约定, 单一规则)

- 盘上条目**不新增 kind 字段**(仓库 119 条不动, 无 schema 漂移);
  `mcp__` 前缀即 MCP 工具命名约定(`mcp__<server>__<tool>`)的服务器级
  形式。tool-search `--find` 投影 `kind=mcp`、doc_sync Gate 7 环境分支
  均用同一前缀规则 — 不引入第二个真相源(枚举自然语言 regex 不可穷尽,
  结构化命名才是检测通道)。

## D4. Gate 7 一致性: 环境条目的"存在性语义" = 受认可的溯源标签

- repo 条目: `source` 必须 `(REPO_ROOT / source).exists()`(原样)。
- `mcp__` 条目: `source` 必须 ∈ `ENV_PROVENANCE_SOURCES=("claude-json",)`
  且名字匹配 `^mcp__[a-z0-9][a-z0-9_-]*$`。生成机的 claude-json 路径
  既不可移植也不可从 repo 验证 → 存在性检查对环境条目退化为**受认可
  溯源**检查(伪造/手改成任意路径 → FAIL, 与 dangling repo 路径同级)。

## D5. dispatch 验收: 通配覆盖语义(只紧不松)

- 精确名: `check_host_forbidden_tools` 的 6 项成员判定原样(零放宽,
  硬约束)。
- 显式通配项(`*` 结尾): 其前缀**覆盖**任一 HOST_FORBIDDEN 名 → 同语义
  REJECT(`mcp__frida__*` 覆盖 spawn/attach; `mcp__x64dbg__*` 覆盖 4 项
  x64dbg host 通道)。理由: intended_tools 通配 = worker 可合法取该族
  任一工具, 覆盖禁用名即未承诺 VM-only 子集。canonical 派发形态是具体名
  (references/dynamic-re-tool-priority.md:45
  `[T3 tools=mcp__x64dbg__set_breakpoint,...]`), 仓库唯一现存通配派发
  用例(tests/test_recall_inject.py VM_CLAIM)走 recall_inject 钩子
  (永不 REJECT), 不经本检查 → 零现存回归。
- `check_tools_allowed`: 前缀映射已存在(`tool_to_constraint` 的
  `mcp__x64dbg` startswith → vm_detonation), `mcp__camoufox__*` 类非 VM
  族 → 无约束 → PASS; 两个方向均补测试钉死。

## 风险

- R1: 通配覆盖 REJECT 是行为收紧 — 现场若有未入库的通配派发习惯会被
  拦; REJECT 消息保留 connect_remote 具体名修复指引。
- R2: `--with-mcp` 生成的索引若被误提交, 纯 repo `--check` 报 stale
  (自纠: 重新纯再生)。
- R3: inventory 密钥卫生靠"不输出值"维持 — 将来加 transport 字段必须
  延续"只出类别不出值"(config env 可能带 API key)。
