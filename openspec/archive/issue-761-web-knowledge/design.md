# Design — #761 web 知识与认知层

## 用户裁决（原文 + 日期，依序四条）

1. **风控/爬虫知识 web 域专用**（issue #761 正文，2026-08-27）——
   "J 组补强 5 项 web 域为主……风控对抗知识属于 web 域专用：不进 malware 域参考，
   只挂 `--type web` 场景与 recall 词典"。
2. **seqthink 正名 sequentialthinking**（2026-08-27 裁决）——契约措辞一律用
   MCP 工具真名 `mcp__sequential-thinking__sequentialthinking`（工具已在两 agent
   的 allowedTools），不再写 "seqthink" 简称。
3. **无头优先**（issue #761 评论，2026-08-27 原文）——
   "web 工程要补充一点，浏览器 mcp 尽量用无头，除非风控太厉害了可以启用 headfull。"
4. **调试插桩一等能力**（issue #761 评论，2026-08-27 原文）——
   "camoufox-mcp 是可以调试和插桩的。这在 web 项目里面很重要。"

## 决策

### D1 — J1 挂两个新域而非塞进 web-labs

域表每行 = 一个 `_index-<domain>.md`，召回时 domain token 权重独立
（W_CAT_DOMAIN=2.0）。`web-risk-control` 与 `web-crawler-engineering` 各自成域：
场景表新增一行 "Anti-bot decisions & crawler ops (风控/爬虫)" → 两域并集；
web-labs 保持 peeling/hook 手法定位不动（#760 领地，避免并行冲突面）。
目录行 purpose 中英双语（EN 词保证 ASCII tokenizer、CJK 保证 unigram/bigram）。

### D2 — J6/J7 入 J1 文档而非 quickref

评论区裁决的落地落点写明是 "web-re-worker 契约 + quickref 动态面章节"
（#760 I4 验收增量）；本波把裁决内容织入 J1 新文档承载的方法论本体：
- 对抗决策树第三层即无头升级链：headless 默认 → 反无头指纹信号清单（可判定）
  → 指纹仿真 → headful 最后手段；
- 检测点定位 loop 的观察步给 camoufox 执行列（CDP 断点 / evaluateOnNewDocument
  注入 / DOM 断点监听 cookie-storage 写入；headless 下 CDP 行为一致）。
#760 编辑 quickref 时反向引用本文件即可。

### D3 — J2 是 sequentialthinking 契约唯一权威源

权威段放 `agents/kunglao-worker.md`（`<!-- contract: sequential-thinking -->`）
+ `agents/kunglao-redteam.md` 各一段（攻击路径枚举专用措辞）。#759 THINK 席位
引用 worker 段原文。触发器写成可枚举的四类（签名算法推导/加密参数溯源/风控决策
树遍历/多步假设链），附输出纪律（轨迹摘要进 fact derivation 可审计，不是全文倾倒）。

### D4 — plan_reviser 三触发全机械可判定，建议与执行分离

| 触发 | 机械信号 | 输出 |
|---|---|---|
| blocker 升级 | `blockers/<claim>.md` 存在且 mtime > plan revision 时间戳、该 claim 有 plan | suggest(blocker) |
| fact 推翻假设 | facts/*.md status: PROVEN 且与 plan `assumptions:` 行关键词重叠 ≥2 个 token 且 mtime 更新 | suggest(assumption) — WARN-only |
| cost 超阈 | `runs/cost_advice.json` tier == advisory（cost_gate 写入信号） | suggest(cost) |

`--check` rc: 0 无建议 / 3 有建议（对齐 plan_drift_detector 的 SATURATED 观察面，
绝不 block）。`--apply` 只做增量追加：frontmatter revision++ + 追加
`## revision-N`（时间戳/触发/变更步骤/原因），历史 revision 段永不重写
（diff 可审计）。实际修订由 orchestrator 按 SKILL.md 契约执行。

### D5 — recall 反馈环最小闭环

采集：DONE 行 `recall_useful:` 由 lib_kunglao 单点解析（parse_declared_notes 同型，
单值白名单 yes/no/misleading）；统计在 `references_recall.py --record-feedback /
--feedback-stats <ws>` 写 `runs/.recall-stats.json`（per-term 计数 + 连续 misleading
streak）。降权只输出建议清单（连续 ≥3 misleading），词典本身不动 —— lessons
nursery (#525) 同型人工裁决。红队 dispatch 注入走 recall_inject 既有 FAIL_OPEN
路径（REDTEAM_RE 判定，rc 恒 0）。THINK 前**不 hook**（脚本动作）：新增
联合查询构造 `--joint <workspace>`（claim 文本 tokens ∪ facts/_INDEX 前 N 行标题
tokens），供 #759 think 调用前置知识注入。

### D6 — WebSearch 是 LEARN 第二级不是替代

worker LEARN 条目改两级梯："先查内部（references_recall 命中 re-library）→ 不满足
再 WebSearch（同族先例/已知解法/报错特征）"；evidence 纪律两条硬规则：URL+检索日期
必须记 derivation；外部检索结果不得直接支撑 PROVEN（verifier 盲验之后才可）。
operational-mechanics.md 的三行梯同步（机械面孔）。

### D7 — decide 冻结锚刷新（corpus 增长的连带维护）

J1 在 `references/re-library/` 新增两个知识文档 → `anomaly_detector` 的 baseline
corpus（Source: re-library refs，#663）随之增大 → lexical 维度分数小数位漂移
→ channel-2 冻结快照 (`tests/decide_anchor_8804dcd.json`) 两个 case 失配。
处理遵循 #357 判例（移动数据源必须同提交移动 pin）：
- channel-1（live-vs-c5cb1ae 逻辑等价，63 测中的硬护栏）保持全绿——证明仅
  corpus 变化、无逻辑回归；
- channel-2 按其文件头注明的机生成路径机械重刷漂移 case
  （`.tmp/regen_anchor_761_corpus.py` 留档），diff 仅 4 行分数。

## Risks

- recall_inject 加查询会改变既有 dispatch 注入文件集合 → WEB_SIGNALS 全部为
  多词复合/CJK 锚点，既有测试 fixture 文本零命中（test_recall_inject 不动）。
- .recall-stats.json 在 runs/ 下属 workspace 运行态：init/upgraded 清点不看它；
  命名 dot-file 避免被 runs 遍历消费方当 report 读。
