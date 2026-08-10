# convergence-completeness-gate
## What
CONVERGED 判定从"open_claims==0 AND partial_facts==0"升级为三重完整性门:
(a) 所有 primary_questions 都有 PROVEN(非 STAMP/unverified)claim 答;
(b) 零 orphan terminal claim(terminal 但无 answers_question 链);
(c) SPINNING 假收敛检测加固——`_dedup_consecutive` 不误折真实 flatline。
不满足 (a)/(b) 时 CONVERGED 降级为 SATURATED 或 BLOCKED(带具体原因)。
## Why
当前 CONVERGED 只看"没活干"不看"答完没有":
orphan claim terminal 时仍准 CONVERGED(18/54 实测案例);
primary_questions 可能被 STAMP(未 BLIND)claim "答完"——这不是可信收敛。
SPINNING `_dedup_consecutive` 的 time gate 有 edge case:连续 same-state entries
间隔 >SAME_TURN_WINDOW_SEC 时被保留,但 `_flatline_run` 只看 open_count——
若 orchestrator 每 119s 调一次 convergence_check,所有 entries 被折叠成 1 个,
flatline 永远 <8,SPINNING 永远不 fire。
## Scope
- scripts/convergence_check.py: `decide()` 增加 _check_completeness gate
  - 新函数 `_orphan_terminal_claims()`: 找 terminal claims 无 answers_question
  - 新函数 `_unverified_primary_questions()`: 找 primary_questions 无 PROVEN answering claim
  - CONVERGED 路径增加完整性检查;不满足 → SATURATED/BLOCKED + 具体 reason
- scripts/convergence_health.py: `_dedup_consecutive` flatline 安全加固
  - 新增 `_has_real_flatline()` helper: dedup 后仍检测 open_count 连续不变
  - 修复: `_flatline_run` 额外检查 dedup 前的原始序列长度
- tests/test_convergence_completeness.py(新): RED1-RED4
## Acceptance
- test_convergence_completeness: RED1-RED4 全绿
- pytest 全量绿(>=201)
- openspec validate convergence-completeness-gate PASS
