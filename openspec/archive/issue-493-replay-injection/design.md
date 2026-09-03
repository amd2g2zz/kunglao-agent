# Design: ghidra-light 重演注入测试 (#493)

## Context

执法面(注入的对象,均已合入 dev):

- `devkit/subagent_review.py` — Gate 5:staged 触域路径
  (scripts/ hooks/ docs/ tests/ references/ skills/)必须有
  `.subagent-review/*.json`,五字段齐 + verified_by 不自签 + tools_used
  非空;否则 HARD_PAUSE(rc=2)。
- `hooks/dispatch_gate.py` — PreToolUse on Agent:`_capability_guard`
  (#496)读 #495 三产物中的 `validated_capability` 能力卡,派发声明工具族
  与卡上工具族不相交且无 `capability-disproof:` 标记 → REJECT(exit 2)。
- `agents/ghidra-light.md`(#494)— three-point check:`ls scripts/re` /
  grep `tools/_INDEX.yaml` / `references/re-library/`;自造禁令。
- `tools/_INDEX.yaml` — 注册工具名库(kebab-case 逻辑名,validate_index.py
  校验)。

关键事实:`scripts/re/` 是**工作区**命名空间(per-engagement 部署),skill
仓库内不存在;仓库内的真实工具面 = `tools/<category>/*` + `scripts/*.py` +
`references/*`。既有 review JSON 已用 `tools/_INDEX.yaml#subagent-review`
锚点后缀约定。

## Goals / Non-Goals

Goals:

- 三注入场景各 ≥1 项测试,重演 100% kill;
- Gate 5 增 tools_used 可解析性校验,错误信息可行动(给出三合法类);
- dispatch 层交叉断言对 ghidra/decompile 族生效(真打,非仅 frida/xposed
  轨迹的复述)。

Non-Goals:

- **不按 staged 文件名嗅探自造工具**(逐字拟合 = 过拟合风险,计划风险表
  明确缓解)。Gate 5 判 review 契约;自造**文件** + 合法 review 属 reviewer
  职责,不属本门 — 场景④ 有测试钉住该边界(incident 文件名 + 合法 review
  → 放行)。
- 不改 `_staged_files` / DOMAIN_PREFIXES / SELF_VERIFIERS 语义(既有
  test_subagent_review.py 原样全绿)。
- 不新增第五决策面;不动 Gate 6 / 三产物门 / TYPE_E 判死门。

## Decisions

### D1: 行为等价类,而非逐字回放

场景① 保留事故文件名作历史锚,但检测类 = "触域路径新增 + 无 review";
等价类变体(任意新 scripts/ 文件名)同样 rc=2。场景③ 检测类 =
"tools_used 引用不可解析路径",参数化覆盖事故拼写之外的变体(新造名 /
bare 未注册名 / traversal)。

### D2: 可解析性的合法类(白名单域)

1. `scripts/re/**` 前缀 — 工作区 RE 工具命名空间(仓库内不可枚举,前缀
   信任;`agents/*.md` three-point check 第 1 点的落点);
2. bare 逻辑名 ∈ `tools/_INDEX.yaml` 注册名(`ghidra-decompile-functions`
   类);
3. `scripts/` / `tools/` / `references/` 根下**现实存在**的文件,`#anchor`
   后缀剥离后判存在。`references/` 域为硬约束白名单成员(合法 review 引用
   过 `references/_INDEX.md` 类)。

拒绝:`..` 段(traversal)、空路径段(含尾斜杠/双斜杠)、锚点单独出现、
白名单域之外的路径、绝对路径(leading `/` 即空段)。tools_used 非数组 →
显式 fail-closed(schema 说 Array,字符串/标量不是合法 citation 载体)。

### D3: fail-closed(向严)方向 — 更严,不更松

`tools/_INDEX.yaml` 缺失/坏 YAML → 注册名集 = 空 → bare 名一律不可解析
(收紧,不放松)。可解析性在 `_validate_one` 内执行 → 自动继承 `check()`
的 "任一 review 失败即拦"(场景④ 的 mask 测试钉住:合法 sibling 不能
掩盖坏引用)。

### D4: dispatch 层为"真打"(subprocess)

复用 `tests/test_decision_teeth.py` 的 `_run_gate` 形状(payload 含
cwd/workspace,激活 `.hook_state.json`),能力卡族从 frida/xposed 换成
ghidra/decompile:

- 卡记 "ghidra headless decompile …" + 派发
  `[T1 tools=ghidra-decompile-functions]` → rc=0(族在手的交叉断言);
- 卡记 "x64dbg …" + 派发 ghidra 族(无标记)→ rc=2 + `REJECT capability`
  + stdout 指引 `capability-disproof`;
- 同切换 + `capability-disproof: x64dbg (…)` → rc=0。

证明 #496 guard 的工具族交叉断言对 ghidra/decompile 同样生效(词汇表
`_TOOL_FAMILY_BY_TOKEN` 的 ghidra/x64dbg 条目真被消费)。

### D5: 不放松既有 Gate 5 测试

- `tests/test_subagent_review.py` fixture(`scripts/re/pseudo_c_extractor.py`
  命名空间、真实 `scripts/kunglao.py`、`scripts/re/x.py`)全在合法类内;
  快检两文件同跑,全绿。
- 真实仓库 pin:已跟踪 gate5 review 的三条引用、`_INDEX.yaml` 五个 ghidra
  注册名、`references/_INDEX.md`、`scripts/kunglao.py` 对真实检出可解析;
  事故路径(`scripts/decompile_funcs_headless.py` /
  `scripts/ghidra/DecompileFuncs.java`)对真实检出**不可**解析(真 java 在
  `tools/ghidra/DecompileFunctions.java` — 拼写即行为类)。防止 `_INDEX.yaml`
  改名/移动悄悄弄坏合法 review。

## Risks / Trade-offs

- **白名单过紧误伤**:review 若引 `devkit/` 等域外路径会被拦 → 属预期
  收紧;修法是引合法类,或把该 CLI 注册进 `tools/_INDEX.yaml`(与 #494
  "缺失能力上游化,不落地 workspace 脚本" 同一纪律)。
- **dispatch 子进程测试较慢**(3 × ~2s):可接受 — 真打优先,seam 已由
  test_decision_teeth 覆盖,本件补的是 ghidra 族的行为回放。
- **误把合法 workspace 前缀当自造**:`scripts/re/` 前缀信任是必要放宽
  (仓库内不可枚举部署集);滥用面 = 在 review 里编 `scripts/re/` 假名 —
  该风险由 reviewer 独立核验(verified_by 链)承担,Gate 5 不重复造枚举。
