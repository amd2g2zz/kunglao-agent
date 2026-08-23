# Design — ext 索引三源枚举 + 零新信任机制 (#476)

## D1. 独立 `tools/_INDEX.ext.yaml`,不并入内部索引

内部 `tools/_INDEX.yaml` 的 schema(tools-index/1)是**执行注册面**:
category == `tools/<category>/` 目录名、tier/cost_tier、input_output。
ext 条目是**描述目录**,没有执行语义(tier/cost_tier 会是伪造值,
category 无目录可对)。两个选择里:

- 并入(内部 yaml 加 `ext:` 段):逼 validate_index 分叉两套 schema,
  且消费面(tool-search / _index_tool_names)要区分"可执行注册"与
  "仅描述" — 信任边界靠约定不靠结构;
- 独立文件:信任边界**结构化** — 内部索引 = 执行注册,ext 文件 =
  描述目录,消费方一眼可辨,内部契约零改动。

选独立文件,schema `tools-ext-index/1`,条目字段
`name / capability / source / usage / description`(name 唯一、
source 必须存在、capability 非空且含冒号时两侧非空)。

## D2. 三源 = repo 内可复现面(对 issue 原文的重定义,记录在案)

issue 原文的"三源"是 `mcp_probe.registered_names` 的环境侧三源
(user-global / project-scoped / workspace .mcp.json) — 依赖运行机器的
`~/.claude.json`,测试与 CI 不可复现。本变更按派发 task spec 落地
repo 内三源(全部可从仓库字节推导):

1. `scripts/*.py` — 有入口点的 CLI(102 文件中 82 个);
2. `hooks/*.py` — 有入口点的 gate(8 个);
3. `references/re-library/*.md` — #494 三点查的第三点,
   能力声明域文档(29 篇)。

`references/tool-inventory.md` / `dynamic-re-tool-priority.md` 考虑过
并排除:前者是存量清单(与 ext 索引同类,会被本索引取代其"清单"角色
的一半),后者是选型指南非能力声明 — 收进来的判据不足,留待需要时
扩 generator 的 SOURCE_RULES 一行。

## D3. 入口点判定 = 结构化声明,非文件名清单

"哪些 scripts 是工具脚本"用 AST 判定:模块顶层存在
`if __name__ == "__main__":` 节点.Compare(Name('__name__') == '__main__')
的树形匹配,不做文件名枚举、不扫自然语言 regex(规则:枚举任何语言
的 regex 不可穷尽;检测走结构化声明通道)。20 个无入口点的库模块
(lib_kunglao.py / status_defs.py / …)结构上即被排除 — 这就是
"域白名单"的实现形式:白名单是**结构属性**,不是名单文件。

## D4. capability map 可选,未映射 = `unknown`(发现不依赖 map)

`tools/_INDEX.ext.map.yaml`:`name: tag` 静态子集映射(种子 ~20 条
高流量项)。未映射条目 `capability: unknown` — issue 验收语义原样
保留("不维护 map 也能发现")。可检索性兜底:`--find` 关键词模式
匹配 name+capability+description+usage(+source),capability 为
unknown 的条目照样按名/描述命中。map 命中率不设门槛 — 它只提升
可检索性,不是完整性义务。

## D5. 生成器 `tools/ext-scan.py` = tools/ 根层第三 meta-tool

- stdlib-only(ast/pathlib/sys,不 import yaml — 输出格式自控,
  手写序列化保确定性;devkit 约定 stdlib-only 也因此可复用其谓词);
- `python tools/ext-scan.py` 重新生成;
  `--check` 内存重生成后与盘上文件逐字节比对,陈旧 → exit 1;
  `--stdout` 打印不落盘(测试确定性用);`--root <dir>` 支持沙盒树;
- usage 行推导:scripts 取模块 docstring `Usage:` 块首行(无则
  `python <source>`);hooks 用固定模板
  `hook <source> (settings.json wiring; JSON on stdin; exit code = verdict)`;
  references 用 `read <source> (capability reference)`;
- description 推导:scripts/hooks 取 docstring 首行;references 取
  frontmatter `description:`(无则首个 H1)。
- 生成器不注册进任何索引(querier 不入被查注册表 — tool-search
  同款纪律);meta-tool 例外写进 tools/README 结构规则 +
  test_tools_structure_340 META_TOOLS。

## D6. 零新信任机制 = 构造性,不是承诺

ext 条目只被两件事消费:(1) `tool-search --find` 的**读+打印**;
(2) Gate 5 `tools_used` 的**引用可解析性**判定(引用 ≠ 执行)。
没有任何代码路径从 ext 索引出发执行条目。事实信任仍走既有
provenance gate:三方工具产出落盘 raw artifact → evidence 索引 →
盲验;只吐结论文本 → derived summary → 既有规则排除(issue 的
artifact 层论证原样成立)。

## D7. Gate 7 子检 (d):一致性门(#446 同风格)

`devkit/doc_sync.py` 增第四子检,读**工作树**的 ext 索引(查询面
消费方读的就是工作树 — 门与消费方同源;#446 (b) 的 staged 读法
针对"pin 必须随本提交走",本检的失效模式是"索引指向的文件没了",
工作树读法同时覆盖两种时序):

- **FAIL(rc 1)**:条目缺 name/capability/source 任一;source 路径
  不存在;ext name 与内部 `_INDEX.yaml` 注册名撞名(裸名解析不许
  有二义性);
- **WARN(rc 0 附加)**:入口点 scripts/hooks 未入索引 — 修法
  `uv run python tools/ext-scan.py`(比 #446 (c) 只查 staged-new 更
  强:生成器落地时已全覆盖,无存量债,任何缺口 = 索引陈旧);
- ext 文件缺席 → N/A 通过(存在性由测试 pin,不由门勒索)。

行级解析 ext/内部 yaml(devkit stdlib-only 约定,同 `_parse_pins`);
入口点谓词从 `tools/ext_scan.py` import(`_registry_note` 已有
sys.path.insert 先例),单一事实源。

## D8. `--find` 与既有过滤器互斥

`--find <kw>` 是发现模式(内部 + ext 联查),`--capability/--tier/
--cost-max` 是内部目录过滤模式。混合 → usage error(exit 2):
ext 条目无 tier/cost_tier,AND 语义会静默把 ext 全滤掉 — 显式
拒绝优于静默收窄。命中输出:name / kind(internal|ext)/
capability / source / usage(内部条目 source = `tools/_INDEX.yaml`
即其解析注册表,usage = input_output;ext 条目 source = 条目
source 路径,usage = 条目 usage)。

## D9. `_index_tool_names` 纳入 ext 名,fail-closed 方向保持

内部索引损坏 → 空集(现状,#493)。ext 文件损坏/缺席 → 只丢 ext
名,内部名不受牵连(内部条目仍可验真;两索引独立损坏不应互相
放大)。裸名解析由此多一类合法名,仍受 (d) 的撞名 FAIL 保护
无二义性。

## D10. RED 通道

- `tests/test_ext_index.py`(新):shipped 索引 pin(存在/三源齐/
  source 全存在/unknown 可出现/内外零撞名)、ext-scan 确定性与
  --check 陈旧检出(沙盒树)、--find 行为(内外联查/大小写/
  空命中/互斥 usage error)、零网络模块断言、_index_tool_names
  ext 纳入;
- `tests/test_doc_sync.py`:子检 (d) FAIL/WARN/N-A/修法提示
  (_Repo 沙盒模式,沿用既有 _Repo 类);
- `tests/test_subagent_injection.py`:ext 裸名解析类 + fail-closed。
