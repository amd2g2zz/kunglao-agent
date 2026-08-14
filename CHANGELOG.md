# Changelog

本项目全部显著变更记录于此。格式遵循 [Keep a Changelog 1.1](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 PEP 440。v0.1 之前的内部迭代版本号 (v1.9.0–v1.9.38) 是开发期标记，
统一折叠进 v0.1 首发（见文末映射表）。

## [0.1.0] - 2026-08-14

首个公开版本：收敛驱动的逆向工程编排 skill —— 以 Claude Code 为唯一界面，
把恶意样本带到字节级证明、独立验证的事实库，全程由机械门禁强制。

### Added

- 收敛循环内核 — decide/tick/verify/record/health 五子命令 router，dispatch→blind-verify→CONVERGED 闭环由 completion gate 机械裁定 (#93)
- 三型工具链矩阵 + 类型感知初始化 — Windows/Linux/Android 各自的最小工具链探测与 workspace 拒绝未初始化 (#304)
- 五层分析阶梯 — init 阶段固化 L1-L5 深度承诺，防止 worker 越层空转 (#304)
- 证据完整性 — evidence/_index.json 全量索引，每条 fact 追溯到原始工件，派生摘要在设计上被排除 (#140)
- ICD-203 对齐 — kunglao facts 与 malware-veri-notes schema 完全对齐 + fact frontmatter 模板 (#336)
- 事实引用图 — fact 间引用的图结构校验，孤儿/断链在 CI 拦截 (#140)
- OPERATOR_ACTION 台账行 — 审计轨迹覆盖人工介入 (#142)
- 写侧门禁 — maker-checker 盖章回验 + 独立锚点 + defer 引用可回查 (#236)
- 心跳体系三件套 — touch/tick/selfcheck：活动性以心跳为准（时间戳不作数），dispatch 前置校验心跳存活 (#287)
- claim 撤回链 — RETRACTED 终态 + claim_deps 爆炸半径重开 (#331)
- 校准门禁 — 交付要求 confidence + falsifier，calibration/oracle 模板持久锚定 (#204)
- plan-to-execute 与 tool-first 门禁 — claim dispatch 必须带可执行计划，文本命中工具时强制工具路径 (#294)
- specialist-first 派发门禁 — agenttype 机械校验，专家先于通才 (#310)
- 可执行预言机契约 — verifier 验证记录必须含 machine_check (#332)
- 三类型工具链矩阵 + tools/_INDEX 分域索引 — 工具家目录、validate_index、分域登记与结构完整性 CI (#283)
- 静态分析工具集 12 件 — binary-sweep/disasm-dump/stack-strings/go-buildinfo-carve/pe_analyze 等 (#278)
- Ghidra 工具集 — 5 个 Java 脚本 + postScript 包装器吸收进 tools/ghidra/ (#293)
- Ghidra 异步作业协议 + 二进制 diff — 长任务转后台作业 + Bindiff (#308)
- Ghidra 运行时侦察 — Recon/ScanPointer/ExportVtableStruct/EvidenceAnnotations (#320)
- crypto 算法库 8 算法 + CLI — 去重 15+ 处算法识别逻辑 (#285)
- yara-scan / yara-gen — 规则式扫描与检测规则生成 (#313)
- frida 动态模板 + 脚本生成模板 — cfg-analyze/cfg-hook + decryption/disasm/stage-unpack，Windows 路径转义可执行 (#335)
- 5 个 pipeline recipes — crypto-decrypt/go-recovery/iat-chain/stage-unpack/syscall-chain (#287)
- capability router + 确定性工具查询 — 样本特征探测路由到工具 (#302)
- 反编译产物后处理 — C 规范化器 + z3 不透明谓词消解 (#306)
- 运行时知识召回 — recall_inject hook 按 claim 特征注入 references (#268)
- references 检索工具 — 场景/类别/文件名匹配 + 渐进披露输出 (#229)
- 结构化事件日志 + TUI 状态面板 — 磁盘渲染的监控视图 (#287)
- 9 个独立 CLI + 统一 router — kunglao{,-decide,-verify,-record,-monitor,-init,-eval,-digest} + mcp_probe (#316)
- MCP 供给机制化 — 探针 + .mcp.json scaffold + 分型供给表 (#316)
- 发布契约 — release-manifest + release receipt 校验资产/CLI 清单并绑定知识库 revision (#80)
- 评估体系 — evals.json 3 项 eval + oracle selfcheck 入 CI (#117)
- 观测性 — outcome_capture 历史进入优先级排序 (#122)
- prompt 注入 sanitize — 样本内容威胁分类内化自研 (#307)
- 文档体系 — LICENSE/AGENTS.md/README/DESIGN/references 分层导航 (#116)

### Changed

- CLI 收敛 31→9 — 独立入口压缩到 9 个，其余并入 router 子命令 (#230)
- scripts 治理 — 70 脚本审计（0 孤儿/0 断链）+ smoke launcher (#230)
- tools/ 目录规范化 — 根层归位 + 双 common 合并 + 类目 id 对齐 (#340)
- SKILL.md 契约化重写 — 顺序工作流 8 节 + 命令式语态 + 占位符化 (#226)
- SKILL.md 渐进披露修正 — 去 DESIGN/issue 号/版本号引用，索引统一 _INDEX.md (#261)
- CTF→RE 身份统一 — 13 文件 228 处命中处理，知识零删除 (#250)
- 验证精简为 L1 脚本 + 统一 redteam — 删除 verdict-redteam/doubt_checker (#240)
- 文档组织重组 — docs/(design+devlog) + references archive + openspec 归档 (#263)
- 工具契约对齐 — 现有工具统一契约 + disasm_constant_check 核心抽取 (#284)
- AGENT_TEAMS 默认 0 化 — init 纳入设置 (#276)
- review gate 降为 1-reviewer (#323)
- 声明体系反向扫描 — 未声明资产入册 + 索引一致性 (#320)

### Fixed

- 文档漂移修复批 — 子命令表/aux 路径/scripts 引用/旧名/版本标注 (#321)
- Windows 路径与平台感知 — frida 模板路径转义、fixture POSIX 可执行 (#335)
- UTF-8 stdout 契约强制 + Windows 保留名守卫 (#317)
- 去硬编码 — workspace 探测/agent 工具路径占位符/VM IP 端口环境发现 (#228)
- digest manifest 全量 re-pin + LF 规范化 (#271)
- 工程级 hook 部署 — wire_up_settings 写 workspace 级 settings (#258)
- 心跳 tick 绑定收敛动作 + --heartbeat-off 双端校验 (#237)
- 监视闭环 — drift 现实校验 + refutation 传播 + feedback inbox (#241)
- 决策层修复 F3/F6/F11/F14 — decide 输出 schema 拆分等 (#127)
- completion transaction — CONVERGED 要求零全局矛盾 (#202)
- CONVERGED 要求 discovery 消费 (#203)
- 激活 workspace 无 oracle 被拦截 (#200)
- unified hook 退出码空间 — BLOCKED(3) vs REJECT(2) (#134)
- YAML safe_load 加固 (#129)
- utcnow() 弃用替换为 timezone-aware (#131)
- worktree 扫描要求 .kunglao-worktree 标记文件 (#137)

## 内部版本映射

v0.1 之前仓内代码注释中的 v1.9.x 标记是开发期特性溯源注释（"此 gate 于 v1.9.24 落地"），
非发布版本。它们全部归属 v0.1 首发交付范围，映射关系：

| 内部标记 | 代表特性（非穷举） |
|---|---|
| v1.9.0-1 | convergence-driven dispatch 成为默认调度模式 |
| v1.9.2-7 | failure-blocked claim 拦截（dispatch_gate）、优先级排序修正 |
| v1.9.8 | worker_pulse 收敛脉冲、payload 形状全适配、fact 命名修正 |
| v1.9.12/13/18/25/26 | worktree 隔离与 worker 状态归属（反复回归的派发丢监控类缺陷） |
| v1.9.17 | closeout checklist（过早收敛防） |
| v1.9.19 | superseded-path 禁行声明 |
| v1.9.20/21 | 活动性心跳（时间戳不作数）、sanctioned SendMessage 通道、智能 ping 协议 |
| v1.9.22 | verifier 必须 BLIND |
| v1.9.24 | facts-snapshot HARD-REQUIRED（防状态丢失欺骗）、best-first 偏差审计 |
| v1.9.28 | dispatch 前置校验心跳存活（机械门禁化） |
| v1.9.29 | plan-drift/STALLED/stuck-worker 门禁、claim-status guard（引用最多的标记，26 处） |
| v1.9.31 | plan-to-execute 门禁 (#239) |
| v1.9.32 | tool-first 门禁 (#294) |
| v1.9.33 | agenttype specialist-first 门禁 (#310) |
| v1.9.36-38 | heartbeat 体系三件套（touch/tick/selfcheck）语义统一 |

分布统计（全仓 121 处标记/37 文件）：v1.9.29×26、v1.9.24×11、v1.9.36×8、
v1.9.28×8、v1.9.20×8、v1.9.13×7、v1.9.8×6、v1.9.12×5、v1.9.25×4、v1.9.22×4、
其余各 1-3 处。源文件内这些注释按发布决策保留不动——它们是"何时引入"的
溯源锚点，不是版本声明。
