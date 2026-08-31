# issue-829-carrier-consistency

## Why

四载体（claim-register / facts/_INDEX.md / facts/*.md / notes/*.md）各自漂移无对账——#825 事故复盘实锤：register 修正后 _INDEX 仍 14+ VERIFIED、notes 仍批量 verify_status=passes、fact frontmatter status 与 verified 字段互相矛盾、verified_by_run 引用已隔离文件。每载体各有 lint 但无 pairwise 门，下一次循环即可从假绿 notes 重新判出 CONVERGED。

## What Changes

- 新 `scripts/carrier_consistency.py`：check(ws) → {ok, violations, checked}，五规则：
  (a) register stamped claim (PROVEN/VERIFIED) ⇔ linked fact stamped（双向）
  (b) _INDEX 行状态 == fact frontmatter status
  (c) notes verify_status=passes ⇒ 引用 claim 的 linked fact `verified: true`
  (d) fact `verified_by_run` 引用文件存在
  (e) claim-register.yaml 重复 YAML 键（strict loader）
- 挂接 convergence_check.decide()：CONVERGED 前置跑；violations（含检查器自身异常）→ 降级 DISPATCH + carrier_drift 事件落账；只拦 CONVERGED 不拦其余决策，不引入 deadlock
- CLI face（--json，exit 0/1）供 operator 直查

## Impact

- Affected: scripts/carrier_consistency.py（新）、scripts/convergence_check.py（decide 挂钩）、scripts/README.md（catalog 行）、tests/test_carrier_consistency_829.py（新）
- 状态机语义零改动；既有测试零回退
