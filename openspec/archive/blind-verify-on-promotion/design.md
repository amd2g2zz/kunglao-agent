# Design — blind-verify-on-promotion

## 门判据

claim_migrator 是 orchestrator 提升 claim 的唯一正式入口(CLI kunglao-record.py --claim-migrate)。当前它拦 worker(非 orchestrator actor 写 terminal → 拒),但 orchestrator actor 写 PROVEN 无任何 BLIND 检查。这是 46/47 假 PROVEN 的直接根因。

### 核心函数 blind_gate.check_proven_gate

```
check_proven_gate(claim_id, facts_dir) -> (allowed: bool, effective_status: str, reason: str)
```

判据链(短路):
1. claim 不是 → PROVEN → (True, requested_status, 'not a PROVEN promotion')
2. fact file 不存在 → (False, 'STAMP', 'no fact file for <cid>')
3. fact 无 verifier_sign_off block → (False, 'STAMP', 'verifier_sign_off missing')
4. verifier_sign_off.verdict == REFUTE → (False, 'STAMP', 'BLIND verifier REFUTED')
5. verifier_sign_off 完整(verifier_id + sign_off_at + refute_attempt) → (True, 'PROVEN', 'BLIND verified by <id>')

### 降级 vs 拒绝

claim_migrator 用**降级**:PROVEN 请求无 BLIND → 写 STAMP 而非拒绝。理由:
- 信息不丢失(claim 仍被追踪,标 STAMP = 不可信)
- PRD M1 原文"无签字自动降级 STAMP"
- orchestrator 不需重试;显式承认"这条还没验"

worker_budget.compare_register_change 用**拒绝**(register 直写绕 claim_migrator 的旁路)。理由:hook 是最后防线,register 已被改 → 仅 reject signal;但 gate 仍标注 STAMP 要求 orchestrator 回收。

### STAMP 状态

新增 `STAMP` 到 claim 状态集(与 PROVEN 同列但语义 = "自章未验")。STAMP 不是 terminal(可后续补验升 PROVEN,或翻 REFUTED)。ledger 记 `claim_promoted` payload.status='STAMP'。

### verifier_sign_off block 格式(复用 doubt_checker.py L70-84)

```yaml
verifier_sign_off:
  verifier_id: kunglao-redteam-w2
  refute_attempt: "tried X, Y, Z to break; held"
  sign_off_at: 2026-08-10T14:00:00Z
  verdict: CONFIRMED   # CONFIRMED | REFUTE
```

verifier_id == worker_id → self-stamp → 拒(doubt_checker L112 同判据)。

### measure_blind_coverage.py

读 claim-register.yaml(全 claims)+ facts/*.md(逐条 has_verifier_sign_off)。输出:
```
PROVEN: 47
BLIND-signed: 1
coverage: 2.1%
UNVERIFIED(STAMP candidate): 46
```
exit 0 always(度量非门)。--json 输出机读。
