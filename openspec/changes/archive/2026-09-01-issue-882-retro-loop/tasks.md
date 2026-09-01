# issue-882 — tasks

## 1. 微回溯（触点①）

- [x] TDD：tests/test_backtrack_loop_882.py — 结算索引 record → 同 (scene,operation)
      微回溯命中；异 key 不命中；dispatch 注入块含"前车之鉴"+ 工具/结果；无教训 →
      不注入（零噪声）；索引滚动截断至 K。
- [x] scripts/backtrack_loop.py：`.retro-index.json` / `.retro-state.json`、
      record_settlement / micro_lessons / micro_lessons_context。
- [x] hooks/dispatch_gate.py：ALLOW 收尾链挂 additionalContext 注入
     （capability guard 通过后、trace_allocated 前；不提前 return）。

## 2. 结算回溯（触点②）

- [x] TDD：emit_settlements → `runs/<ts>-retro-<claim>.md` 落盘（trace 子图行 +
      from→to + 假成功标记）；PROVEN 无 PQ 覆盖 → FAKE-SUCCESS 标记；滞后计数
      bump；gate/tick rc 契约不变。
- [x] scripts/register_proven_gate.py：emit_settlements 内挂 record_settlement +
      settlement_retro（fail-open，镜像 _burn_lesson_lineage 姿态）。
- [x] scripts/backtrack_loop.py：settlement_retro（trace 子图局部回放 +
      FAKE-SUCCESS 检查 + 同 key 负史）→ `retro_report` 词。

## 3. 策略回溯（触点③）

- [x] TDD：三触发（每 N 结算 / stall 指纹 / plan_review ritual）各自 trip；不 trip
      不产出；policy retro 写议程（数据项：ΔV_m/claim、失败签名重复、drift、
      DECIDE 输出、PROPOSAL 行）；kunglao-decide 被调（议程含 DECIDE 段 =
      调用图证据）；假设种子入 hypothesis_store（幂等）。
- [x] scripts/backtrack_loop.py：policy_due / run_policy_retro（窗口聚合 +
      plan_reviser.run_checks + plan_drift_detector 子进程 + kunglao-decide
      --json 子进程 + HypothesisStore.create）→ `retro_policy` 词 + `hypothesis_seed` 复用。
- [x] scripts/heartbeat_tick.py：`report["backtrack"] = run("backtrack_loop.py",
      ws, "--policy")`（advisory，镜像 rollup_sweep/#883 挂法）。
- [x] scripts/event_taxonomy.py：EMIT_ACTIONS += retro_policy / retro_report
      (字母序)。

## 4. 座舱三字段

- [x] TDD：cockpit_summary 带 backtrack 三字段；快照带 backtrack 段；两 slot
      探针上线（含 staleness_budget 守卫）；pending_proposals 推导（plan_review
      行晚于议程 → 0）。
- [x] scripts/tuition_curve.py：cockpit_summary += backtrack。
- [x] scripts/statusline_snapshot.py：slot 补 probe fn（unattributed_rate>0.30 /
      backtrack_lag>8）+ build_snapshot backtrack 段；更新 #883 slot 测试至
      "#882 已落地"状态（其自述演进）。

## 5. 登记 + 收尾

- [x] scripts/README.md 登记 backtrack_loop.py。
- [x] deploy_manifest：--write → --check 绿。
- [x] 本地三门：pytest 全量 / release_receipt --check / deploy_manifest --check。
- [x] push + gh pr create --base dev（Fixes #882）+ CI 绿（不 merge）。
