# Design — outcome-capture-r6 (#35)

## Design Decisions

### D1. 两本账本不混——只写 `.convergence_ledger.jsonl`

仓里有两本 JSONL 账本：

- `.convergence_ledger.jsonl`（convergence_check / convergence_health 用）——SNAPSHOT
  行（ts/decision/open_count/…），本变更追加 OUTCOME 行。
- `ledger.jsonl`（kunglao_record 用）——seq/event_id/checksum 的事件账本。

本变更**只写前者**，与后者完全隔离。两本账本语义不同（前者是循环状态轨迹，后者
是 claim 生命周期事件），混写会污染 convergence_health 的 `_dedup_consecutive`
与 `_flatline_run`（它们假设行都是 snapshot 形态）。OUTCOME 行被
`ledger_line_type()` 识别为独立类型后，convergence_health 现有逻辑会把它当作
"无 open_count 字段的 snapshot"——需在 D7 说明兼容性。

### D2. 容错逐行读（MIRROR `convergence_health._read_ledger`）

`read_outcome_rows(workspace)` 镜像 `convergence_health.py:68-81`：

```python
for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line: continue
    try: row = json.loads(line)
    except json.JSONDecodeError: continue
    if ledger_line_type(row) == LedgerLineType.OUTCOME: out.append(row)
```

关键：用 `ledger_line_type(row)`（来自 #34）判型，而不是 `row.get("type")=="outcome"`
裸写——契约升级只改 `status_defs` 一处，本模块自动跟进。SNAPSHOT 行（无 `type` 或
`type=="snapshot"`）被排除，保证聚合只消费 OUTCOME。

### D3. 幂等 append（MIRROR `kunglao_record.record_event`，去易变字段）

`kunglao_record.record_event` 用 `event_id = sha256(event_type + canonical(payload))`
去重（L89-112）。镜像该模式，但**排除易变 ts**——否则每次 capture 都因 ts 不同而
误判为新事件：

```python
def _seen_key(row): return f"{row.get('claim_id')}|{row.get('checker')}|{row.get('result')}"
```

同一 claim + 同一 checker + 同一 result → 视为重复，跳过（不重复 append）。result
**纳入**键：C-1 先 partial 后 passes 是两个不同事件（验证状态演进），都应记录；
只有"同 claim 同 checker 同结果"才是真正的重复（同一份 verify 文件被扫两次）。

append 写（非 tmp→replace）：单 orchestrator 串行写，并发风险低；tmp→replace
留给后续优化（不阻塞）。

### D4. `## Overall verdict` 机械读取（容空白）

verify-note 产物格式（`malware-veri-notes/scripts/verify-note.py:106-110`）：

```
## Overall verdict
To be filled by Claude after collecting all subagent outputs:
`passes` (all facts reproduce) / `partial` (some reproduce) / `fails` (any cannot)
```

正则 `r"## Overall verdict\s*\n+\s*(\S+)"`（IGNORECASE）——`\s*\n+\s*` 容忍标题与
取值间任意空白/空行。取值 `passes|partial|fails` 落库前 `.strip().lower()`。
匹配失败 → 跳过该文件（不崩）。注意：取第一非空 token，故"`` `passes` ``"反引号
场景取到的是 `` `passes` ``——verify-note 实际产物是裸 `passes`（无反引号，见
模板行），正则按裸串设计；若产物漂移到反引号，需后续调整（不阻塞，记 risk）。

### D5. red-team verdict + claim 抽取

red-team 产物（`kunglao-redteam` agent）含 `RED-TEAM VERDICT: CONFIRMED|REFUTED|
UNVERIFIED(-WITH-GAP)`。正则：

```python
REDTEAM_RE = r"RED-TEAM VERDICT\s*[:\-]?\s*(CONFIRMED|REFUTED|UNVERIFIED(?:\s*-\s*WITH-GAP)?)"
```

claim_id 从正文 `claim:/target:` 抽 `C-NNN`（`r"(?:claim[:=]?|target[:=]?)(C-\d+)"`）；
缺失 fallback 文件名（保幂等键稳定——同文件名同 checker 同 result 仍能去重）。

### D6. `aggregate_reward` 纯函数——聚合只消费 OUTCOME

```python
RESULT_SCORE = {
    "passes": 1.0, "partial": 0.5, "fails": 0.0,
    "CONFIRMED": 1.0, "REFUTED": 0.0, "UNVERIFIED": 0.5, "UNVERIFIED-WITH-GAP": 0.5,
}
def aggregate_reward(rows):
    scores = [RESULT_SCORE.get(r.get("result"), 0.0) for r in rows
              if r.get("type") == LedgerLineType.OUTCOME]
    return sum(scores) / len(scores) if scores else None
```

- **纯函数**：同输入同输出，无副作用，LLM 永不进分数（风格镜像
  `priority_ratio.py` 纯函数排序）。
- **防御性 type 过滤**：即便被传整本 ledger（含 SNAPSHOT），也只聚合 OUTCOME。
- **未知 result → 0.0**：`RESULT_SCORE.get(..., 0.0)`，保守（不明结果不给分）。
- **无数据 → None**：不误报 0.0（会与"全 fails"混淆），不误报 0.5（会与"全
  UNVERIFIED/平均"混淆）。调用方（priority/prompt 注入）自行决定 None 的默认
  含义——R6 接线时再定。

### D7. SNAPSHOT 行兼容（additive）

现有 `.convergence_ledger.jsonl` 行无 `type` 字段 → `ledger_line_type()` 返回
SNAPSHOT（#34 契约）。本变更 additive：

- `read_outcome_rows` 只挑 OUTCOME → SNAPSHOT 行被忽略，不影响聚合。
- `capture` 只 append OUTCOME 行 → 不改写既有 SNAPSHOT 行。
- convergence_health 的 `_read_ledger` / `_dedup_consecutive` / `_flatline_run`
  读 OUTCOME 行时，`open_count`/`open_ids` 字段缺失 → `_dedup_consecutive` 的
  `same_state` 判定会因 None!=None 比较而把它们当不同状态（保守保留，不崩）。
  实测：convergence_health 现有测试无 OUTCOME 行夹入的 case，本变更不引入回归
  （全量 tests/ 回归在 Task 3 验证）。

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/outcome_capture.py` | CREATE | capture() / read_outcome_rows() / aggregate_reward() / CLI |
| `scripts/test_outcome_capture.py` | CREATE | 5 条 AAA RED→GREEN 测试 |
| `scripts/status_defs.py` | （无改动） | OUTCOME 行契约已存在 L42-84；本变更是第一个消费者 |

## Out of scope

- **reward 接线 priority / prompt 注入**：留给 R6 后续（等 ≥2 样本防过拟合）。
- **worker_pulse quarantined**：#36 协同，本变更不动 hooks。
- **tmp→replace 原子写**：单 orchestrator 串行写，并发风险低，后续优化。
- **改 convergence_health 消费 OUTCOME**：trajectory 探测仍只看 SNAPSHOT；
  OUTCOME 是事件层，trajectory 是状态层，两者正交。
