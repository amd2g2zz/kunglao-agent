# 治理 F+G 落地 — doc-sync 门 + 决策面机器锚 + 活性台账 (#446)

## Why

Issue #446(D1 治理面)+ 2026-08-19 评论区两条细化:F 类(机制冗余)与
G 类(写作层失守)在本件收编落地。G 类的核心教训是**活体漂移**:同一
门数在 code/docstring/hook 模板/README 四类载体上各自复制,注册第 6 门
(#492)后其余载体仍说 4-gate — #492 修了 quality_gates.py 与 pre-commit
两处,devkit README/docs 与 `.github/workflows/release-check.yml` 的
4-gate 措辞仍在(本件 grep 实测余量 21 行,基点 4bd9102,见 tasks §4)。评论区第 7
活例(2026-08-19):4572c30 编辑 `references/_INDEX.md` 未重钉
`_INDEX.yaml` sha → `test_references_index_pins_all_reference_files` 变红
— `scripts/re_pin_references.py` 已存在但 references/ 的 commit 流程没有
强制调用它。学习系统只有加法(#446 证据 3):lessons 库(#41)存在但
`references/_INDEX.md` 与 SKILL.md 零提及(隐形债);SKILL.md 的 MUST
哪些已生效哪些是愿景,读者无法区分(spec-实现 gap)。

## What Changes

- **G 类 doc-sync 门(Gate 7)**:`devkit/doc_sync.py` 注册进
  `quality_gates.py` GATES(现 6 门 → 7 门),pre-commit 模板
  `1 3 4 5 6` → `1 3 4 5 6 7`(头注释同步)。三个子检查:
  (a) 门数计数声明扫描 — devkit/** 与 .github/workflows/** 面上任何
  "N-gate / N gates / N 门" 数字计数声明 = 违规(派生不复制:门数唯一
  来源是 GATES 注册表;数字措辞一律改 number-free);
  (b) references/ 编辑未重钉检测 — staged 含 references/*.md 而
  `_INDEX.yaml` 未同 staged → HARD_PAUSE;同 staged 但 staged 内容的
  sha 与 staged yaml pins 不符 / 新文件缺 pin → HARD_PAUSE
  (把 re_pin_references.py 纳入 pre-commit 链);
  (c) 机制登记三件套 — staged 新增 scripts/*.py 的 stem 未出现在
  `references/_INDEX.md` → WARN(不阻断;存量未登记是既有债,不回溯)。
- **G 类漂移余量修复**:devkit/README.md、devkit/docs/{README,
  quality_gates,quality_roadmap,unit_test_spec}.md、
  `.github/workflows/release-check.yml` 共 21 行 4-gate 措辞 →
  number-free 措辞(指向 GATES 注册表)。
- **F 类决策面归一(最小化)**:`scripts/error_response.py` 的
  `_CHARTER_STATE` 表与 `references/agent-three-state-charter.md` 三态表
  加**机器锚** — charter 声明 `CHARTER_SOURCE`/`CHARTER_STATES`
  (符号锚:状态词表,非行号 — #446 验收要求行号引用清零),charter
  执行器表加 error_response.py 行;新测试
  `tests/test_decision_surface_anchor.py` 断言两处互指存在 + 值域锁步。
- **F 类活性单源:仅台账**(4 处活性表示的 file:line 清单进本
  design.md §D7;实际合并归 #498 收尾后单独 PR — 避免本 PR 面过大)。
- **lessons 库补文档面**:`references/_INDEX.md` 加 lessons 条目 +
  `skills/kunglao-agent/SKILL.md` 一行 pointer。
- **spec-实现 gap 台账**:`mechanisms-status.md` — SKILL.md 的 MUST
  清单逐条标 implemented/pending(机械 grep 佐证),作为 #442 收尾
  DoD 输入。

## Impact

- **代码**:`devkit/doc_sync.py`(新)、`devkit/quality_gates.py`
  (Gate 7 注册 + docstring 门列表 +1 行)、`devkit/githooks/pre-commit`
  (门列表两处 + 头注释)、`scripts/error_response.py`(锚常量,
  行为零改动)。
- **文档**:devkit 4 个 md + release-check.yml(漂移余量)、
  `references/_INDEX.md`(lessons 行)、
  `references/agent-three-state-charter.md`(执行器表 +1 行)、
  `references/_INDEX.yaml`(重钉)、`skills/kunglao-agent/SKILL.md`
  (+1 行 pointer)。
- **测试**:`tests/test_doc_sync.py`(新)、
  `tests/test_decision_surface_anchor.py`(新)。
- **openspec**:本目录三件套 + `mechanisms-status.md`。
- **不做**:worker 活性 4 处表示的物理合并(#498 后单独 PR);遇阻决策
  面 x5 的全量宪法表重构(本件只锚 error_response ↔ charter 这一对,
  其余互引关系待 #498);行号引用全仓清零(本件不新增行号引用,
  存量清零另立);mechanisms.md 总账本体(issue 验收第一条,挂 #498
  收尾面,本件的 (c) WARN 是它的前哨)。
