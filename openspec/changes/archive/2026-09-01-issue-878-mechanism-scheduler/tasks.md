# issue-878 — tasks

## 1. 注册表 + schema 门

- [x] TDD：tests/test_mechanism_scheduler_878.py — 随仓 mechanisms.yaml 校验通过；
      缺 trigger / cost_class / cockpit_signal 三项前置各自被拒；trigger.type 越表被拒；
      cost_class 越阶被拒；gate 未知被拒；重名被拒；channel 词汇钉死。
- [x] scripts/mechanisms.yaml — schema kunglao.mechanisms/1，13 条目
      （8 入口裁定 + tick advisory 子步骤迁入），每条
      {name, entry, channel, trigger{type,gate,(host),(events)}, cost_class, depth,
      cockpit_signal, owner, description}。
- [x] scripts/mechanism_scheduler.py — load_registry / validate_registry
      （fail-closed 面：册坏整轮拒跑 + mech_reject emit）。

## 2. 单宿主 tick + 预算

- [x] TDD — 调度决策：gate due 才跑（policy_retro 非 due 不 spawn 子进程）；廉价先行
      （预算只够一个时 cheap 跑、expensive drop）；预算尽 drop 计数++；失败 rc 透传
      不计 drop；runner 注入 seam（脚本名+argv 与既有 tick 手搓逐字一致）。
- [x] scripts/mechanism_scheduler.py — run_due(ws, budget_s, runner, now)；
      state runs/.mechanisms-state.json（last_run/last_rc/drops/next_eligible，
      原子写）；compact 视图。
- [x] scripts/heartbeat_tick.py — :239-286 advisory 手搓段替换为注册表遍历
      （runner=run 注入；legacy key 回填映射；report["mechanisms"] 新面；
      liveness 核心/oracle/breaker/cockpit/快照原样保留）。
- [x] scripts/event_taxonomy.py — EMIT_ACTIONS += mech_reject / mech_run（字母序）。

## 3. 账本事件总线

- [x] TDD — 事件类映射（claim_settled→settlement；mission_stall/plan_stall→stall；
      plan_review→plan_review）；byte-offset 只读增量（offset 前进、截断回退、
      半行不吞）；事件类喂 policy_retro 门（stall/plan_review 行触发 lag<N 的回溯）。
- [x] scripts/mechanism_scheduler.py — read_new_events(ws)（镜像 #883 有界读 +
      持久 offset state）；GATES 词表（always/loop_unregistered/session_dead/policy_due）。

## 4. 座舱健康段

- [x] TDD — build_snapshot 带 mechanisms 段（每机制 {last_run,next_eligible,drops}）；
      mechanism_health 探针（last_rc∉{0,None} → 不 ok + [mech] 码）；
      staleness_budget 守卫继续生效。
- [x] scripts/statusline_snapshot.py — mechanisms 段 + probe_mechanism_health 探针
      （fail-open，镜像 backtrack 段挂法）。

## 5. 一条命令 + 迁移收尾

- [x] TDD — --plan 输出覆盖全部注册条目（含 8 入口）且含 trigger/gate/cost/
      next_eligible/drops 答案；--check 门面 rc 契约；--status/--run 面。
- [x] scripts/mechanism_scheduler.py — CLI（--plan/--check/--status/--run）。
- [x] scripts/README.md — 登记 mechanism_scheduler.py 行。
- [x] tools/_INDEX.ext.yaml — ext-scan 再生（新 CLI 入发现面）。
- [x] deploy-manifest — 先 ext-scan 再 --write 后 --verify（顺序陷阱）。

## 6. 本地门 + 交付

- [x] python -m pytest tests/ -q 全绿（100%；已知 7 环境性基线失败照 stash 对照甄别）。
- [x] python scripts/release_receipt.py --check 绿。
- [x] conventional commits 小粒度 → push → gh pr create --base dev（Fixes #878）
      → CI 绿 → 停手不 merge。
