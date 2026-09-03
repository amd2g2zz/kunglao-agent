# Change: issue-828-expected-hashlock

## Why

kunglao-verify 的 F3（`check_expected_anchor_source`，kunglao_verify.py:282）只防**同义反复**（producing script 内嵌 expected）；防不住**顺序改写**：maker 跑 verify → L1 FAIL → 把 fact frontmatter 的 `expected:` 改成观测输出 → 重跑 → PASS。事故时间线（F008：FAIL 后 8 秒改 expected_sha256 → VERIFIED；F017：7 连 REJECTED 后手工对齐 expected → PASS）。改 expected = 改评分标准 = 假胜利后门。

## Gates Already Covered (F1-F6)

F3 覆盖面：expected 不得由 producing script 自算。缺口：**时序改写**无门。

## What Changes

1. **expected hash 锁（rewrite-after-fail gate）**：每次 verify 在输出 JSON（runs/verify-<fid>-<ts>.json，天然 append-only）记录 `expected_hash`；新 run 先扫该 fact 的历史 JSON（mtime 序），若**上一条 L1=FAIL 且 expected_hash 变化** → lint 级 `EXPECTED_TAMPERED`（fail-closed，overall=REJECTED，不予晋升）
2. **justification 通道**：fact frontmatter 携带非空 `expected_correction: <reason>` → 放行（correction 进 lint reason 与 ledger detail，审计可见）
3. **首锚幂等**：无历史 → 首跑即锚；同 expected 重跑零打扰
4. **支撑修复**：verify 输出文件名同秒碰撞加 `-k` 后缀（否则同秒两跑互相覆盖 → 历史被抹，锚失效——门的结构性前提）

## Decision: 锚载体选型

**verify JSON 历史即锚**（issue 指定方向），不引入 .lock 侧车：verify-<fid>-*.json 天然 append-only + 时间戳命名，无第二真相源漂移问题；maker 改历史 JSON = 篡改 verify 证据本身（属其他篡改面管辖）。

## Impact

- scripts/kunglao_verify.py：verify() lint 链 +1 门、输出 +1 字段、文件名碰撞修复
- 无 schema 破坏：expected_hash 为新增字段
