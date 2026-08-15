# Changelog

本项目全部显著变更记录于此。格式遵循 [Keep a Changelog 1.1](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 PEP 440。v0.1 之前的内部迭代版本号 (v1.9.0–v1.9.38) 是开发期标记，
统一折叠进 v0.1 首发（见文末映射表）。

## [Unreleased]

### Fixed (router runtime + decide INVALID enum, #370/#371)

- kunglao.py 路由器 3/5 子命令运行时修复 (#370) — `tick` 忽略 workspace
  （裸 `hbt.main()` 把 sys.argv[1] 字面量 "tick" 当 workspace 路径）改为
  `hbt.main([str(ws)])` 显式 argv 注入（向后兼容的可选参数， 对齐
  kunglao_verify/kunglao_record 路由模式）；`decide` 人类模式与 `health`
  嵌套 argparse 重解析路由器 argv 导致 SystemExit 2 — 改为直接组合
  `cc.decide/_human` 与 `ch._read_ledger/assess/_human` 模块函数。新增
  tests/test_router_runtime.py（6 测试, 先 RED 后 GREEN）：tick 写
  `runs/.heartbeat-tick.json` 到调用方 workspace 且不再于 cwd 旁生成伪
  tick/ 目录；decide 打印真实决策表；health 打印健康行（无 ledger 时
  exit 3 NO_DATA）。
- decide-output.json enum 补 INVALID (#371) — task_spec primary_questions
  非空畸形（#77 fail-closed）时 convergence_check.decide() 正常返回
  INVALID，kunglao-decide 逐字透传（L134），而冻结 enum 缺该值 → CLI 发出
  违约输出。INVALID 复用 exit 4（冻结 0-4 退出面）；冻结仪式（RED 测试 +
  schema 修订 + specs/phase-4/contract.md 与 module-design.md M1.3 回写，
  同一提交）。openspec/archive/fix-97 的"恒不 INVALID"判断仅覆盖异常→
  BLOCKED 路径，存档不改。
### Fixed (pre-release security batch, #367)

- Review-gate pre-commit key path no longer hardcodes the author's machine —
  the tracked template `.claude/git-hooks/pre-commit` carries the
  `__KUNGLAO_REVIEW_KEY__` placeholder; the human-run installer
  `kunglao-init --install-git-hooks` stamps the installing user's absolute
  key path into `.git/hooks/pre-commit` once at install time (#147
  anti-forgery preserved: the stamped path is a literal, never env-resolved
  at commit time); an unstamped copy fail-closes with install guidance;
  missing key guides `review_gate.py key-init`; hardcode scan extended to
  the whole tracked tree (git grep, allowlisted historical references only)
  (#367)

### Fixed (hook registry single-source, #372)

- env_check hook mirror drift — HOOK_FILES (6) hand-copied from
  wire_up_settings registrations (8 distinct files); recall_inject (#268)
  and completion_gate were invisible to the env_check deployment gate. Now
  env_check.HOOK_FILES IS wire_up_settings.WIRE_UP_HOOK_FILES (frozenset,
  single source) and check_hooks scans the Stop section too (completion_gate
  is a Stop hook); set-equality + Stop-scan tests added; SKILL.md count
  corrected 6 → 8 (#372)

### Changed (renderer unification, #362)

- CLAUDE.md 渲染引擎统一 — scripts/template_render.py 成为 {{param}} 单次替换 +
  残留占位符检测的唯一引擎；template_gen.py（CLI/目录/退出码不变）与
  kunglao-init write_claudemd 共用同一原语；CLAUDE.md.base.tmpl 占位符
  `<UPPERCASE>` → `{{lowercase}}` 迁移（渲染产物字节等价，golden 三型验证）(#362)

### Fixed (renderer + env wiring, #362)

- 未填占位符不再静默 — 渲染后残留 `{{...}}` 触发 TemplateRenderError（run() 转
  stderr + exit 1 + 本次 scaffold 清理），杜绝半成品 CLAUDE.md (#362)
- .env 端口接线 — KUNGLAO_VM_SHELL_PORT / KUNGLAO_FRIDA_PORT 接入 env_check stdlib
  解析（os.environ 优先，.env 兜底），VM_PORTS 由解析值派生（原硬编码 [9876,
  1337] 与 toolchain 口径不一致）；KUNGLAO_CLAUDE_JSON / KUNGLAO_DIE 在
  .env.example 注明"仅 shell export 生效，.env 不读取" (#362)
- 死代码 — kunglao-init.py template_for_type() 零调用方，删除 (#362)
- 残留断言泛化 — test_init_injected_claudemd_has_no_placeholder_residue 由枚举
  7 占位符改为正则扫描（同时捕获遗留 `<>` 与新 `{{}}` 形态）(#362)

### Fixed (pre-release defect batch, #356)

- W1 tools/_INDEX.yaml 28 个工具条目补一行 description（英文，15-40 字符：干什么 +
  何时选它，从现有 input_output/when_not 提炼）；validate_index.py 新增 description
  必填非空断言 (#356)
- W2 CLAUDE.md 模板单源化 — 4 份模板(.tmpl/.windows/.linux/.android) 收敛为
  CLAUDE.md.base.tmpl + kunglao-init 按 OS 注入差异段；五层分析原则收编回单源；
  删除幻觉引用节(~/.claude/rules/common/)；新增成功标准节（可验证判据）；
  中英混杂清理（全英文）(#356)
- W3 硬编码拔除 — migrate_facts/wire_up_settings 的 C:/Users/hr 路径相对化或
  <HOME> 占位；toolchain.py VM_SHELL_PORT 9876 裸常量改为 KUNGLAO_VM_SHELL_PORT
  环境变量可配（默认 9876 不变）(#356)
- W4 .env 部署面 — 新增 .env.example（6 个部署变量，一行英文注释）；env_check.py
  开头接入纯 stdlib .env 解析（os.environ 优先，workspace .env 兜底，零新依赖）；
  .gitignore 加 .env (#356)
- W5 cfg-hook.js.tmpl Frida 17 修复 — Module.getExportByName(mod, name)(16-only) →
  Process.getModuleByName(mod).getExportByName(name)，头注释标注 Requires: frida >= 17 (#356)

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

### Fixed or Removed

- 发版前卫生批 (#355) — docs/ 一次性修复日志与会话计划残渣删除、HISTORICAL 设计文档迁入 docs/design/archive/、specs/README 断链修复（去除未跟踪 .research-tree-alignment 依赖与"不引入 OpenSpec"矛盾条款）、openspec/changes 51 个已交付目录归档至 openspec/archive/、根 DESIGN.md 判定为 HISTORICAL 并迁档、CHANGELOG v1.8.x 映射段补齐、.claude/reviews/ 会话残渣出库（git-hooks 保留）、.gitignore 增加 .research-tree*/ 与 .pytest_cache
- 死代码移除 — memory/ 子系统整体删除（staging/longterm/candidates corpus + memory/scripts 蒸馏流水线 + references/memory-protocol.md，实测零运行时消费方）；hook_activation ALL_HOOKS 与 cost_gate advice 中的 memory_capture 幽灵条目同步清除 (#355, 原 #358 Wave 6)

## 内部版本映射

v0.1 之前仓内代码注释中的 v1.8.x / v1.9.x 标记是开发期特性溯源注释（"此 gate 于 v1.9.24 落地"），
非发布版本。它们全部归属 v0.1 首发交付范围，映射关系：

| 内部标记 | 代表特性（非穷举） |
|---|---|
| v1.8.x | orchestrator 失败模式工程化期（design rationale 存档于 docs/design/archive/DESIGN.md）：v1.8 iterative-deepening tier 门控；v1.8.1 C0a PROVEN 不打折 + self-cap 闸；v1.8.2 F1-F6 失败模式紧凑表（SKILL.md §6-pre）+ self-cap-safe-prose（§7）+ B1c blocker；v1.8.3-5 enforcement gates 套件（troubleshooting/search/active-intervention/backtrack/reuse/hook-activation/ask-for-direction，tests/test_v1_8_enforcement_gates.py）；v1.8.15/16 complete-teardown 搜索算子链（scripts/complete_teardown.py） |
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
| v1.9.29 | plan-drift/STALLED/stuck-worker 门禁、claim-status guard（引用最多的标记） |
| v1.9.31 | plan-to-execute 门禁 (#239) |
| v1.9.32 | tool-first 门禁 (#294) |
| v1.9.33 | agenttype specialist-first 门禁 (#310) |
| v1.9.36-38 | heartbeat 体系三件套（touch/tick/selfcheck）语义统一 |

分布统计（#355 重测；口径：git 追踪文件、排除冻结历史 openspec/archive + docs/design|devlog 档案 + references/archive、排除本文件自身）：
**v1.9.x 活树 101 处/26 文件** — v1.9.29×26、v1.9.24×13、v1.9.8×6、
v1.9.28×4、v1.9.25×4、v1.9.13×4、其余各 1-3 处；
**v1.8.x 活树 19 处/8 文件** — v1.8.2×5、v1.8.5×4、v1.8.16×3、
v1.8.1×2、v1.8.3×2、v1.8.4×2、v1.8.15×1（另有 22 处在冻结档案内）。
源文件内这些注释按发布决策保留不动——它们是"何时引入"的
溯源锚点，不是版本声明。
