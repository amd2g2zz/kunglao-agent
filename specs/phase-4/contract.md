# Phase 4 契约 — M1 DECIDE 动作选择改造

> **修订 2026-08-06 (issue #1 cleanup-routing-module)**: 路由层(method_router / method_topk / method_router_register / method-graph)经实验证伪 CUT,本契约已移除全部路由段。priority_ratio 段保留当前实现(旧 0.35·Δdisc 公式),VoI 代理重写见 issue #2(`phase4-voi-priority`)。

来源文档(冻结源, 引文带行号):
- `docs/design/module-design.md` — §M1 全部 (L112-207); M1.1 划分 L114-125; M1.2 签名 L126-159; M1.3 schema L160-172; M1.4 状态机 L173-192; M1.5 错误处理 L193-199; M1.6 测试点 L200-205
- 同目录 `docs/design/design-spec.md` — §3.2 比值键算法(L129, 含 2026-08-06 VoI 代理定稿)
- 现成可复用(不改): `scripts/convergence_check.py::decide`(5 分支矩阵, golden F-01..F-16)、`scripts/priority.py::rank_claims`(legacy 加法权重)、`scripts/ask_for_direction_gate.py`(selfcheck 反问部分已实现)

> 2026-08-14 (#319 去重): 源文档随 docs 树合一迁至 `docs/design/`(旧树已删,
> 见 git 历史), 行号按当前文件重核。注: 现 `docs/design/module-design.md`
> M1.2 含 resource_selector/feedback_updater(2026-08-06 修订), 与本契约
> "路由已移除"的冻结签名集不同 — 即 #319 审计发现的两树内容漂移。

---

## 1. 函数签名(冻结, M1.2 原文 L126-159, 路由已移除)

```python
def convergence_matrix(open_count, partial_count, free_slots, blocked_count) -> Decision:
    """→ DISPATCH(1) | DISPATCH_VERIFIER(2) | SATURATED(3) | BLOCKED(4) | CONVERGED(0)"""

def priority_ratio(claims: list[Claim], deps: DepGraph, evidence: EvidenceView) -> list[Action]:
    """比值键排序: score = [0.35·Δdisc + 0.35·E_unlock + 0.10·unc] / cost
    Δdisc = marginal_discriminator(对已得证据去重)
    E_unlock = expected_unlock(deps) × P(success)
    unc = freshness = 1/(1+attempts)
    cost = NEXT_TIER_CHEAP[tier]"""
    # 注: 上述为当前实现; VoI 代理重写 [0.45L+0.30D+0.25N]/cost 见 issue #2

def explore_gate(verified_fact_count: int, threshold: int) -> bool:
    """count < threshold → 探索模式(按 cheapness 铺开 T1)"""

def selfcheck(text: str) -> list[str]:
    """扫描 orchestrator 输出, 找反问/自加 cap 违规"""

def decide(ws: Path, scan_text: str | None = None) -> dict:
    """组合以上; 输出契约冻结。路由 CUT: top_actions.skill 恒 None, worker 自选工具。"""
```

### 落地映射(契约空白决策)

| 设计签名 | 本阶段落地 | 备注 |
|---|---|---|
| `convergence_matrix(...)` | **不新建** — `convergence_check.decide(ws)` 已实现同矩阵(5 分支顺序一致, L241-259)且 golden 冻结 | M1.6 L202 "行为快照已有" |
| `priority_ratio(claims, deps, evidence)` | `scripts/priority_ratio.py::priority_ratio` | 纯函数; failure-blocked 过滤由调用方(kunglao-decide)做(签名无 ws) |
| `explore_gate(count, threshold)` | `scripts/explore_gate.py::explore_gate(count, threshold=EXPLORE_THRESHOLD)` | `EXPLORE_THRESHOLD = 5` |
| `selfcheck(text)` | `scripts/kunglao-decide.py::selfcheck(text)` 组合 `ask_for_direction_gate.find_violations`(反问) + `worker_budget.detect_self_cap`(自加 cap) | ask_for_direction_gate 已实现, 只补测试 |
| `decide(ws)` | `scripts/kunglao-decide.py::decide(ws, scan_text=...)` | 独立 CLI, 非 kunglao.py 子命令 |

### priority_ratio 分量语义(契约空白决策, 均写死进 contract 与测试)

- `Δdisc(a) = marginal_discriminator(a, evidence)`:
  - claim a 在 `facts/_INDEX.md` 中有 **terminal fact**(状态含 PROVEN/VERIFIED/NEGATIVE/REFUTED/DEFERRED 之一)→ `0.0`(已得证据去重)
  - 否则 `1.0`
- `E_unlock(a) = expected_unlock(a, deps) × P(success)`:
  - closure 复用 `priority._leverage_v2`(sigmoid 传递闭包 + gateway bonus, 裁剪 [0,1]; priority.py L93-113 现成可复用)
  - `P(success) = 1/(1+promotion_attempts)`(契约空白)
- `unc(a) = freshness(a) = 1/(1+attempts(a))`(与 P(success) 同形)
- `cost(a) = NEXT_TIER_CHEAP[evidence_tier_attempted(a)]`, 字典 = priority.py L44 `{0: 1.0, 1: 0.5, 2: 0.2}`, 越界 `0.1`
- `score(a) = (0.35·Δdisc + 0.35·E_unlock + 0.10·unc) / cost(a)`
- 排序: score 降序; dispatchable 过滤: 非 terminal、attempts<3、depends_on 全部 terminal
- `classify_action(claim)`: 关键词分类器(statement+answers_question 小写): C2/mpd/pegasus/dead-drop→`c2_config_extract`; 命令表→`command_table`; 协议/runtime/网络→`protocol_restore`; 持久化/autorun→`persistence`; 注入/reflective→`injection`; 反分析/garble/诱饵→`anti_analysis`; 家族/vidar/wingo/gsb→`family_attribution`; 未命中→`evidence_collection`

### 探索模式(design-spec §3.2)

`explore_gate(verified_fact_count, threshold=5)`: `count < threshold` → 探索模式。kunglao-decide 在探索模式下按 cheapness 铺开: 同 dispatchable 过滤, `score = NEXT_TIER_CHEAP[eta]` 降序(T1 优先), `explore_mode=True`。

---

## 2. 输出 schema 引用

- 冻结结构: `schemas/decide-output.json`(M1.3 L163-170 逐字段)
- 必需 9 字段: `decision`(enum 5 值) / `exit_code`(0-4) / `top_actions[]`(items: claim_id, action, score, skill) / `blocked[]` / `failure_blocked[]` / `stale[]` / `drifts[]` / `explore_mode`(bool) / `selfcheck[]`
- 附加字段(additionalProperties 允许, 非冻结必需): `open_count`, `partial_count`, `free_slots`, `error`
- 字段映射(契约空白):
  - `blocked` = open_claims 中 `blocked=True` 的 id
  - `failure_blocked` = convergence_check 的 failure_blocked(经 failure_analysis_gate.scan_workspace)
  - `stale` = stuck_workers 的 worker 名(>20min 无 in-progress 更新)
  - `drifts` = 恒 `[]`(阶段 4 不计算; plan_drift_detector 为独立 gate)
  - `selfcheck` = `--scan-text` 提供时扫描, 否则 `[]`
  - `top_actions[].skill` = 恒 `None`(路由 CUT, worker 自选)

## 3. 状态机(M1.4 原文流程, 路由步已移除)

```
decide(ws):
  evidence = load_evidence(ws)                    # facts/_INDEX + ledger + loopstate
  decision = convergence_matrix(...)              # ← convergence_check.decide (golden)
  if decision == DISPATCH:
    if explore_gate(evidence.verified_count):     # 早期
      top = sort_by(cheapness)[:k]                # explore_mode=True
    else:
      actions = priority_ratio(claims, deps, evidence)
    dispatch(top)                                 # skill=None; worker 自选工具
  elif decision == DISPATCH_VERIFIER:
    dispatch_verifier(partial_facts)
  return DecideOutput
```

- `k = free_slots = max(0, 3 - active_workers)`(convergence_check L231)
- DISPATCH_VERIFIER / SATURATED / CONVERGED: `top_actions=[]`, 其余字段照 convergence_check 映射
- 脚本异常(M1.5 L198): 记 ledger(failure_recorded) + 返回 `BLOCKED`(exit 4) + `error` 字段 — **不误报收敛**

## 4. 测试点(M1.6 + 本阶段 RED 清单, 路由测试点已移除)

| 测试点 | 断言 | 文件 |
|---|---|---|
| 比值键公式 | `score == (0.35·Δdisc + 0.35·E_unlock + 0.10·unc)/cost(NEXT_TIER_CHEAP)`; **≠ 加法权重**; 排序 score 降序 | tests/test_priority_ratio.py |
| Δdisc 去重 | claim 已有 terminal fact → Δdisc=0 → 分数必低于无证据同 claim | 同上 |
| unc 新鲜度 | attempts 增 → unc 降 → score 降 | 同上 |
| dispatchable 过滤 | terminal / attempts≥3 / dep 非 terminal 排除 | 同上 |
| E_unlock 传递闭包 | 解锁下游的 claim 的 E_unlock 高于无下游者 | 同上 |
| explore_gate | count<5 → True; =5/≥5 → False; 自定义 threshold | tests/test_explore_gate.py |
| kunglao-decide 组合 | DISPATCH 时 top_actions 有值且过 `schemas/decide-output.json`; CONVERGED 时 top_actions=[]; explore_mode 正确; skill 恒 None | 同上 |
| selfcheck | 反问文本 REJECT(rc=1); 自加 cap 文本 REJECT(rc=1); 组合扫描返回违规列表 | 同上 |

## 5. 完成判据

1. 全部新增测试绿 + 全量回归绿(`python -m pytest -q -p no:cacheprovider`)
2. `schemas/decide-output.json` 对 kunglao-decide 输出通过 jsonschema 校验
3. E4.1: `tools/measure_value_order.py` 输出符合率%(如实报告, 不为达标改排序/挑样本)
4. 约束: 不碰 SKILL.md/references/hooks/kunglao.py/convergence_check.py/priority.py/test_suite_health.py/test_kunglao_init.py; 不 git commit
5. **issue #1 cleanup**: `git grep -iE "method_router|method_topk" scripts/ tests/` 空

> issue #2(`phase4-voi-priority`)将重写 §1 priority_ratio 签名 + 分量语义为 VoI 代理 `[0.45L+0.30D+0.25N]/cost`,并改上表"比值键公式"测试点。
