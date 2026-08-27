# Design: 重做方向的盲性缺口 (#772)

## D1 — 用户裁决（原文）

> "如果 verifier 反馈和 worker 不一致，orchestrator 收到之后这个工作要重做，
> 在 prompt 要给出 critic 信息但不能直接泄露，否则会出现作弊现象。"

（2026-08-27 裁决记录于任务书；落地为 GAP-ONLY 契约 + 机械 REDO slice。）

## D2 — 缺口取证

| 面 | 锚 | 现状 |
|---|---|---|
| verifier 输入侧（已防护） | scripts/dispatch_context.py L373 `verifier_dispatch_view` + VERIFIER_SAFE_KEYS frozenset（#527） | OK |
| 红队 DIFF 实际落盘 | agents/kunglao-redteam.md 输出契约：`runs/verify-redteam-<target>.md`（issue 猜测的 `runs/redteam-status-C*.md` / `evidence/redteam-*.json` 全仓不存在——按任务书要求先取证） | 唯一消费者是裁决层（kunglao_verify.py 机器检扫同一 glob） |
| redo 反方向（零防护） | orchestrator 把 DIFF 进重做 prompt 无任何过滤面 | 本波落点 |

真实案例形态（sample-incident-01）：DIFF 含 "producer claimed anchor 3494, actual
3446"——任何一处数字直接进 redo prompt，worker 的第二个"独立推导"即被污染。

## D3 — REDO slice 机械过滤（L1+L2）

对称 #527 BLIND slice 的 FAIL_OPEN 姿态；`build_redo_context(ws, diff_path)
-> dict` 永不 raise。三层机械过滤：

1. **节级**："My independent derivation" 正文 = 红队自己的推导（即答案）→
   整节置 redacted 占位；``` fenced block（machine_check 载 expected/actual
   字面值）→ 内容丢弃。保留：标题行 / Attack attempts / VERDICT 行 /
   GAPs 节。
2. **行级**：actual/expected 引导的结论行、producer claimed+数字行、
   derived/recomputed 结论行 → 丢行（English-only on principle，同
   _DISPATCH_MUST_STOP_PATTERNS 先例）。
3. **token 级**：0x 地址 → `<redacted-addr>`；hex ≥8 → `<redacted-token>`；
   十进制 ≥3 位 → `<redacted-num>`（claim/fact id 引用 F\d{3}/C-\d{3}
   先 sentinel 保护再还原——它们是 bookkeeping 不是答案）；超额脱敏可接受，
   漏答案不可接受。

输出契约（测试钉死）：`{version, kind: "REDO", diff_ref, claim_id,
verdict, divergence_class (anchor_mismatch|method_challenged|evidence_gap|
unclassified 关键词归类), gap, challenged[], hint_direction, sanitized:
True, redactions}`。缺文件 → error 标记的 honest 空 slice。CLI 对称加
`--redo-diff`（对 `--verifier-blind`）。

## D4 — 契约三处（L3）

- SKILL.md §1b 行（Orchestrator guardrails 紧凑段）：追加 "re-dispatches
  must be GAP-ONLY (#772) — the redo prompt carries WHERE it diverged,
  never the verifier's derived answer"。
- agents/kunglao-worker.md Dispatch format 段后新增重做盲性条款
  （你收到的是 GAP 不是答案——独立重推；恰好等于 DIFF 出现过的值但非独立
  推出 = 失败不是通过）。
- agents/kunglao-redteam.md Output format 段注明 DIFF 读者是裁决层（#772），
  结论行仍写全；泄露防护在 dispatch_context REDO slice。
- 守门：agents_lint 三要素 structural marker 不受影响；文本断言三处锚点。

## D5 — 泄露启发式 WARN（L4）

`hooks/dispatch_gate.py::_redo_leak_check(ws, prompt_text)` 挂 I1
`_tools_rack_gate` 同一结构走廊（解析出 claim 后、activation 判定前——
泄露不是 session-level concern）。触发：prompt 含 redo/重做 且 与最近
`runs/verify-redteam-*.md` 提取串（≥4 位数字 / ≥16 位 hex）有交集 →
stderr WARN + hookSpecificOutput additionalContext + `redo_leak_warn`
trace（EMIT_ACTIONS 注册一个 emit-face 词，照 #459 纪律）。返回 None
恒不 REJECT（启发式误报代价高）。无 ws / 无 DIFF / 读失败 → 静默 fail-open。

事件词表注册：`redo_leak_warn`（唯一 emit face）。

## D6 — Known limitations（r1 审查后裁决记录，2026-08-27）

1. **节级 withhold 入节判定（F1，r1 FAIL 项）**：`_sanitize_diff_body` 的
   marker 比较原样吃掉了 MD `#` 前缀——真实契约形态
   `## My independent derivation` 从不入节，独立推导正文只靠行级正则/
   数值清洗侥幸兜底；小值锚点（"...correct descriptor index is 9." /
   "The correct field number is 6..."）即由此漏进 slice。修复：比较前
   `lstrip("#").strip()`，并以占位符出现性 + 两句实测泄漏句缺席性双钉扎。
2. **<3 位小值锚点改述风险（残留）**：行级正则不命中的小值结论句若落在
   非 withhold 节（如 Attack attempts 正文），十进制规则（≥3 位）与 hex
   规则均不打——单字符级语义改述仍可能存活。接受理由：红队契约
   （agents/kunglao-redteam.md 规则 1-7）本身把这些值锁在 independent
   derivation / machine_check 结构里，逃逸面小；升级到 NLP 级过滤
   （提议否决）精度无法保障且引入误杀面。
3. **全数字清洗打瞎 GAP prose 的取舍**：GAP 文中的合法数值指针（如"搜过
   0x4000-0x5000 窗口"的窗口本身）同样被 redact——这是"漏答案不可接受、
   超额脱敏可接受"裁决的直接代价。补救路径：orchestrator 需要精确窗口时
   用原始 DIFF（裁决层读者），不把 REDO slice 当唯一事实源。

## 附注 — quality gate 基线

定向套件与全量套件对照 origin/dev@1b6532b 基线跑；pre-existing 失败
（若有）需逐条复现核对后再判非本波回归。
