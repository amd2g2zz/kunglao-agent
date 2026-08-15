## Why

r3 实测 75.6% 轮次零 fact delta：循环分不清"在生产"还是"空转"。验证信号其实
一直存在——verify-note 落 `runs/<ts>-verify-<note>.md` 的 `## Overall verdict:
passes/partial/fails`，red-team 落 `runs/verify-redteam-<target>.md` 的
`CONFIRMED/REFUTED/UNVERIFIED`——但这些结果**只活在文件里，从不进 ledger**。
感知层（convergence_health / priority / prompt 注入）因此看不见外部验证在持续
产出，把陈旧快照误当信号。

根因链：

- `.convergence_ledger.jsonl` 现有行**全是 SNAPSHOT**（ts/decision/open_count/…），
  没有事件行 → 聚合层只能数 open_count 趋势，看不到"验证事件还在产生"。
- verify-note / red-team 各自写文件、各自约定 verdict 串，但没有一个归一入口把
  "一次外部验证结果"落成可聚合的 ledger 事件。
- `status_defs.LedgerLineType.OUTCOME` 契约已在 #34 冻结（additive：无 `type` 字段
  仍视为 SNAPSHOT），但**零生产消费者**——本变更是第一个消费者。

## What Changes

- **`scripts/outcome_capture.py`**（新）：扫 `runs/*.md` → 归一为
  `{"type":"outcome","ts","claim_id","result","checker"}` 行追加到
  `.convergence_ledger.jsonl`。两个 checker：
  - **verify-note**：`## Overall verdict` 节取 `passes|partial|fails`（正则宽松
    容忍空白行）；claim_id 从 frontmatter `claim_id:` 读，缺失 fallback 文件名。
  - **red-team**：`RED-TEAM VERDICT: CONFIRMED|REFUTED|UNVERIFIED(-WITH-GAP)`；
    claim_id 从正文 `claim:/target:` 抽 `C-NNN`，缺失 fallback 文件名。
  幂等：`_seen_key = claim_id|checker|result`（同 claim 同 checker 同结果 → 跳过，
  镜像 `kunglao_record.record_event` 的 `event_id` 去重，但排除易变 ts）。
  容错读：镜像 `convergence_health._read_ledger` 逐行 `json.loads`，空行/坏行跳过。
- **`aggregate_reward(rows) -> float | None`**（纯函数）：结果值映射平均
  （passes/CONFIRMED=1.0，partial/UNVERIFIED=0.5，fails/REFUTED=0.0）；无 OUTCOME
  行 → `None`（中性，不误报 0 信号——0.5 已是"全 UNVERIFIED"的有意义值，None 才
  能区分"无信号"与"平均信号"）。聚合只消费 `type==outcome` 行（SNAPSHOT 永不参与）。
- **reward 是 soft 信号 only**：不 gate 任何机械门；接线 priority / prompt 注入
  留给 R6 后续（等 ≥2 样本防过拟合）。
- **tests（RED→GREEN）**：5 条覆盖 issue 三条要求——outcome 行独立 type 可聚合 /
  重复 verify 不重复累计 / 无数据返回中性 / snapshot 行不参与聚合。

## Capabilities

### New Capabilities

- `outcome-capture`: 把 verify-note / red-team 的外部验证结果归一为 ledger
  OUTCOME 事件行，并提供纯函数 `aggregate_reward` 聚合为 0.0–1.0 reward 标量
  （无数据 → None）。reward 仅作 soft 信号，不 gate 任何机械门。

### Modified Capabilities

无。`status_defs.LedgerLineType.OUTCOME` 契约已在 #34 冻结，本变更只消费它，
不改契约（additive：现有无 `type` 字段的 SNAPSHOT 行不受影响）。

## Impact

- `scripts/outcome_capture.py`（新，~150 行）：`capture` / `read_outcome_rows` /
  `aggregate_reward` / `_seen_key` / `_claim_from_note` / `_claim_from_redteam` /
  `main` CLI（`--reward` / `--json`）
- `scripts/test_outcome_capture.py`（新）：5 条 AAA 测试
- `scripts/status_defs.py`：零代码改动（OUTCOME 行字段契约已存在 L42-84，本变更
  是其第一个消费者，docstring 已描述该契约）
- 依赖：纯标准库（json/re/sys/datetime/pathlib）+ `status_defs`（同仓）；零新
  LLM/API 调用，零新第三方包
- 关联：消费 #34 冻结的 `LedgerLineType.OUTCOME` 契约；与 #36（worker_pulse
  quarantined）正交；reward 接线 priority 留给 R6 后续
- 风险：`## Overall verdict` 格式漂移 → 正则宽松 + fallback 文件名；ledger 并发
  append 竞态 → 低频（单 orchestrator 写），后续可 tmp→replace，不阻塞本变更
