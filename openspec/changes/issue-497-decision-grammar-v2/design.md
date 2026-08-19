# Design — 决策语法 v2 (#497)

## 问题边界

"决策语法" = orchestrator 输出文本层的行为门禁词汇表:问句门(Type A/B)已
存在,本变更补齐**陈述句门**(判死宣告 / 计划搁浅)并校准硬错误路由。执法
表面仍是 `scripts/ask_for_direction_gate.py`(orchestrator 打印后的文本)+
三态宪法(单源);plan 侧是 `scripts/plan_drift_detector.py` 的语义翻转
(形式一致 → 新证据后未重推导)。

**不是**本变更(范围外):

- 不做语义级 NLU — 判死/搁浅的 zh+en 模式列表是 tripwire(非穷尽),承重
  判据在结构化证据(梯耗尽标记 / obstacle claim 状态 / 事件流),符合
  #447 声明优先于推断教义;
- 不接入真实工具调用遥测 — plan-stall 的"N 轮无动作"以 self_redirects
  事件流为唯一轮次源(gate 自身记账),不读 hook/heartbeat 状态;
- 不改 `failure_analysis_gate.py` — 梯耗尽标记**只消费** #495 已落地字段
  (`candidates` / `promotion_attempts` / `origin: failure-obstacle` /
  `outcome`),不造新词汇、不加新记录路径;
- 不改 drift 既有 6 类的退出码语义(ORPHAN_CLAIM 等仍 rc=1/rc=2);
- 不新增第六决策面 — charter 表仍是唯一引用源,新类型(Type E / plan-stall)
  作为表内新行登记。

## D1. 宪法校准 v2 — TYPE_D blocker tripwire 拆组 + 梯耗尽前置

TYPE_D 模式拆成两组(动机:identity/scope 是 orchestrator 无法自解的
歧义,维持 must-ask;blocker 类在授权边界内,走梯是自解路径):

```python
TYPE_D_PATTERNS        # identity ambiguity + scope change — 原样,无条件 HARD_PAUSE
TYPE_D_BLOCKER_PATTERNS  # r"\b(?:new\s+hard\s+error|new\s+blocker|encountered\s+blocker)\b"
```

梯耗尽标记(ladder-exhausted marker,只用 #495 已落地字段):

```python
def find_ladder_exhaustion(workspace) -> list[str]:
    # analyses/failure-<C-NN>.yaml 存在 且 entry["candidates"] 为空
    # 且 对应 claim-register claim 的 promotion_attempts >= 3
```

语义:lessons 梯级跑过(`method_ladder_query` 留痕)但 `candidates` 为空 =
机械梯级已无候选;`promotion_attempts >= 3` = 已有三次不同尝试失败。
两者同时成立 = "工具/资源耗尽(梯爬完)"的机械等价结构 → 保留 must-ask
(HARD_PAUSE rc=2);任一不成立 → 降级 rc=1,指引文本要求先走
method-ladder / env-ladder(`failure_analysis_gate --record`),走梯后复评。

判定顺序(check() 内):Type S → Type D(identity/scope)→ Type D blocker
(有梯耗尽 rc=2 / 无 rc=1)→ Type E → plan-stall → Type A/B。

## D2. TYPE E 判死门(陈述句)

tripwire(zh+en,非穷尽):`走不通` / `行不通` / `此路不通` / `无法继续` /
`卡死` / `dead end` / `cannot proceed` / `no viable path`。

证据判据(合法终局的充要机械等价,两路任一):

- **障碍 REFUTED**:#495 升格 obstacle claim(`origin: failure-obstacle`)
  的 status 为 REFUTED;
- **能力证伪**:`analyses/failure-*.yaml` 的 `outcome` 为 REFUTED。

无证据 → rc=1,强制走梯复评(指引:记录 failure_analysis 三产物 / 出示
obstacle claim 终局),不得作为终局;有证据 → 放行(fall-through 到
Type A/B,干净则 rc=0)。fail-closed:文件缺失/不可读 = 无证据 = 拦。

## D3. plan-stall 检测(陈述句,Type B 等价)

tripwire:`下一步[:：]` / `next step[:：]`(带冒号 — 计划文件标题
"## next step" 与自然语句"下一步是"不触发,零回归锚点:
`test_wait_user_decision_rejected` 的 "let me know next step" 无冒号)。

轮次窗口机制(self_redirects.jsonl 事件流,gate 自身记账):

- 文本含声明 → 追加 `plan-stall-decl:` 事件(声明本身不是违规,不计数);
- 文本**不含**声明但含动作标记(派发/dispatch/spawn/running/uv run/
  python 等执行叙事)→ 追加 `tool-action:` 事件(清窗证据);
- 声明时判滞:`tool-action:` 事件流中无 ts 晚于上一次 `plan-stall-decl:`
  的事件 → rc=1(Type B 等价,指引"执行该下一步或声明阻塞原因"),
  追加 `plan-stall:` 违规事件;有 → 该声明已被执行前置清窗,fall-through。

设计取舍:动作证据只认"无声明文本里的动作标记"——含声明的文本里的动词是
意图叙事("下一步: dispatch C-2")不是执行,同文本自清会杀死检测器。
3-strike 计数器过滤非违规前缀(`tool-action:` / `plan-stall-decl:`),
动作事件不污染既有 HARD_PAUSE 语义(回归测试守护)。

## D4. drift 语义翻转 + 白名单文本

`plan_drift_detector` 新增第 7 类 **STALE_PLAN_ON_NEW_EVIDENCE**(WARN 级):

- 判据(plan mtime 为锚,纯观察):`analyses/failure-*.yaml` 任一 mtime 晚于
  plan mtime(新失败分析落地而计划未重推导);或 claim-register 含
  `origin: failure-obstacle` claim 且 register mtime 晚于 plan mtime
  (新障碍升格落地而计划未重推导);
- **WARN 不计入退出码**:仅硬漂移决定 rc(1/2),WARN-only 输出
  `WARN (observe-only)` 并返回 0 — 先观察级,不 HARD(issue #497 原文);
  硬漂移与 WARN 并存时两者都打印,rc 由硬漂移决定;
- 不受 `plan_refers_to_register` 命名空间守卫约束(证据比计划新是
  命名空间无关的事实),既有 6 类守卫原样。

白名单文本(两载体同步,additive):

- `rules/kunglao-convergence-loop.md` 硬禁止#4:触发清单加第 4 项
  "新能力/障碍事实落地(#495 三产物)";"不因单失败重规划"细化为
  "不因无新信息的转向重规划";
- `skills/kunglao-agent/SKILL.md` Hard prohibitions #4:同样加 (d) 项
  与措辞细化(英文载体,同义)。

## D5. 验收映射(负例 = 行为等价类,非逐字重演)

| 负例 | 测试 | 断言 |
|---|---|---|
| (a) 轨迹1:瞬态失败×2 + "这条路走不通"无证据 | `test_trajectory1_*` / `TestTypeE` | rc=1(走梯复评指引) |
| (b) 轨迹2:"下一步: X" 后无动作 | `test_trajectory2_*` / `TestPlanStall` | rc=1(Type B 等价指引) |
| (c) 有障碍 REFUTED 证据的判死 | `TestTypeE.*allowed*` | rc=0(合法终局) |
| (d) blocker 宣告无梯耗尽 | `TestTypeDBlocker.*degrades*` | rc=1(降级指引,非 HARD) |
| 梯耗尽 blocker | `...hard_pauses` | rc=2(must-ask 保留) |
| WARN-only drift | `test_plan_drift_stale_plan.py` | rc=0 + WARN 文本 |

既有零回归:`test_ask_for_direction_charter.py`(Type A/B/C/D/S 全部)、
`test_v1_8_enforcement_gates.py` ask_for_direction 四例、
`test_plan_drift_unverified.py` 全部 — 不改语义,只有 TYPE_D blocker 组
触发条件收紧(其既有用例文本同时命中 scope 组,期望 rc=2 不变)。

## R1-R6(风险与不做)

- **R1 过拟合叙事**:负例取行为等价类(判死语法族 zh+en 参数化 / 停滞
  语义窗口),不逐字匹配 issue 叙事 — 对应 plan 风险行"双轨迹重演测试
  过度拟合叙事细节"。
- **R2 tripwire 漏召回**:模式列表非穷尽是教义(任何语言都不可穷尽);
  承重判据是结构化证据检查,漏召回由 LLM 语义兜底闭环(charter 检测教义)。
- **R3 "卡死"宽匹配**:界面卡死等非判死语境会命中 tripwire — 但承重判据
  是证据检查,无证据一律走梯复评,误拦代价 = 多走一次梯(便宜),漏拦
  代价 = 任务安静死亡(贵),不对称下取高召回。
- **R4 mtime 粒度**:文件系统 mtime 在同秒写入时可能相等 — 判据用严格
  大于,相等视为"计划已见过该证据"(fail-open 到不警告)。
- **R5 事件流污染**:动作/声明事件与违规事件同文件 — 计数器按前缀过滤,
  回归测试守护 3-strike 语义不变。
- **R6 第六决策面**:所有新行为回写 charter 表(新两行 + Type E 字母 +
  变更记录),执行器行更新;不另立决策文本。
