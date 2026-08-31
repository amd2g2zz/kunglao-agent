## Tasks: #815 早停接线

- [ ] 1. SDD proposal/tasks（本目录）
- [ ] 2. TDD 红：tests/test_infeasible_proposal_815.py
  - [ ] 2a. 阶梯文件缺失 → REJECT，寄存器零变更
  - [ ] 2b. 阶梯缺层（只 L1）→ REJECT 且 reason 指名缺 L2,L3
  - [ ] 2c. 阶梯齐但清单空 → REJECT
  - [ ] 2d. 缺 wake_condition → REJECT
  - [ ] 2e. 全要件齐 → claim DEFERRED + wake_condition + 审计工件 + ledger `infeasible_filed`
  - [ ] 2f. 终态 claim（PROVEN）不可立案
  - [ ] 2g. wake：infeasible-DEFERRED → OPEN（带 woken_at/wake_reason + `infeasible_woken`）；非 infeasible DEFERRED REJECT
  - [ ] 2h. 派发面：DEFERRED 后 priority_ratio.is_open=False（自动退出派发）
- [ ] 3. 实现 scripts/infeasible_proposal.py（mirror dead_letter 模式；信号 state 文件存在为机械前置）
- [ ] 4. EMIT_ACTIONS 注册 `infeasible_filed`/`infeasible_woken`（字母序）
- [ ] 5. scripts/README.md catalog 行 + deploy_manifest --write + ext-scan
- [ ] 6. 本地质量门：pytest 全量 + 定向门全绿 → push → PR(base=dev)
