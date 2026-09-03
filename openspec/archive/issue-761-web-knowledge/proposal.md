# Proposal: web 知识与认知层 — 风控对抗/爬虫知识库/sequentialthinking 契约/planning 状态机/recall 反馈环/WebSearch (#761)

## Why

J 组 5 项（web 域为主）+ 评论区两条追加裁决，2026-08-27 现场代码锚：

1. **re-library 零覆盖风控对抗与爬虫工程** — `references/re-library/` 34 个文件里
   web 域只有 `web-re-quickref.md`（hook 手法/剥离流程），"请求为什么被拦、被拦了怎么办"
   （风控信号→定位→应对）与"访问打通之后怎么可持续采集"（会话/频率/IP/验证码）
   完全没有承载文档。live-run sample 类任务的刚需知识散落在 worker-status 遥测里。
2. **sequentialthinking 列在 7 个 agent 的 allowedTools 但契约零处**（grep 全仓：
   只有 `scripts/mcp_probe.py` 注册行）——worker 遇到签名推导/风控决策树这类多步
   推理时不知道要走结构化思考链，思考轨迹也不落 fact derivation。
3. **plan 一次性静态** — `runs/plan-C*.md` 没有状态机（pending/in-flight/blocked/
   superseded），重规划没有增量修订记录（revision 段），#602 的 plan_drift 只做
   事后比对不做触发式建议。
4. **recall 单向无反馈环**（#268 注入后无人评价命中质量）+ **WebSearch 与内查
   无梯级关系**（LEARN 直奔 WebSearch，绕过 re-library 内查）。

## What Changes

- **J1 (T1)**: 新建 `references/re-library/web-risk-control.md`（信号分类学 / 对抗
  决策树含 J6 无头升级链 / 风控栈识别加速乐·瑞数·自研 / 检测点定位 触发→观察→归因
  loop 含 J7 插桩落地列）+ `references/re-library/web-crawler-engineering.md`
  （会话维持 / 频率伪装 / IP 策略 / 验证码分类应对）；收录 `_INDEX.md` 域表 + 场景表
  + 目录行 + 两份 `_index-<domain>.md`；`_INDEX.yaml` re-pin；`recall_inject` 增
  WEB_SIGNALS → "risk control"/"crawler" 查询映射。
- **J2 (T2)**: kunglao-worker 复杂推理契约段（权威源——签名算法推导/加密参数溯源/
  风控决策树遍历/多步假设链必须走 sequentialthinking 链；思考轨迹摘要进 fact
  derivation）+ kunglao-redteam 攻击路径枚举契约（枚举攻击面→逐路径假设→反证）。
  #759 THINK 席位引用此文案作单一源。
- **J3 (T3)**: plan frontmatter 增 `status: pending|in-flight|blocked|superseded`
  + `revision: N`；新 `scripts/plan_reviser.py` 三触发器机械检测（blockers/ 阻塞
  升级 / 新 PROVEN fact 与 plan 假设关键词级冲突(只标记 suggest_revision) /
  cost_advice.json 超阈）→ 建议输出；`--apply` 追加 `## revision-N` diff 可审计；
  SKILL.md orchestrator 契约：收到 suggest_revision 必须产出 revision 段。
- **J4 (T4)**: DONE 行模板增 `| recall_useful: yes|no|misleading`；lib_kunglao 单点
  解析同型 helper；references_recall 统计 runs/.recall-stats.json per-term 质量 +
  连续 3 次 misleading 的降权建议清单（人工裁决，不自动删改——lessons nursery 同型）；
  recall_inject 触发面增红队 dispatch 前（对抗知识注入）；THINK 不 hook——改为
  references_recall 联合查询构造（claim 文本 + facts/_INDEX 前 N 行标题）供 #759。
- **J5 (T5)**: worker LEARN 梯级扩两级：先查内部（re-library + references_recall）
  → 不满足再 WebSearch（同族先例/已知解法/报错特征）；evidence 纪律：WebSearch 进
  fact 必须记 URL+检索日期于 derivation、不得直接当 PROVEN 依据（verifier 盲验后才可）。

## Out of scope

- agents/web-re-worker.md（#760 I4 领地）
- web-re-quickref.md 的 J6/J7 章节编辑（并入 #760 验收）
- recall 降权自动删改词典（人工裁决面，只输出建议清单）
- #606/#605 的 plan 交互式重排（本波只做状态机+增量修订触发器）

## 安全面

- recall_inject 保持 FAIL_OPEN/rc=0 纯注入语义不变
- plan_reviser 默认 --check 只读+rc=3 建议面，--apply 只追加不重写
- recall-stats 只是运行时统计文件（runs/.recall-stats.json），不触碰任何用户数据目录
