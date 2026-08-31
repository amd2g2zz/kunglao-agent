# Proposal: 重做方向的盲性缺口 — REDO slice 机械过滤 + 契约三处 + 泄露 WARN (#772)

## Why

#527 的 BLIND 硬排除只保护 **verifier 输入侧**（dispatch_context.py L373
BLIND slice）。**反方向零防护**：verifier 反馈和 worker 不一致、orchestrator
裁决重做时，红队 DIFF（含独立推导值——sample-incident-01 真实案例
"producer claimed anchor 3494, actual 3446"）若直接进重做 prompt，
worker 照答案改。第二个"独立推导"只是抄 checker——maker-checker 全链
在重做这一跳失效。

脱敏边界（本 issue 的核心语义）：

- worker **知道**："错在哪"（GAP 形态：field mismatch / 假设被质疑 /
  替代方法方向）
- worker **不知道**："对的是什么"（红队的推导值 / 结论 / 锚点答案）

## What Changes

- **L1+L2（T1）**: `scripts/dispatch_context.py` 增 `build_redo_context(ws,
  diff_path)`——对称 #527 的 BLIND slice。读红队 DIFF 实际落盘形态
  （取证：`runs/verify-redteam-<target>.md`，issue 猜测的
  `runs/redteam-status-C*.md` / `evidence/redteam-*.json` 不存在）；
  节级丢弃（独立推导正文 / machine_check fence——它们载荷答案）+
  行级丢弃（actual/expected 引导的结论行）+ token 级清洗
  （hex 8+/十进制 ≥3 位/0x 地址），超额脱敏可接受（漏掉答案不可接受）。
  输出 GAP 形态 dict：divergence_class / gap / challenged / hint_direction。
- **L3（T2）**: 契约三处——SKILL.md §1b 对称条款（verifiers must be BLIND;
  re-dispatches must be GAP-ONLY）、kunglao-worker 重做措辞（你收到的是
  GAP 不是答案——如果新结论恰好等于 DIFF 里出现过的值但你没独立推出来，
  那是失败不是通过）、kunglao-redteam 输出段（DIFF 的读者是 orchestrator
  裁决层，不是下一版 maker prompt 的素材；结论行仍写全，泄露防护在
  REDO slice）。
- **L4（T3）**: `hooks/dispatch_gate.py` 增 `_redo_leak_check`（I1 的
  `_tools_rack_gate` 旁的结构走廊）——prompt 含 redo/重做标记且与最近
  verify-redteam DIFF 的数值串（≥4 位数字 / ≥16 位 hex）有交集 →
  stderr WARN + additionalContext（不 REJECT——启发式误报代价高，WARN
  让 orchestrator 自查）。FAIL_OPEN。

## Out of scope

- 不改红队 DIFF 的写出格式（它的读者是裁决层——泄露防护在 dispatch_context
  的 REDO slice，不在 redteam 写出侧）。
- 不做提示词语义级"NLP 抄袭检测"——L4 是数值交集启发式，精度换零依赖。
