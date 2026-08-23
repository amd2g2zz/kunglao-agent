# Design — issue-446-governance-fg

## D1. doc-sync 门挂哪里:GATES 注册(Gate 7),不是独立 devkit 检查

备选:(a) 独立 `devkit/doc_sync.py` 由 CI 单独调用;(b) 注册进
`quality_gates.py` GATES 作 Gate 7。

选 (b)。理由:
- 漂移面是 commit-facing 的(hook 模板、pre-commit 链、CI workflow
  注释)— 挂进 GATES 后 pre-commit `1 3 4 5 6 7` 与 CI
  `quality_gates.py` 调用点自动携带,零新增调用方;
- GATES 注册免费获得三件事:`test_gate_registry_lockstep_with_gate_
  functions`(#492)的注册↔实现锁步、docstring 门名锁步、argparse
  choices 校验;
- 独立调用意味着又一个新的"要知道去跑"的机制 — 正是 #446 批判的
  加法方向。

注册模式逐字镜像 Gate 6(`_gate7_doc_sync` + `GATES[7] = ("Doc Sync",
...)` + docstring 门语义段 + pre-commit 模板门列表),reviewer 可用
`git show 4c259cc` 对照 #492 的同类 diff。

## D2. 扫描面:devkit/** + .github/workflows/**,不含 scripts/ 与 hooks/

计数声明正则(大小写不敏感):`数字 + [空格/连字符] + gate(s)/门`。
全仓试扫(2026-08-20,本 worktree)证明面选择是经验问题:

- 面内命中全部为真漂移(实测 21 行,含评论区清单 6 处中未被 #492
  先修的余量 + CI workflow 3 处新发现);
- 面外若纳入 scripts/hooks/tests 会大量误伤**另一个计数族**:产品
  enforcement gates(`10 gates`、`7 gate scripts`)、版本号
  (`v1.8.3 gates`)、ID 后缀(`DIFF-1 gate`、`Phase 0 gate`)。
  这些与 devkit 质量门注册表无关,纳入即制造噪声门。

结论:扫描面 = 质量门家族的文档载体(devkit/** 全部文本文件 +
`.github/workflows/**`)。scripts/hooks 的 gate 计数属产品机制总账
(issue #446 验收第一条 mechanisms.md)领地,不在本门范围。

## D3. 语义:任何数字计数声明 = 违规(不只是"与 len(GATES) 不符")

两个备选:(a) 数字 ≠ len(GATES) 才违规;(b) 数字计数声明一律违规,
要求 number-free 措辞(指向 GATES 注册表)。

选 (b)。理由:评论区 G 类原则是**派生不复制** — 即使今天写对
"6-gate",注册 Gate 8 的 PR 就把它变成新漂移;#492 的
`test_quality_gates_docstring_no_stale_gate_count` 已经证明"追着
stale 数字修"是打地鼠(它的 canary 列表硬编码 "4",永远只认旧错)。
number-free 措辞("质量门框架,门数见 GATES 注册表")一次修复、
永久免疫。GATES 的 len 只出现在违规提示信息里(告知当前真值),
不参与判定 — 判定与注册表解耦,注册表 import 失败时扫描照常 fail。

## D4. references 重钉检测读 staged 内容,不是磁盘内容

评论区第 7 活例有两种失效形态:(i) md staged、yaml 没 staged;
(ii) 两者都 staged,但 md 又改过、yaml pin 是旧的。只查 staged 文件
清单能拦 (i),拦不住 (ii)。本门用 `git show :<path>` 取 **staged
字节**算 sha,与 staged `_INDEX.yaml` 的 `files:` 块比对:

- md staged 而 yaml 未 staged → HARD_PAUSE(rc=2,镜像 Gate 5 语义);
- 新 references/*.md 无对应 pin → HARD_PAUSE;
- staged sha ≠ staged pin → HARD_PAUSE;
- 提示语直接给修复命令 `uv run python scripts/re_pin_references.py`。

`files:` 块用文本解析(镜像 re_pin_references.py 的行级解析,不引
yaml 依赖 — devkit 现有模块全部 stdlib-only,保持一致)。git 调用
失败 → 视为无 staged(N/A 放行,镜像 subagent_review._staged_files
的失败语义;此路径由调用方 quality_gates 的异常兜底二次覆盖)。
archive/ 下的 md 不在 pin 义务内(镜像
test_references_index_pins_all_reference_files 的豁免)。

## D5. 新机制登记 = WARN 不是 FAIL

三件套(code + reference + _INDEX 行)对**staged 新增**
(`--diff-filter=A`)的 scripts/*.py 检查 stem 是否出现在
`references/_INDEX.md`。WARN 不阻断,理由:存量 scripts/ 有大量未
登记文件(既有债),FAIL 会立刻把仓库锁死;强登记的硬门随
mechanisms.md 总账(issue 验收第一条)落地,本 WARN 是它的前哨
信号 — 先可见,后强制。

## D6. F 类锚:符号锚(状态词表),不是行号

issue #446 验收第二条明言"行号引用清零或替换为**符号引用**"。
因此 error_response.py 侧新增:

```python
CHARTER_SOURCE = "references/agent-three-state-charter.md"
CHARTER_STATES = ("allowed", "must-ask", "must-stop")
```

charter 侧执行器表加一行:declares `scripts/error_response.py`
`_CHARTER_STATE` 为三态表的派生列(值域 = 本表三态)。锁步测试
`tests/test_decision_surface_anchor.py` 断言:
1. `_CHARTER_STATE` 每个值的引导 token ∈ `CHARTER_STATES`;
2. charter 文本含三个状态词 + 提到 error_response.py(互指存在);
3. error_response.py 源文本提到 charter 文件名(互指存在);
4. taxonomy 文档含每个 ErrorClass 值(UNCLASSIFIED ↔ 未分类)且提到
   error_response.py;代码提到 taxonomy 文件名。

活性单源同理不合并(见 D7),只产出台账。

## D7. 活性单源:仅台账(合并延后)

4 处 worker 活性表示(file:line,2026-08-20 实测):

| # | 表示 | 写入方 / 权威点 | 消费方 |
|---|---|---|---|
| 1 | `runs/worker-status-*.md` | worker 写;单点解析在 `hooks/lib_kunglao.py`(#444 声明,`scripts/lib_kunglao.py:24-28` 按路径加载同文件,无第二解析) | `scripts/convergence_check.py:93,140`(_scan_active_workers)、`heartbeat_tick` reconcile |
| 2 | `analysis_state.txt` `[active_workers]` | `scripts/heartbeat_tick.py:18`(reconcile 重建,zombie 自愈)+ `scripts/hook_activation.py:656`(--reconcile,GROUND TRUTH = worktree status files) | `worker_budget` ≤3 并发门 |
| 3 | `runs/.heartbeat.json` | `scripts/heartbeat.py:35,47`(register)、`:93-96`(alive 判定,35min 窗) | `hooks/worker_budget.py:1349,1549`(check_heartbeat_alive,dispatch 拒绝) |
| 4 | `runs/.convergence_ledger.jsonl` | `scripts/convergence_check.py:214`(LEDGER_NAME)+ `scripts/lib_kunglao.py:46`(LEDGER_FILE) | `convergence_health.py`(HEALTHY/STALLED/SPINNING)、`worker_budget` STALLED/SPINNING 拒绝 |

现状评估:#1 已单源(#444 修);#2 是 #1 的**派生物**(reconcile 从
status files 重建 = 派生而非复制);#3/#4 是正交事实(心跳活性 ≠
收敛轨迹),非同义冗余。真正的合并候选是"#2 的冗余条目清理 +
#1/#2/#4 的快照一致性校验" — 属 #498 决策循环一体化的收尾面,单独
PR 处理;本 PR 只交付本台账(design 即账)。

## D8. 风险

| Risk | L | I | 缓解 |
|---|---|---|---|
| 扫描正则误伤合法数字(gitignore 外的新文件类型) | M | L | 面限 devkit/+workflows;正则要求 digit-gate 邻接;violations 带 file:line 可即时核 |
| staged-content 检测在非 git 环境(pre-commit 之外手动跑)误放行 | L | L | 与 Gate 5 同语义(N/A);tests 用隔离 git 仓覆盖真 staged 路径 |
| WARN 被当噪声忽略,三件套退化为装饰 | M | M | WARN 文本指明登记动作与 mechanisms.md 总账的关系;总账硬门在 #498 收尾面接手 |
| 锚测试过拟合当前文本措辞 | M | M | 断言只查符号存在(文件名/状态词/类名),不断言整句 |
| 门列表 "1 3 4 5 6 7" 本身是下一个漂移点 | M | M | test_doc_sync 断言模板门列表 == GATES-{2}(注册表派生);Gate 8 落地时该测试强制同步 |
| 编辑 references/ 触发本门自身 HARD_PAUSE(自食) | L | L | 本 PR 的 references 编辑全部走 re_pin_references.py 重钉后同 staged(即门的第一次实战) |
