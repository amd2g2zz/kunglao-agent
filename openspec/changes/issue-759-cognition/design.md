# Design: orchestrator 认知层 (#759)

## D1 — 用户裁决 + 现场证据（2026-08-27）

用户裁决（原文）：**"调度需要处理规划/价值/下一次部署"**。

#711 三条现场证据（#704 dispatch 后台化之后的等待期行为）：

| # | 证据 | 后果 |
|---|---|---|
| E1 | tick 等待期 action_taken EMPTY，零认知产出 | 整个等待窗口没有推理产物；#237 把空字段定义为空闲故障信号，但没人给它替代物 |
| E2 | 价值排序靠用户手改文件 + SendMessage hack | 用户一次裁决（"目标是 RCE"）无结构化入口 |
| E3 | 主动检索靠用户两次提示才发生；三次关键洞见两次来自红队一次来自用户 | "不搜是确定性损失"（SKILL 契约句），但触发器不存在 |

## D2 — 代码锚

| 锚 | 角色 |
|---|---|
| scripts/heartbeat_tick.py main() 步骤链 + action_taken #237 契约 | T1 挂点 |
| scripts/priority_ratio.py priority_ratio() 纯函数 + EvidenceView.from_workspace 单点装配 | T2 注入点 |
| scripts/notes_writer.py note_supersedes_hypothesis NotImplementedError 缝（#762 K3） | T2b 接线点 |
| scripts/event_taxonomy.py EMIT_ACTIONS 受控词表（静态字面量扫描锚 test_event_stream_adoption） | T2b 事件注册 |
| skills/kunglao-agent/SKILL.md Phase 2 决策表 + Tick binding 段 | 契约层 |

守门：`grep -rn 'action_taken\|priority_ratio\|note_supersedes' tests/ --include='*.py'
| grep -v test_cognition` —— 命中面语义全部保持不变。唯一例外：
test_notes_closure_762.py 的 K3 seam 占位测试（NotImplementedError 断言）随实装
升级为"已接线"断言——K1a/K1b/K2 面零改动。

## D3 — T1 THINK 席位

**等待期判定**（机械、保守）：`claim-register.yaml` 存在 **且**
`priority_ratio()` 返回零 dispatchable 动作。判定失败（损坏 register 等）
一律 = 不等待 → 不点火（保持 legacy 行为，test_heartbeat_off 的
`action_taken == ""` 断言由此保住——那个 fixture 无 register）。

**席位产物** `runs/.think-<UTCcompact>.md`：三段固定 schema
`## patterns` / `## hypotheses` / `## value`；模板内嵌输入摘要
（facts/_INDEX 尾部行 + hypothesis_store open 清单）。脚本只保证
"席位存在 + 产物落盘 + 路径机器可读"，永不生成思考内容本身——
占位段留给 orchestrator LLM 就地填。

**tick 接线**：heartbeat_tick 以 run() 子进程方式调 think_seat.py（与
monitor/rollup_sweep 同一 advisory 形态：rc 不进 alert 权重）；stdout 为
单行 JSON，解析失败一律 = 席位不可用（不 substitute）。waiting 且有 artifact
→ `report["action_taken"] = f"THINK {path}"`。

**为什么子进程而不是进程内 import**：monkeypatch run() 的既有套件
（628/620c/762/heartbeat_off）不该隐式执行真实文件写；run() 边界天然隔离。

## D4 — T2 价值函数

`runs/value-weights.yaml`：

```yaml
schema: kunglao-value-weights/1
source: user-ruling            # 或 orchestrator-adjudication
rationale: "目标是RCE，DoS拿不到赏金"
claim_classes:                 # impact class → weight
  rce: 10
  dos: 1
overrides:                     # per-claim 显式覆盖，最高优先
  C-202: 5
```

- 加载点：`EvidenceView.from_workspace`（kunglao-decide / dispatch_context /
  dispatch_gate top1 audit 全部经此单点 → 权重自动全链路生效）。
  fail-open：缺文件 / yaml 损坏 / 形态错 / 非>0 数值条目 → 忽略该项。
- 乘法点：score = (VoI numerator / cost) × weight。注入的 EvidenceView
  （默认权重 {}）逐字节保持旧公式 → test_scoring_is_deterministic_pure 不动。
- claim→class 解析序：overrides[claim_id] > claim.value_class 字段 >
  词边界关键词分类（rce/dos/sandbox_escape/c2_extract…）> 1.0。
  机械词表，无自然语言推断（同 tool_families_from_text 形态）。
- 写入通道契约（SKILL.md）：用户裁决由 orchestrator 结构化写入本文件；
  手改排序输入 / SendMessage 中断循环不是通道。

## D5 — T2b K3 接线（Closes #762）

**指针键独立于 notes 链**：frontmatter 用 `supersedes_hypothesis: H-NNN`
（Plain `supersedes:` 已被 #528 check_write 强制指向 notes/ 内存在的目标，
混用会把假链伪造面重新打开；独立键 = note 链（结果层）与假设改写
（假设层）互不干扰）。兼容形态：`supersedes:` 仅当目标在 hypotheses/
下解析成功时也被接受。

**状态迁移**：仅 open→superseded（superseded_by=<note id>，后继可以是一个
NOTE id —— 假设现已活在新结论 note 里，这是对 #528 successor 语义的扩展）。
非 open 源状态大声抛 InvalidTransition（终态不重开是 #528 铁律）。

**三件套**：事件 `hypothesis_superseded`（EMIT_ACTIONS 注册，detail 带
affected_claims）；affected_claims = hyp.claim_id ∪ 同 competitor_group
peer hypotheses 的 claim_id（只读计算，排序去重）；返回 dict 暴露列表。
不改 claim-register（重排信号由下一轮 value/priority 重算自然吸收）。

## D6 — T3 主动触发器

- 进度信号：`runs/think-state.json` {digest:{terminal_facts, open_claims},
  stall_ticks}——每次等待期 THINK 重算 digest，相同 +1，不同归零。
  N tick 无进展 = stall_ticks ≥ THRESHOLD(=3)。
- 触发时模板增 `## suggested_searches`：每 stalled open claim 两列机械种子
  （websearch query 由 classify_action 类别合成；reference-library 行指向
  references_recall 场景调用），cap 3 claims；保证非空 by construction，
  具体措辞由 orchestrator 精化。
- SKILL 契约一句："THINK 产物的 suggested_searches 必须在下一动作执行"
  （E3 对策）。
