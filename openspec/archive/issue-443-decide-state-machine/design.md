# Design — decide() 一等状态机 (#443)

## 0. 范围与不变量(最高约束)

**本变更只重组判定组织方式。** 每个 gate 的语义、每个分支的 action 文本、
输出 dict 的字段集合、exit code 语义全部逐字节不变。唯一合法的 diff 形态:
elif 链 → 表驱动。回归锚定(design §5)在哈希级证明这一点。

## 1. 为什么是 (State, Event) 转移表而不是"有序谓词表"

issue 设计方向给了两个可选形态:(a) 有序谓词表(gate → verdict 行表,
first-match-wins);(b) 显式状态枚举 + `TRANSITIONS: dict[(State, Event),
(State, Action)]`。选 **(b)**,理由:

1. 决策矩阵有真实的两段结构——先分诊(schema / 收尾事务 / 调度),再在
   段内排序。特判堆的嵌套(`elif not opens and not partials:` 里再套
   5 层)证明这不是平面优先级问题;(a) 需要 token 化优先级或嵌套表才能
   表达,等于把控制流换了个皮。
2. 终态 = verdict 本身(State.INVALID/CONVERGED/DISPATCH/...),
   `(decision, exit_code)` 由 `VERDICTS[终态]` 查表得出——decision
   字符串与 exit code 的绑定从"每分支手写三处"变为单一映射,新增 verdict
   忘改 exit code 的错型结构性消失。
3. 阶段(stage)是可测试单元:STAGE_PROBES 声明每阶段的探测序,catch-all
   尾事件(DRAIN_CLEAN / UNEXPECTED_STATE / DRAINED)使"任意快照必达
   终态"成为可断言的表性质,而非通读控制流的推演。

## 2. 数据结构(全部为模块级声明数据)

```python
class State(str, Enum):        # 3 评估阶段 + 6 终态
    SCHEMA, DRAIN, SCHEDULE    # 阶段
    INVALID, CONVERGED, DISPATCH, DISPATCH_VERIFIER, SATURATED, BLOCKED  # 终态

class Event(str, Enum):        # 词汇来源全部为已落地概念,零新造
    # SCHEMA 段
    SCHEMA_INVALID             # #77 malformed primary_questions
    WORK_PENDING / DRAINED     # opens/partials 非空与否(互补,穷尽)
    # DRAIN 段(opens==0 且 partials==0,完成事务,序 = 历史事故序)
    ORPHAN_TERMINAL_CLAIM      # M2 完整性
    PRIMARY_Q_UNVERIFIED       # M2 BLIND-verified PROVEN, not STAMP
    NOTE_LAYER_GAP             # DESIGN S8 C0
    DISCOVERY_UNCONSUMED       # #147 发现消费
    GLOBAL_CONTRADICTION       # #147 完成事务
    DRAIN_CLEAN                # DRAIN 段 catch-all
    # SCHEDULE 段(有活,能不能现在派)
    WORK_AND_FREE_SLOT         # → DISPATCH
    PARTIALS_AND_FREE_SLOT     # → DISPATCH_VERIFIER
    WORK_NO_FREE_SLOT          # → SATURATED(poll)
    FAILURE_ARTIFACTS_DUE      # #495: 失败尝试缺三产物分析
    LADDER_REQUIRED_BLOCKER    # #497: 梯未耗尽的 blocker(爬梯)
    LADDER_EXHAUSTED_BLOCKER   # #497: 梯耗尽标记(find_ladder_exhaustion)
    UNEXPECTED_STATE           # SCHEDULE 段 catch-all

VERDICTS: dict[State, tuple[str, int]]     # 终态 → (decision, exit_code)
STAGE_PROBES: dict[State, list[Event]]     # 每阶段探测序(顺序即优先级,在数据里)
_EVENT_PREDICATES: dict[Event, Callable]   # 事件 → 快照谓词
TRANSITIONS: dict[(State, Event), (State, Callable)]  # 转移 + action 构造器
```

机器驱动(`_run_machine`): 从 SCHEMA 起,按 `STAGE_PROBES[state]` 顺序取
第一个谓词为真的 Event,查 `TRANSITIONS` 转移;落在 VERDICTS 终态即执行
该行的 action 构造器返回。步数上限 + 无转移行 fail-closed → 老链的
`else: SATURATED "Unexpected state"` 兜底(逐字节同文)。

### 2.1 老分支 → 新转移的等价映射(逐行对账)

| 老链顺序 | 转移行 | action 文本 |
|---|---|---|
| `if pq_error` | (SCHEMA, SCHEMA_INVALID)→(INVALID, …) | 逐字节同 |
| `elif not opens and not partials:` | (SCHEMA, DRAINED)→(DRAIN, noop) | — |
| ├ `if orphans` | (DRAIN, ORPHAN_TERMINAL_CLAIM)→(BLOCKED, …) | 同 |
| ├ `elif unverified_pqs` | (DRAIN, PRIMARY_Q_UNVERIFIED)→(SATURATED, …) | 同 |
| ├ `elif pq_note_gaps` | (DRAIN, NOTE_LAYER_GAP)→(DISPATCH_VERIFIER, …) | 同 |
| ├ `if discovery_reason` | (DRAIN, DISCOVERY_UNCONSUMED)→(DISPATCH, …) | 同 |
| ├ `if contradiction_reason` | (DRAIN, GLOBAL_CONTRADICTION)→(BLOCKED, …) | 同 |
| └ `else` | (DRAIN, DRAIN_CLEAN)→(CONVERGED, …) | 同 |
| `elif unblocked_open and free_slots` | (SCHEDULE, WORK_AND_FREE_SLOT)→(DISPATCH, …) | 同 |
| `elif partials and free_slots` | (SCHEDULE, PARTIALS_AND_FREE_SLOT)→(DISPATCH_VERIFIER, …) | 同 |
| `elif unblocked_open and not free_slots` | (SCHEDULE, WORK_NO_FREE_SLOT)→(SATURATED, …) | 同 |
| `elif failure_blocked_open` | (SCHEDULE, FAILURE_ARTIFACTS_DUE)→(BLOCKED, …) | 同 |
| `elif opens and not unblocked_open` | (SCHEDULE, LADDER_*_BLOCKER)→(BLOCKED, …) | 同 |
| `else` | (SCHEDULE, UNEXPECTED_STATE)→(SATURATED, …) / 驱动兜底 | 同 |

SCHEMA/WORK_PENDING→SCHEDULE 的转移行存在但无 action(纯分段)。
注意老链 `else`(Unexpected state)实际可达:opens==0、partials>0、
free_slots==0——锚定矩阵有专项 case 钉住。

## 3. 事件词汇的消费点(不造新词汇)

- **FAILURE_ARTIFACTS_DUE(#495)**: 谓词 = `_failure_blocked()` 非空,
  即 `failure_analysis_gate.scan_workspace` 判 BLOCKED 的 claim——
  #495 收紧后其语义就是"失败尝试的分析缺 `validated_capability` /
  `identified_obstacle`(missing_artifacts)或未覆盖最新尝试"。本变更
  零改动地继承该语义(#495 proposal: "它们消费 scan_workspace,语义
  自动传播")。
- **LADDER_REQUIRED_BLOCKER / LADDER_EXHAUSTED_BLOCKER(#497)**: 老链
  的 `opens and not unblocked_open` 单分支,按 #497 的 blocker 二分
  词汇拆成两个事件——探测时调
  `ask_for_direction_gate.find_ladder_exhaustion(workspace)`(#497 落地
  的梯耗尽标记:promotion_attempts>=3 且 method-ladder candidates 为空):
  命中 → LADDER_EXHAUSTED_BLOCKER(must-ask 侧),否则
  LADDER_REQUIRED_BLOCKER(爬梯侧)。**两行今天指向同一终态 BLOCKED 与
  同一 action 构造器**——decide() 目前不区分 must-ask 与爬梯(那是
  ask gate 的领地,#497 proposal: "不动 convergence_check");拆事件的
  价值是把 #497 的区分点预置为表结构:未来要分叉 = 改一行转移行,
  不是插 elif。加载失败 fail-open 归 LADDER_REQUIRED_BLOCKER(标签
  无行为后果,两 flavor 同 verdict)。
- 惰性求值保留: discovery/contradiction 扫描仍只在 DRAIN 段到达时算
  (快照对象上的 cached method),梯标记只在 SCHEDULE 段 blocker 探测时
  算——与老链的成本剖面一致,输出无差。

## 4. decide() 的新形态

```python
def decide(workspace: Path) -> dict:
    snap = _decide_inputs(workspace)          # 显式状态对象(原散落局部变量)
    state, action = _run_machine(snap)        # 查表执行,零 elif
    decision, exit_code = VERDICTS[state]
    return { ...字段、字段名、顺序与老版完全一致... }
```

- `_decide_inputs` 收编老版开头的全部快照计算(reg/task_spec/opens/
  partials/workers/blockers/failure_blocked/orphans/unverified/note
  gaps/blocked 派生)——纯读取,顺序与老版一致。
- 输出 dict 键集合不变(schema `convergence-check-output.json` 顶层
  `additionalProperties: true`,且本变更不加新键——锚定要求哈希级相等)。
- 调用方兼容(全仓 grep 实证): `main()`(全 dict + `_human` +
  ledger)、`kunglao-decide.decide()`(子集字段)、`kunglao.py
  cmd_decide`、`worker_pulse`(子进程 --json + exit code);
  external_kicker 不直接调 decide(读 ledger)。

## 5. 回归锚定策略(硬验收,写进测试)

**双通道锚**,均落在 `tests/test_decide_regression_anchor.py`:

1. **冻结快照通道(永久)**: `tests/decide_anchor_c5cb1ae.json` —
   ~30 case 输入矩阵 × c5cb1ae 基线 decide() 的完整输出,机器生成
   (生成命令见下),测试断言重构后 decide() 对同 case 输出逐字段相等
   (JSON 规范化后比较)。git 历史被裁剪后依然有效。
2. **活基线通道(更强,maker-checker)**: 测试内
   `git show c5cb1ae:scripts/convergence_check.py` 提取老版到 tmp,
   同目录复制 `hooks/lib_kunglao.py`(满足其 `__file__` 相对定位),
   importlib 唯一名加载 → 同一 fixture 工作区上并行运行老版与新版
   decide(),完整 dict 相等。历史不可用时 skip(通道 1 仍在)。

**矩阵设计**(输入 → 期望输出全部由通道 2 现场推导,非手写):
- 每分支至少 1 case(13 分支 + INVALID + 兜底);
- gate 交织 / 优先级序 case(schema 压过 dispatch、orphan 压过
  unverified、queue 压过 failure、opens 压过 partials、note-gap 压过
  discovery、discovery 压过 contradiction、failure 压过 all-blocked);
- #495/#497 新语义交织(三产物部分缺失仍 BLOCKED / 完整放行 DISPATCH /
  梯耗尽 unblocked 仍 DISPATCH / 梯耗尽 blocked 走 BLOCKED);
- 确定性边界: worker-status 文件全部新写(mtime 新鲜,stuck 必空),
  排除 age_min 时间漂移;多文件列表依赖 NTFS 枚举序(仓库既有测试同
  前提)。

**冻结快照生成命令**(reviewer 可重放;产物必须由 c5cb1ae 基线产生,
不得由新代码产生——maker-checker):

```bash
cd D:/works/kunglao-wt/443 && uv run python - <<'EOF'
import importlib.util, json
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "anchor_mod", "tests/test_decide_regression_anchor.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
Path("tests/decide_anchor_c5cb1ae.json").write_text(
    json.dumps(m.capture_from_git_baseline(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8")
EOF
```

## 6. invariant 测试(design §1 的表性质)

| 不变量 | 断言 |
|---|---|
| 表完整性 | 每个 (stage, probe-event) 对都有 TRANSITIONS 行 |
| 谓词全覆盖 | STAGE_PROBES 引用的事件 ⊆ _EVENT_PREDICATES,且无孤儿谓词 |
| catch-all 尾 | 每阶段探测表末事件在全空与全满快照下恒真 |
| 穷尽性 | 机器对矩阵内任意快照 ≤ 上限步数内落在 VERDICTS 终态 |
| 终态映射 | VERDICTS 键 == 6 终态;decision/exit_code 与 EXIT_* 常量一致 |
| 零 elif 元守卫 | `inspect.getsource(decide)` 不含 "elif"(防回潮) |
| 双梯同判 | LADDER_* 两事件指向同终态同 action 构造器(#497 seam 文档化) |
| 确定性 | 同 case 两次运行输出相等 |

## 7. Rejected

- **R1 动 gate 语义 / action 文案**: 违反 issue 范围声明;锚定直接红。
- **R2 新增输出字段**(如透出 ladder_exhausted 诊断): 破坏哈希级锚定;
  W-15 式诊断字段加键是 #444 的先例,但本 issue 的验收就是输出全等,
  加键留给后续 issue。
- **R3 有序谓词表代替状态机**: 见 §1,嵌套分诊表达不了。
- **R4 把状态机抽成新文件**(scripts/decide_machine.py): issue 证据 2
  的 grep 锚定 `scripts/convergence_check.py`;单文件内聚,且避免新
  import 面(kunglao-decide/worker_pulse 的加载路径不变)。
- **R5 在 decide() 内区分 must-ask / 爬梯 verdict**: #497 领地
  (ask gate);本变更只预置事件词汇。
- **R6 全量 pytest 作为本 issue 门**: #369 跨进程锁,泳道快速门
  `-m "not load_sensitive"`;全量门是 PR 前主会话的事(Task 5)。
