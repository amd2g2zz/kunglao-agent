# Design — failure-lessons (#41)

## Design Decisions

### D1. `--record` 增加可选 `--outcome` / `--what-happened`, 旧文件零迁移

`analyses/failure-<claim>.yaml` 新增两个**可选**字段:

```yaml
claim: C-1
covers_attempt: 3
method_assumption: "grep 静态字符串能直接看到 IOC"
assumption_validity: not-justified
next_method: "运行时构造 IOC — Frida hook syscall.SyscallN"
outcome: PROVEN            # 新增, 可选: PROVEN|VERIFIED|REFUTED|NEGATIVE
what_happened: "Frida 抓到 NtCreateThreadEx 注入 chrome.exe, IOC 全部运行时构造"  # 新增, 可选
analyzed_at: "..."
```

- `_analysis_covers` / `scan_workspace` / `hooks/dispatch_gate._failure_blocked_ids`
  全部只读 `covers_attempt` 与 claim 状态 — 新字段是纯增量, 旧文件照常解析
  (yaml.safe_load, `.get` 缺省)。**向后兼容, 零迁移**。
- 校验(与 gate 现有 `--validity` 严格风格一致): `--outcome` 必须是
  `PROVEN|VERIFIED|REFUTED|NEGATIVE`(大小写归一为大写; 用元组常量
  `OUTCOME_VALUES`, 不定义任何 `TERMINAL = {` 集合 — 避免触发
  `test_status_defs.test_consumer_has_no_own_status_set` 的 grep 守卫);
  `--outcome` 与 `--what-happened` 必须同给同缺。
- **回填不覆盖**: claim 关闭时 orchestrator 只需重跑
  `--record C-1 --outcome PROVEN --what-happened "..."`; 已有 entry 的
  method_assumption/validity/next_method/analyzed_at 在未重传时**保留**(读到
  旧 entry 做字段级合并), 只有 outcome/what_happened 是新写的。失败时刻的分析
  内容不会被关闭时刻的调用冲掉。

### D2. 聚合模式 `--lessons`: 按失败签名分组, 幂等写库

```
python scripts/failure_analysis_gate.py <ws> --lessons [--library DIR] [--reflect-queue FILE]
```

- 失败签名 = `(method_assumption, next_method, claim_topic)` — issue 明示
  "method + assumption + claim topic"。`claim_topic` 取 claim 的 `topic` 字段,
  无则用 statement 归一化(小写 token 化取前 120 字符); claim 不在 register 则
  用 claim_id。
- 签名 → 文件名: `lesson-<slug10>.md`, `slug = sha256(signature 规范化串)[:10]`。
  同签名 → 同文件名 → **天然幂等**(已存在则跳过, 不覆写)。同签名多 claim →
  首次写入时一份文件列出全部来源 claim(分组聚合)。
- lesson 文件 = YAML frontmatter(method_assumption/assumption_validity/
  next_method/claim_topic/outcome/sources/created_at) + 正文(每个来源 claim 的
  what_happened 逐条列出)。

### D3. 闭环门禁: 只入库已验证 outcome

"闭环"判定(纯函数, 无 LLM):

| outcome | 入库条件 | 否则进 /reflect 队列 reason |
|---|---|---|
| PROVEN / VERIFIED | 恒成立 | — |
| NEGATIVE | ledger 有 `{claim_id, checker: red-team, result: CONFIRMED}` OUTCOME 行(#35 的 outcome_capture 已把 `runs/verify-redteam-*.md` 落成该行) | `negative-unverified` |
| REFUTED | 永不 | `refuted` |
| (无 outcome 字段) | 永不 | `no-outcome` |

- 红队行读取复用 `outcome_capture.read_outcome_rows(workspace)`(纯读 ledger,
  不触发 capture 副作用)。
- /reflect 队列文件 = claude-reflect 的 `learnings-queue.json`(JSON **数组**,
  非 JSONL; 默认 `~/.claude/learnings-queue.json`, `--reflect-queue` 可覆盖 —
  测试写 tmp)。条目格式沿用插件 schema
  `{type, message, timestamp, project, ...}` + 附加
  `claim_id/outcome/reason/next_method/method_assumption`;
  `type="failure-lesson-candidate"`。幂等: `claim_id|reason` 已存在则跳过。

### D4. BLOCKED 输出附 top-3 相似 lesson(检索从小起步)

- `check_claim` BLOCKED 结果增加 `similar_lessons`: 对库中每份 lesson 文件,
  用 claim statement + claim_id 的 token(小写, `\w{3,}`)对 lesson 全文做
  关键词 overlap 打分, top-3(按 -score, 文件名决胜); 库空 → `[]`。
- `scan_workspace` 签名保持 `(workspace)`, 新增 `library=None` kwarg(缺省
  DEFAULT_LESSONS_DIR)— `convergence_check._failure_blocked` /
  `priority.py:144` / `hooks/dispatch_gate` 调用零改动。读库是纯只读, 不影响
  既有 BLOCKED 决策路径。
- `--search <kw>` CLI 模式复用同一打分函数, 打印命中 lesson 的
  topic/outcome/score。

### D5. 默认库位置与可测性

- `DEFAULT_LESSONS_DIR = ~/.claude/skills/kunglao-agent/references/lessons/`
  (issue: 库在全局 skill references/ 下, 跨样本; 与 case-book.md 同级)。
- 所有写库/写队列的入口都接受 `--library` / `--reflect-queue` 显式路径 —
  测试全部指向 tmp, 生产默认路径永不被测试触碰。

## Rejected Alternatives

- **R1. 每 claim 一个 lesson 文件**(不分组): 同签名 3 次失败 → 3 份几乎相同的
  lesson, 检索噪声大; issue 明示"按失败签名分组"。
- **R2. lesson 直接存 workspace**: 违反 issue"跨样本, 不存 workspace" —
  单样本教训无法被下一样本检索。
- **R3. outcome 写成独立 ledger 行**: outcome 属于 failure analysis entry 的
  生命周期, 不是 convergence ledger 事件; 写在 analyses/ 里保持单点事实源,
  ledger 只供 red-team 幸存判定只读。
- **R4. NEGATIVE 无条件入库**: 未过 red-team 的 NEGATIVE 正是 C-13 事故
  (水处理模拟器诱饵 → score 3 → 0)的温床; 必须要求红队 CONFIRMED。
