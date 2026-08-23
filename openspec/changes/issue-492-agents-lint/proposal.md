# agents/*.md 三要素静态 lint — Gate 6 Agents Contract (#492)

## Why

Issue #492(#462 拆件二,#462 已关)。Gate 5(Subagent Review / Maker-Checker,
`devkit/subagent_review.py`)是 **commit-time 执行层**契约通道:只强制
`.subagent-review/*.json` 的 5 字段形状 + 反自签 + tools_used 非空。但 #462
验收第二条要求**定义层**静态断言:agent 定义文件本身必须含三要素声明。
#462 证据 2(契约审计):5 个 specialist agent 的 `agents/*.md` 三要素
(plan / state-sync / tool-discovery)**各 0 条**,而 kunglao-worker 单独有
12 / 6 / 2 条 — specialist 恰是长时运行、高爆炸半径的角色。

定义层缺失没有机械信号:agent 文件退化成"裸 pipeline 说明书"时,没有任何
门拦住;执行层 Gate 5 只能事后追认。缺一个**事前**定义层门。

## What Changes

- **结构性声明通道**(用户教义:结构化声明优于 prose regex — 任何语言的
  prose 条款枚举不可穷尽):每个 `agents/*.md` 须含三个显式 HTML 注释
  标记 `<!-- contract: plan-to-execute -->` / `<!-- contract: status-sync -->`
  / `<!-- contract: tool-discovery -->`,标记后(到下一标记或 EOF)须有
  ≥2 行非空内容。标记文法有限可枚举 = 机械可判;标记下的 prose 保持
  任意语言自由形式,零枚举。
- **lint 实现** `devkit/agents_lint.py`:扫 `agents/*.md`,任一标记缺失或
  标记后内容 <2 非空行(空心声明)→ rc=1 FAIL,列文件与缺项;全过 rc=0;
  `--json` 机器可读输出;fail-closed(agents/ 缺失 / 零 .md / 文件不可读
  全算违规)。
- **补齐现有 8 个 agent 定义**(实际文件数:issue 正文列 10,实际 8 —
  无 cti-correlator.md / shodan-host.md):kunglao-worker.md 在既有三节旁
  加标记(模板基准,零新 prose);其余 7 个在文件尾追加最小契约块,内容
  从各文件现有 prose 提炼。**只加标记与最小内容,不重写既有 prose** —
  #494(specialist 契约扩写)的领地。
- **Gate 接线**:quality_gates.py 注册 Gate 6(Agents Contract);
  pre-commit 模板 `1 3 4 5` → `1 3 4 5 6`,模板头注释同步(修 G 类
  drift:模板头说 1+3+4 实际跑 1 3 4 5 的既有漂移一并修);quality_gates.py
  docstring 门数同步(docstring 说 4-gate,实际 6 门)。

## Impact

- **代码**:`devkit/agents_lint.py`(新)、`devkit/quality_gates.py`
  (Gate 6 注册 + docstring 门数修正)、`devkit/githooks/pre-commit`
  (门列表 + 头注释)、`tests/test_devkit_quality_gates.py`(docstring
  门数描述同步,行为不动)。
- **agent 定义**(8 文件,additive only):`agents/kunglao-worker.md`
  (3 标记行)+ ghidra-light / go-symbols / floss-filter / pefile-signature /
  verdict-scorer / kunglao-init-worker / kunglao-redteam(尾部最小契约块)。
- **行为面**:新增门 — agents/*.md 缺三要素任一 → HARD_PAUSE(rc=1,
  quality_gates 整体 FAIL)。与 Gate 5 互补:lint 抓定义层缺失,
  .subagent-review 抓执行层缺失。
- **不做**:不改 Gate 5 域前缀(agents/ 不入 DOMAIN_PREFIXES — 定义层
  门每次全量跑,无需域触发);不扩写 agent 契约内容(#494 领地);不动
  devkit/docs/quality_gates.md 的 #463 4-gate 框架叙述(历史文档,
  Gate 5 当时也未入文档 — 归 #446 机制治理);不新增 frontmatter 字段
  (route_capability.py 消费面不碰)。

需求源: issue #492 (github.com/amd2g2zz/kunglao-agent/issues/492)
架构约束: issue #498 G 类(机制治理:门数/文档漂移)+ 用户教义
"结构化声明优于 prose regex"(memory: structural-declaration-over-regex)
