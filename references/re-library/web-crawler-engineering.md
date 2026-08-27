# Web crawler engineering reference

> Domain: web targets (`--type web` workspaces) — the sustainability face of
> collection work, AFTER access is solved (`web-risk-control.md` owns "why am
> I blocked"). Field shape per section: 信号 → 定位命令 → 应对. All practices
> assume the kunglao evidence discipline: every mechanical decision (a budget
> change, an IP-tier switch, a solver introduction) lands in a claim/fact or a
> note with its trigger signal — nothing is tuned by feel.

## 会话维持 (session persistence)

Sessions are ASSETS: rebuild cost (registration, verification, warming) is an
order of magnitude above maintenance cost. Every rule below serves that
asymmetry.

| 信号/问题 | 定位命令 | 应对 |
|---|---|---|
| cookie 池分层缺失（guest 与登录态混用、共享 jar） | inventory 列 jar/profile 目录 + 检查同槽位并发写 | 三层池：guest / session / logged-in；身份槽位文件带元数据（注册时间、最后活跃、风控事件史），无元数据的裸 cookie 禁止复用 |
| 登录态过期静默失败（任务拿到的全是登录墙页） | 响应状态分布统计：401 / 302-to-login 占比随时间爬升 | 滑动刷新——token 临期前主动续期；批量 401 触发整池体检与重登排队，禁止逐请求硬闯 |
| 身份被关联封禁（一封一串） | 同池多身份的 IP/指纹/时间重叠分析 | 身份↔指纹↔出口三元组绑定表；任一角进黑名单即整组休眠观察，不再用剩余角试探 |
| storage 串号（localStorage/sessionStorage 跨身份污染） | profile user-data-dir 清单比对 | 每 slot 独立 user-data-dir；进程退出 flush+journal，恢复时校验一致性再上线 |

## 频率伪装 (rate disguise)

Machine pacing is itself a fingerprint: the defender fits your interval
distribution as cheaply as your TLS handshake.

| 信号/问题 | 定位命令 | 应对 |
|---|---|---|
| 固定间隔 sleep（方差≈0 的机器节奏） | interval 分布直方图 / std 计算，纳入 preflight 自检 | log-normal 抖动 + burst-and-idle（人类有爆发有停顿）；恒定 sleep 在 plan review 即打回 |
| 单域预算无账本（凭感觉调速） | per-domain request counter 按 分钟/小时/日 滚动落盘 | 预算表驱动调度；触顶进入冷却队列而不是换 key/换 IP 硬冲 |
| 自适应信号被忽视 | 出口延迟分布 + 拦截率滑动窗口监控 | 延迟抬升或拦截率上翘 → 自动降速一档并记录触发值；退避是正常运行不是故障 |
| 新身份被首小时烧穿 | 新 slot 冷启动行为日志回放 | 冷启动限速观察期（低频只读），逐步放开到标准档；冷启动期的每一步都可丢弃 |

频率纪律写在 plan 的 steps 里——每个采集步骤的预期输出包含"本步预算内"，
orchestrator 验计划时核对预算表存在，不要等 recall。

## IP 策略 (IP strategy)

The IP is part of the identity, not a fungible pipe. Tier choice and rotation
semantics are two independent decisions; conflating them burns sessions.

| 维度 | 定位命令 | 应对 |
|---|---|---|
| 住宅 vs 机房 | 出口 ASN 分类表标记每个代理；关键域名单独标注 | 风控敏感面优先住宅段；机房段留给探路请求、静态资源、不怕拦的高容量面 |
| 轮换语义选择 | sticky 测试：同一轮换周期内二次请求是否保持出口一致 | 会话绑定型风控必须 sticky-per-session；按请求轮换会把"设备跳跃"画成高危画像（比固定机房还贵） |
| 轮换反而有害的场景 | 封禁事件时间线 vs IP 更换时间相关性 | 登录/支付/首跳等关键动作锁定出口不变；仅在无状态列表页之间轮换 |
| 出口质量体检 | 上线前黑名单库查询 + 目标站预热探测（HEAD→GET 小流量爬坡） | 质检不过的段直接退役并登记；线上发现污染立即摘除，保留该段的失败证据供复盘 |

策略变更落 claim：住宅→机房、轮换→粘性这类切换必须有触发信号证据（哪类封禁/
哪条延迟曲线），事后可审计。

## 验证码分类应对 (CAPTCHA triage)

Classify first — each family has different cost AND a different root-cause
story. A CAPTCHA appearing at all is often a SCORE VERDICT, not a puzzle to
solve (that loop-back lives in web-risk-control.md's decision tree).

| 类型 | 特征信号 | 应对 |
|---|---|---|
| 滑块 slider | 拖拽缺口对齐交互 | 轨迹仿真：加速-减速-过冲-回弹的人类曲线族；匀速直线必挂。先问它为何出现——多数情况下修环境分比解块便宜且持久 |
| 点选 click-text / click-order | 按序点击文字或图元 | 识别服务或人工兜底走显式登记制（plan 里申报外部打码引入）；成功样本连同 challenge 材料在有效窗口内存档复用 |
| re-challenge / 无感验证 | 页面无可见交互却反复弹挑战、cookie 刚发又收 | 不要当验证码解——这是环境/行为分判决，走 risk-control 决策树 B2/B3 分支修根因；solver 通过率永远低于把分数修好 |
| 高频出现型 | 每个请求都弹，甚至静态资源也弹 | 不是验证问题而是分数崩塌：逐项核查会话/频率/IP 三节哪条违约，优先恢复到"偶尔弹"的基线再谈应对 |

红线：CAPTCHA 应对永不改变任务的声明边界（授权范围/数据用途照 task_spec 执行）；
任何外部识别服务的引入、用量、数据流向必须在 plan 与 evidence 中可见。

## 失败_budget 与止损

| 信号 | 止损动作 |
|---|---|
| 同一身份连续 N 次 CAPTCHA/challenge | 停用该身份整组（含其三元组），转人工盘点，不带伤续跑 |
| 解题成功率低于基线一半 | 记录配方 diff 后停用当前 solver 配方，回到分类重选 |
| 预算持续超支三档退避仍不收敛 | 升级 blocker（附已调参数与观测曲线），交 orchestrator 重排优先级 |

止损产出的每次数据（成功样本、失败 pair、命中率）都是下一个 site note 的原料
——采集工程的知识复利靠 note 制度，不靠个人记忆。

## 采集节奏与站点画像

| 信号/问题 | 定位命令 | 应对 |
|---|---|---|
| 多站点无差别共享节奏与预算 | per-site budget/rate 对照表是否存在 | 每站点独立画像（防御形态、基线延迟、预算档、CAPTCHA 频率史），新站点从最保守档起步 |
| 站点改版/风控升级未察觉 | 基线探针（每周一次只读访问记录成功率与耗时） | 探针异常先于业务受损发现；触发 risk-control 域的识别流程复核 |
| 经验不沉淀，同站反复踩坑 | notes/site_<domain>.md 是否存在并被新会话首读 | 防御形态、已验证解法、踩坑清单三段式 note；下一个案例开浏览器前必读 |

## 与其他层的衔接

- 环境被判死 → `web-risk-control.md` 对抗决策树（J6 无头升级链在内）；
- 参数算不出 → `web-re-quickref.md` 签名定位工作流；
- 方法耗尽 → LEARN 梯级（worker 契约）：内查 re-library 不满足，再 WebSearch 外部
  检索（同族先例/已知解法/报错特征），检索结果按 evidence 纪律记 URL+日期。
