# Design — Gate 6 Agents Contract (#492)

## 问题边界

"定义层契约门" = agent 定义文件(`agents/*.md`)的三要素静态断言。执法
表面是新脚本 `devkit/agents_lint.py`,由 `devkit/quality_gates.py` 的
GATES 注册表接线;pre-commit 模板同步门列表。**不是**本变更(范围外):

- 不做 prose 条款枚举(教义:任何语言不可穷尽;检测通道 = 标记文法,
  prose 只在标记 span 内自由存在,不被解析);
- 不改 Gate 5(`subagent_review.py` 原样;两门互补不合并触发逻辑);
- 不扩写 agent 契约实质内容(#494 领地,本件只过 lint);
- 不动 agents frontmatter(`route_capability.py` 消费 `triggers:`,
  加字段会与路由解析耦合);
- 不动 devkit/docs/ 的 #463 4-gate 框架叙述(历史文档,门 5 当时亦未
  入文档;统一治理归 #446)。

## D1. 声明通道二选一 — HTML 注释标记(否决 frontmatter `contract:` 列表)

两个候选:(a) 正文 HTML 注释标记;(b) frontmatter `contract:` 列表。
**选 (a)**,理由:

1. **声明与内容同体可验**:标记后的 span 就是 agent 实际消费的指令字节,
   lint 可同时验存在性 + 实质内容(≥2 非空行)。frontmatter 列表只能验
   存在性 — "声明有、正文无"的空心声明会原样通过,复活 status≠验证
   (maker-checker §4)陷阱。issue 验收原文即要求"标记后无实质内容"可拦。
2. **不碰路由消费面**:frontmatter 已被 `scripts/route_capability.py`
   解析(triggers 表);往里加契约语义扩大了路由解析的责任面,且 YAML
   声明与正文内容可分叉,制造新 drift 面。
3. **additive 最优**:HTML 注释渲染不可见、对 agent prompt 干扰最小,
   插入点可贴既有 section(kunglao-worker 零新 prose)或文件尾(#494
   只需扩 span 内内容,不搬动结构)。
4. **文法有限可枚举**:标记行文法 `^\s*<!--\s*contract:\s*(element)\s*-->\s*$`
   与命令文法同类(教义第 1 优先机械层的"文法有限可枚举"例)。

标记三要素(element 与 #462 契约同名):

| element | 契约含义 | kunglao-worker 模板锚 |
|---|---|---|
| `plan-to-execute` | 先写计划再动手(禁 trial-and-error 裸奔) | `## Plan-to-Execute (v1.9.29)` |
| `status-sync` | 状态/产物文件落盘(报 done 无文件 = FAILED) | `## State-write protocol` |
| `tool-discovery` | 工具发现 + 禁自造(先查 toolshelf/复用,不自造) | `## Script reusability` |

## D2. lint 语义 — span 计数 + 围栏豁免 + fail-closed

- **span**:某标记行到下一个**任意 element** 的标记行(或 EOF);span 内
  非空行(去空白后非空)计数 `< MIN_CONTENT_LINES(=2)` → 违规
  "空心声明"。2 行 = 有实质的最小单位;1 行存根 = 声明无内容。
- **逐次出现全验**:同一 element 多次出现时,每次出现都须非空心 — 尾部
  裸复制的标记(空心)同样违规,防"真节 + 假标记"的糊弄面。
- **围栏豁免**:扫描跳过 ``` / ~~~ 围栏代码块内的标记行 — 文档引用标记
  文法(示例块)不应制造幻影标记(幻影 + 逐次全验 = 假阳性 HARD_PAUSE)。
  未闭合围栏 → 其后全豁免(fail-safe 方向:少认标记,不误认)。
- **未知 element 忽略**:`<!-- contract: future-x -->` 不识别不报警 —
  前向兼容,#494 若加 element 只改 CONTRACT_ELEMENTS 单点。
- **fail-closed**:agents/ 目录缺失 / 零 *.md / 文件不可读 → 全部计为
  违规 rc=1(空目录/缺目录不许绿 — 对齐 plan Edge Cases "空目录/缺
  claim-register (#449/#492)" 行)。
- **rc 契约**:0 = 全过;1 = 有违规;2 = argparse 用法错(镜像
  quality_gates 语义)。`--json` 输出 `{ok, agents_dir, agents[],
  violations[]}`,violations 每条带 `file` + `element` + `problem`
  (issue 要求"列文件与缺项")。
- **可测性接缝(SEAM 模式)**:`lint_text(text)` 纯函数 / `lint_dir(path)`
  目录级 / `check()` 打印 + rc,三层;REPO_ROOT 模块级可 monkeypatch
  (镜像 subagent_review.py)。

## D3. Gate 接线 — 新 Gate 6(否决并入 Gate 5 子检查)

- **常驻而非域触发**:agents/*.md 是常驻资产,定义层检查应像 Gate 1
  (contract modules present)一样每次运行(纯文件读,<10ms);Gate 5 的
  N/A 语义(非域路径平凡通过)与"每次检查定义层"语义不匹配 — 并入
  Gate 5 要么改其触发语义(动已验证代码),要么退化成域触发(agents/
  不变更有漂移不拦)。
- **语义分层即文档**:issue 原文"与 Gate 5 互补:lint 抓定义层缺失,
  .subagent-review 抓执行层缺失" — 两个门各占一个注册位,分层自文档。
- **注册模式**:GATES dict 加 `6: ("Agents Contract", _gate6_...)`,
  函数体 import agents_lint.check() 并 `bool(rc == 0)`(镜像 _gate5 的
  rc 布尔转换注释 — 真值陷阱同源)。

## D4. G 类 drift 同步(门数三载体)

修三处门数漂移(教训:写死门数 = 下次加门必漂):

1. `devkit/quality_gates.py` docstring:"4-gate"/"all 4 gates" → 门数
   从 GATES 派生的表述(注册表即真相,docstring 不写死数字);
2. `devkit/githooks/pre-commit`:命令行 `1 3 4 5` → `1 3 4 5 6`(两处),
   头注释 "Gates run: 1+3+4"(本身已漂 — 实跑 1 3 4 5)→ 全列 5+6;
3. `tests/test_devkit_quality_gates.py` docstring "4-gate runner" 描述
   同步(注释,行为不动)。

pre-commit 模板头注释的门列表是给人读的,无法从 bash 派生 — 同步改并
在测试里钉住(`1 3 4 5 6` in 模板文本),漂移即测试红。

## D5. 验收映射

| 验收点(issue #492) | 测试 | 断言 |
|---|---|---|
| 缺三要素任一 → HARD_PAUSE | TestLintText::test_missing_* (参数化×3) | lint_text 违规含 element;lint_dir rc=1 |
| 标记后无实质内容(<2 行/空) | test_bare_marker / test_one_line_stub / test_blank_lines | 违规 problem 含 "non-empty content" |
| 全过 rc=0 | test_two_content_lines_pass / test_real_repo_agents_all_pass | 0 违规 |
| --json 输出 | TestCLI::test_json_output | violations 带 file+element,可解析 |
| 空目录/缺目录 fail-closed | TestLintDir::test_missing_dir / test_empty_dir | rc=1,违规非空 |
| Gate 6 注册 | TestGateWiring::test_gate6_registered | GATES[6] == "Agents Contract" |
| pre-commit 同步 | test_pre_commit_template_lists_gate6 | 模板含 "1 3 4 5 6" 且无 "4-gate" |
| docstring 同步 | test_quality_gates_docstring_no_stale_count | 源码无 "4-gate"/"all 4 gates" |
| 8 个 agent 全过 lint | test_real_repo_agents_all_pass | agents_dir ok=True,8 文件 |
| 围栏内标记不幻影 | test_marker_inside_fence_ignored | 围栏内标记 0 出现 |
| 裸复制标记 | test_duplicate_bare_marker_fails | 第二次出现判空心 |

## R1-R5(风险与不做)

- **R1 幻影/漏认标记**:围栏豁免 + 未闭合围栏全豁免 — 宁漏认不误认;
  真标记被未闭合围栏吞掉的代价 = lint 绿而契约缺(下一道防线是 Gate 5
  执行层与 reviewer),误认的代价 = HARD_PAUSE 假阳性(直接卡提交),
  不对称下取漏认。
- **R2 "≥2 行"是存在性不是质量**:内容质量由 #494 扩写与 reviewer 把关,
  本门只防"零声明/空心声明"退化 — 与 Gate 1(模块存在可导入)同粒度。
- **R3 契约块在文件尾而非语义节旁**:7 个 agent 的标记贴不到现成节
  (三要素散在规则列表里),尾部追加块是最小 additive 形态;#494 扩写时
  可原地长,不欠结构债。
- **R4 pre-commit 头注释手写门列**:bash 无法从 GATES 派生 — 用测试钉
  住字符串,漂移即红(机械回验)。
- **R5 devkit/docs 门数叙述未动**:quality_gates.md 的 "4-Gate 框架"是
  #463 框架史(Gate 5 亦未入文档)— 统一治理是 #446 领地,本件只修
  任务点名的三载体,防 scope creep。
