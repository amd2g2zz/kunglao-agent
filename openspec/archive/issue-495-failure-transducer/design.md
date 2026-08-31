# Design — failure→knowledge transducer (#495)

## 问题边界

"失败转导" = 一次失败尝试(`promotion_attempts > 0`、非 TERMINAL)在被
re-dispatch 或下 NEGATIVE 结论之前,必须把失败**类型化**为机器可消费的
事实:能力✓(validated_capability)、障碍(identified_obstacle)、下一方法
出处(next_method_source)。转导的落点是 `analyses/failure-<C-NN>.yaml`
(既有协议文件)与 claim-register.yaml / claim_deps.yaml(DAG 生长)。

**不是**本变更(范围外):
- re-library 检索与 WebSearch 错误签名(method-ladder 梯级 2/3)的机械
  执行 — 门只机械跑梯级 1(lessons,已有 `_score_lessons` 接口);梯级
  2/3 由 orchestrator 声明 `--source`,门校验枚举与 novel 前置;
- NEGATIVE 结论的正当性判据(`justified-adequate` 三问语义原样保留);
- facts/ 层另建产物文件(`--lessons` 聚合与 `--reflect` 队列已覆盖回流);
- `priority*.py` 对能力/障碍事实的消费(#496 价值上牙的领地,#499 裁决后)。

## D1. 三产物字段与覆盖判据(analysis 协议 v2)

`record_analysis()` 新增三个 keyword 参数(位置参数兼容):

```python
record_analysis(ws, cid, assumption, validity, next_method,
                outcome=None, what_happened=None,
                validated_capability=None,     # 本次证明了什么能用(能力✓)
                identified_obstacle=None,      # 具体什么挡的(升格触发器)
                source=None,                   # lesson-hit|reference-hit|web-hit|novel-hypothesis
                library=None)                  # 梯级 1 检索库(--library 透传)
```

entry 新键(非空才写,避免给 closure 回填伪造空串):

- `validated_capability` / `identified_obstacle` — 三产物之二(第三产物是
  升格出的 claim 本身);
- `next_method_source` — provenance 归一化( strip().lower() );
- `method_ladder_query` + `candidates` — 梯级 1 留痕(仅失败时记录;
  closure-only 调用保留 prior,与 #41 "closure 不清空失败时记录"同构)。

closure-only 回填(只给 outcome/what_happened)对新字段的保留规则与
assumption/validity/next_method 完全一致:取 prior 值。

`_analysis_covers()` 收紧为三条件(复用既有 BLOCKED 状态机,不加新门):

```python
covers >= attempts                    # 既有:版本覆盖
and str(analysis.get("validated_capability") or "").strip()
and str(analysis.get("identified_obstacle") or "").strip()
```

任一产物缺失 → 不覆盖 → `scan_workspace`/`check_claim` BLOCKED →
`hooks/dispatch_gate._failure_blocked_ids` 拒绝 re-dispatch(#495 验收 1
"失败后未产出三产物 → 不可 re-dispatch(复用现有 BLOCKED 语义)")。
BLOCKED dict 追加 `missing_artifacts` 诊断字段(仅当 analysis 存在),
`_print_blocked` 指引补第 4/5 问与 record 命令样例。

## D2. 障碍升格:claim 生长协议

`_promote_obstacle_claim(ws, claim_id, obstacle, parent_claim)`,
`identified_obstacle` 非空时由 `record_analysis` 在写完 analysis 后调用:

1. **幂等判重**:register 中已有 claim 满足 `obstacle_for == claim_id`
   (与 `origin == "failure-obstacle"` 配对)→ 返回既有 id,`created=False`。
   判重键是**归属标记**而非文本 — 同 claim 重跑、障碍措辞变化都不重复建。
2. **id 分配**:`C-{max+1}`,max 取既有 id 尾部数字的最大值;宽度跟随
   产生 max 的那个 id(C-001 风格 → C-002;C-1 风格 → C-2),保证同寄存器
   风格一致且不碰撞。
3. **新 claim 字段**:
   ```yaml
   - id: C-<n+1>
     status: OPEN
     boundary_type: obstacle
     evidence_tier_attempted: 0
     promotion_attempts: 0
     depends_on: [<失败 claim id>]        # 寄存器内声明(镜像 seed_claims 风格)
     statement: "Obstacle (from C-<k>): <obstacle 截断>"
     origin: failure-obstacle             # 类型标记
     obstacle_for: C-<k>                  # 幂等判重键
     promoted_from: analyses/failure-C-<k>.yaml
     answers_question: <父 claim 有则继承>  # 价值上下文不断链
   ```
   `boundary_type: obstacle` 不受 lint_facts 约束(该门只 lint facts/
   frontmatter);priority 链读 `statement`,不读 title — 故只写 statement。
4. **claim_deps.yaml 写边**:`depends_on[<新id>] = [<失败id>]`(setdefault
   合并,不覆盖既有边;文件缺失则建 `depends_on: {}` 骨架再写)。
   这是 plan_drift_detector MISSING_DEP_LINK / refutation_propagate
   reverse-walk 消费的**权威边存储** — "平铺 DAG 长出节点"的可验证形态。
5. 写回用 `yaml.safe_dump(sort_keys=False)`(refutation_propagate.write_yaml
   同款);register 原样读-改-写,不动无关字段。

失败 claim 终结后(TERMINAL)再 record:升格仍发生(障碍是已买下的信息,
不随父 claim 关闭而蒸发);但 `_needs_analysis` 对 TERMINAL 为 False,父
claim 不再 BLOCKED。

## D3. method-ladder 梯级 1 接线(fail-open)

失败时记录 = (assumption / validity / next_method) 任一显式提供。此时:

```python
query = " ".join(x for x in (identified_obstacle, assumption) if x)  # 错误签名
try:
    candidates = _score_lessons(query, lib)      # 与 --search 同一函数
except Exception:
    candidates = []                              # fail-open:查询失败不阻塞记录
```

- 查询串 = 障碍 + 假设(issue #495 What 4 "错误签名取自 obstacle/assumption
  关键词");`method_ladder_query` 落盘留痕(验收"查询留痕可审计")。
- candidates 命中形如 `_score_lessons` 返回(file/score/outcome/next_method/
  claim_topic),直接进 entry — orchestrator 与 #496 后续消费同形状。
- fail-open 覆盖三类:库目录缺失(`_score_lessons` 天然返回 [])、库文件
  不可读(`_lesson_meta` 已容错)、检索自身异常(try/except 兜底)。
  硬约束:lessons 检索任何失败不得让 record 返回 recorded=False。

## D4. provenance 门

- 归一化:`source.strip().lower()`;合法枚举
  `SOURCE_VALUES = ("lesson-hit", "reference-hit", "web-hit", "novel-hypothesis")`。
- **缺 source**(且 prior 无可继承)→ 拒绝:`--source is required ...`;
  **非法枚举** → 拒绝:`must be one of ...`。拒绝即 recorded=False、不落盘
  (与既有 validity/outcome 校验同构,exit 1)。
- **novel-hypothesis 前置**:本次(或 closure 继承的)candidates 为空 →
  拒绝,理由指明"先查 lessons/reference/web"。机械含义:梯级 1 是门内
  唯一可机械验证的梯级,novel 声明前它必须留下非空痕迹。
  已知边界:空库 + 无命中时 novel 被拒 — 操作者出路是如实声明
  reference-hit/web-hit(梯级 2/3 是声明面)或让库先积累;fail-closed
  是本仓库默认哲学("验不了 → 不许")。

校验顺序:claim 存在 → 三问/prior 合并 → source 归一化+枚举校验 →
梯级 1 检索 → novel 前置 → 写盘 → 升格。novel 校验放在梯级 1 之后,
因为它的判据(candidates)是梯级 1 的输出。

## D5. 验收 → 测试映射(见 tasks.md)

| #495 验收 | 测试(tests/test_failure_analysis_transducer.py) |
|---|---|
| 三产物记录进 analysis | `test_record_three_artifacts_written` |
| 障碍自动升格 claim(OPEN/depends_on/继承 answers_question) | `test_obstacle_promoted_to_claim_grows_dag` |
| 升格幂等(重跑不重复建) | `test_obstacle_promotion_idempotent` |
| lessons 自动检索注入 candidates + 留痕 | `test_record_runs_lessons_ladder_into_candidates` |
| 检索 fail-open 不阻塞 | `test_ladder_fail_open_on_search_error` |
| 缺/非法 source 拒绝 | `test_source_required_to_record` / `test_source_invalid_enum_rejected` |
| novel 需 candidates 非空 | `test_novel_hypothesis_requires_candidates` |
| 三产物缺失 → BLOCKED(轨迹1 单元级:瞬态失败×2 后判死宣告被拦) | `test_transient_failures_without_artifacts_stay_blocked` |
| CLI 接线(拒绝路径 + 全链路) | `test_cli_record_rejects_missing_source` / `test_cli_record_full_transducer_path` |

负例(父计划"双轨迹重演"的单元级版,行为等价类非逐字):轨迹1 = 判死
宣告不改变 BLOCKED(三产物缺失即拦,与措辞无关);DAG 生长 = 升格后
claim_deps.yaml 出现真依赖边。

## Rejected

- **R1 机械执行梯级 2/3(re-library 扫描 / WebSearch 调用)**:把网络调用
  塞进记录路径违反 fail-open 约束(超时即阻塞);梯级 2/3 是声明面,
  门只校验声明合法性与 novel 的梯级 1 前置。
- **R2 三产物落 facts/ 层**:facts 是 worker 的字节级证据协议(frontmatter
  schema 另一套);失败转导产物是分析时序事实,落 analyses/ 即可回流
  (#41 --lessons 聚合已消费该目录),再建一层 = F 类机制冗余。
- **R3 升格 claim 用 statement 全文做幂等键**:措辞微调即重复建;归属
   标记(obstacle_for)才是稳定键 — 与 `_lesson_slug` 按内容判重不同,
   这里判重的是"这个失败有没有转过导",不是"障碍是否同款"。
- **R4 收紧写进 dispatch_gate / convergence_check**:那是第二表示;单一
   覆盖判据在 `_analysis_covers`,消费方经 scan_workspace 自动传播(#444
   同款"一处实现多处消费")。
- **R5 给旧 analysis 做迁移脚本**:旧记录无产物信息可迁移(证据已蒸发,
   这正是本 issue 的动机);正确动作是按新协议重录,BLOCKED 状态本身
   就是指引。
