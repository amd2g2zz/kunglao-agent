# kunglao-agent DESIGN (v1.8.2)

> **NOTE (2026-08-11)**: DESIGN lags SKILL.md (operative contract per §17) — reconcile before relying on it. §8 C0's note-layer gate is now enforced mechanically by `scripts/convergence_check.py` (`_note_layer_gaps`, commit e2f2432). C0's spec says notes carry `answers_question` directly; the live convention links via `note.claim_id → claim.answers_question` — the gate implements the live chain.

v1.8.2 在 v1.8.1 自打脸补丁基础上加 6 个 orchestrator 在-session 反复违反的失败模式(F1 傻等 / F2 忘记心跳 / F3 只 ping 最后启动 / F4 不根据 subagent 返回重规划 / F5 死锁僵尸等待 / F6 弃用专业 agent 用 general-purpose),落进 SKILL.md §6-pre 紧凑表;新增 §7 self-cap-safe-prose(防 _SELF_CAP_RE 把 SKILL.md 自身的 prose 当 self-cap reject)+ B1c blocker type(worker died without notification)+ §6e priority 3 硬约束(`general-purpose` <50-line dispatch 即 §6e 违规)。**Mirror rule**: SKILL.md 是 operative contract,DESIGN.md 是 design rationale + changelog;两者 § 编号要一致(本版本新增 §6-pre + §7,DESIGN.md 此处不重写 prose,只增交叉引用)。

Santa 四轮 + beam 评估 + 搜索算法选定后定稿。v1.7→v1.8 加:iterative deepening tier 门控(把"RE 是搜索问题"落进架构——贪心 best-first + 全局 tier gate,2 算法组合)。v1.8→v1.8.1 加:C0a PROVEN 不打折约束 + hook `check_no_self_cap` 闸(防 sub-agent 偷偷加时间上限,防单 VM 短窗口 PROVEN 打标 → 误判收敛 → 提前开环)+ §9 rule 5 "禁止等用户决定" 配合 learned skill `~/.claude/skills/learned/orchestrator-proactive-loop.md` (env 失败自修、并行 dispatch、note 强制 verifier)。v1.8.1→v1.8.2 加:SKILL.md §6-pre 6 行失败模式紧凑表(F1-F6,单 worker focus bug + 死锁 + 弃用专业 agent)+ §7 self-cap-safe-prose + B1c blocker + §6e priority 3 硬约束。

---

## 1. 定位 + 输入契约

样本无关的逆向分析 **orchestrator looper skill**。

**输入(三件,缺一不启动)**:
1. **sample** — `bins/<sha>`,sha256 已验
2. **task_spec.yaml** — 用户的要求(问题 / 范围 / 约束 / 深度 / 交付形态)。前置定,运行中可外部更新
3. **现有 artifact** — CTI / evidence / fact base,只读冷启动

**输出**:项目级、已验证的行为证据 fact base(唯一交付物)。
**不是**:报告写作(下游 hr-report)、符号恢复/改名、某样本专用脚本、CTI 重查。

## 2. task_spec.yaml schema

```yaml
primary_questions:           # 必答 — 收敛硬条件 C0
  - id: q1
    q: "样本是否属于 Vidar 家族?"
    need: yes_no_with_evidence
  - id: q2
    q: "C2 协议是什么?"
    need: protocol_description
  - id: q3
    q: "样本家族归属?"
    need: model_selection        # 归因/模型类——Phase 0.7 展开成 K 个互斥竞争 claim
    candidates: [vidar, wingo, gsb, loader_stub]

scope:                       # claim 是否进队列
  in:  [family_attribution, network, persistence]
  out: [anti_analysis_strings, bitcoin_clipper]

constraints:                 # worker 不可破,§11 hook 强制
  vm_detonation: forbidden        # 未授权 → 需 VM 的 claim 直接 deferred
  time_budget_minutes: 120
  dynamic_re: allowed

depth: standard              # triage | standard | deep

success_criteria:
  deliverable: fact_base
  must_include_ioc_table: true
  confidence_floor: 倾向于    # 低于此的结论标 suspected,不交 confirmed
```

## 3. 架构:orchestrator-worker 两层

```
ORCHESTRATOR(主 session,读 SKILL.md)
  MONITOR → DISPATCH → [workers] → VERIFY → RECORD/RE-PLAN
       │
       └─ spawn WORKERS(≤3 concurrent,Agent/Task)
             做所有新证据采集,自决方法,返回 draft fact
```

- orchestrator 不做新证据采集
- workers 做所有分析,≤3 并发,跨分析多轮 sequential
- maker-checker 天然满足:worker=maker,orchestrator=checker

## 4. orchestrator 纯度

不做**新证据采集**(不主动反编译/仿真/dump 作主分析)。做 **synthesis**(跨已有 fact 模式识别)+ **verification judgment**(解读 reproduce)+ **re-planning**。界线:novel evidence vs coordination over existing evidence。

orchestrator 自撰的 composite note 也必须经 `verify-note.py`(独立 verifier subagent),不自己盖章。

## 5. orchestrator 三职责

| 职责 | 做什么 |
|---|---|
| MONITOR | 读 §13 cold-restart 8 文件;跟踪 claim 状态;跨 fact synthesis;**收用户在途反馈**(§10) |
| DISPATCH | 决最高价值下一步(**依 task_spec 价值函数**);spawn ≤3 worker(§11 hook 强制);不规定方法 |
| VERIFY | §12:静态跑只读 reproduce+byte-exact;动态重跑同工具+归一化 trace diff |

## 6. 模块目录(描述性,无顺序 — worker 自选)

| 支柱 | 工具 |
|---|---|
| **样本类型检测** | DIE(`evidence/die.json`)、`pefile-signature`、resources 扫描 |
| **静态 RE** | `ghidra-malware`、`ghidra-re`、`ghidra-light` agent、`mcp__ghidra__*`、`pefile-signature`、`mal-recon` |
| **动态 RE** | `malware-framework`(Qiling)、`rev-frida`、`mcp__x64dbg__*`、`vmr-shell`(需预授权)。worker 按场景选 |
| **内存 dump** | `mcp__volatility__*` |
| **pcap** | TBD,检测到即 `deferred_until: tooling-available` |
| **验证** | `malware-veri-notes`(`verify-note.py` + `lint-notes.py` + fact/note/run schema)。**schema 唯一 owner 是 malware-veri-notes** — kunglao-agent worker 产出的 facts 必须遵循其 fact schema(含 numeric 事实的 `unit:` 字段,见 `~/.claude/rules/common/numeric-fidelity.md`);schema 演进先在 veri-notes 落,再同步 worker 契约,避免"定义方与生产方脱节"导致报告口径丢失 |
| **裁决**(收敛后可选) | `verdict-scorer` agent |

注:`verdict-scorer` 是 **agent type**,非 skill。

## 7. Phase 0 SETUP(pre-loop,允许与用户交互;**所有步幂等——目标文件存在且非空则跳过,不 clobber**)

| 步 | 做什么 |
|---|---|
| **0.1 环境探测 + venv** | **先行必做**。检查当前会话是否处于 venv(`$env:VIRTUAL_ENV` / `sys.prefix != sys.base_prefix` / `.venv` 存在)。已激活 → 记录路径;未激活且 `.venv/` 不存在 → **先创建** `python -m venv .venv`(项目根),本 skill 依赖(cryptography/pyyaml/capstone/pefile 等)装进 venv,不污染全局。验证 `python -c "import cryptography, yaml"`,缺失先补齐 |
| **0.2 认知建立 + 样本校验** | 探测结论写入 `analysis_state.txt`(venv 路径 / Python 版本 / 工具链就绪状态 / 样本 sha256 已校验 / fixtures 清单)形成"已认知基线",后续冷启动以此为准不重复探测。`bins/<sha>` 存在且 `sha256sum` 与 task_spec/report 一致,不匹配则 HARD STOP |
| **0.3 hook 安装** | 在 `.claude/settings.json` 注册 PreToolUse + PostToolUse 挂 Agent 工具 → `hooks/worker_budget.py`。幂等(已注册则跳) |
| **0.4 workspace scaffold 经 `/init`** | 工作区搭建一律通过 **`/init`** 完成(禁止手写 scaffold 命令):建 `facts/` `blockers/` `runs/`;建空 `claim-register.yaml` / `claim_deps.yaml` / `facts/_INDEX.md` / `analysis_state.txt`(空结构段)/ `global_plan.txt`(v1 stub)/ `task_spec_snapshot.yaml`(空)。**幂等**:目标存在且非空则跳过;重复初始化时以 `analysis_state.txt` + `claim-register.yaml` 为准幂等续接,不覆盖已有 state |
| **0.5 样本挂载 + 验** | 确认 `bins/<sha>` 在,`sha256sum` round-trip,写 fact provenance |
| **0.6 task_spec 摄入** | `task_spec.yaml` 在 → 读;**缺 → pre-loop 交互摄入**(问 primary_questions / scope / constraints / depth / success_criteria,写盘)。**iteration 1 之前,允许问**——这不是中途问。读完后算 `deadline_ts = now + time_budget_minutes`,写 `analysis_state.txt`(供 §11 hook (d) 时间检查) |
| **0.7 冷启动 artifact 发现 + schema 迁移** | 扫现有 `evidence/*.json` / `cti-*.json` / 已有 `facts/`,记录可用(只读)。**若 claim-register.yaml 是 pre-v1.5 schema**(refute_paths/evidence 而非 boundary_type/source/promotion_attempts)→ 迁移到 v1.5+ schema,或标 `requires_migration` 暂停进 loop |
| **0.8 pre-flight 检查** | 样本类型 DIE 可判?目录有适用工具?约束兼容(如 vm=forbidden 但只 VM 适用 → flag)?无适用 → meta-deferred,不进 loop |
| **0.9 claim 种子** | task_spec.primary_questions → PRIMARY claims(`answers_question` 标 q_id)。**`need: model_selection` 的问题**展开成 K 个竞争 claim(C-NNa/b/c,共享 `competitor_group: <q_id>`,互斥);CTI → background claims |
| **0.10 进 loop** | O0-O5 可判,首轮开始 |

## 8. 循环语义:开环 / 闭环 / 阻断

### 开环(跑一轮,全真)
- **O0** task_spec.yaml 存在且非空(首次启动门)
- **O1** 存在未决 claim:fact `status ∉ {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}` OR (open boundary AND `promotion_attempts < 3`)
- **O2** 无基础设施故障
- **O3** 无用户显式 stop
- **O4** 无未对账 orphan intent(§14)
- **O5** 软收敛未触发(见 C7)

### 闭环(收敛,交付 fact base,全机器可验)
- **C0** task_spec 每个 `primary_question` 都有一条 **note**(`verify_status=passes` + frontmatter `answers_question: <q_id>`),该 note cites ≥1 fact 且 cited fact `status ∈ {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}`(terminal)。即——问题可由正向 fact(PROVEN)、**证伪性 fact**(NEGATIVE/REFUTED,如"不是 Vidar"/"无 C2")、或已知缺口(DEFERRED)回答。**note 持 verify_status(fact 无此字段),避免 schema 矛盾;terminal 含 NEGATIVE/REFUTED/DEFERRED,避免不可答问题死锁**。机械执行: `convergence_check.py::_note_layer_gaps`(e2f2432) — 注: 实装按 `note.claim_id → claim.answers_question` 链, 与文本"note 直接带 answers_question"有偏差, 见顶部 NOTE。
- **C0a (v1.8.1 强化 — PROVEN 不打折)**: 对 `need: model_selection` / `need: yes_no` / `need: protocol_description` 这类**正向归因型**问题(q1/q3/q4),cited fact 必须是 **`status=PROVEN`**(不是 NEGATIVE/REFUTED/DEFERRED)。**`status=PROVEN` 且 `confidence_band=PROVEN-INITIAL` 不闭合 C0a** —— PROVEN-INITIAL 仅是 annotation band(信号初见、窗口受限、需要 ≥2 独立 tier 来源或 ≥5 分钟多 VM 才能升 PROVEN-FULL)。设计目的:防止单 VM 短窗口"PROVEN"打标 → 主循环误判收敛 → 提前开环。**PROVEN-FULL 升级路径**:`≥2 不同 tier 独立来源(tier-1 静态 + tier-3 动态双源)` OR `≥5 分钟多 VM 起爆 + 完整 IO 链(网络/文件/注册表 ≥1 类有 payload)`。**C0a 不阻塞 exclusion 型问题**(q 答"不是 X"——NEGATIVE/REFUTED 即可)
- **C0b** 对 `need: model_selection` 的问题(q 的 K 个竞争 claim,共享 `competitor_group`):K 中 ≥1 达 terminal **且其余 ∈ {REFUTED, DEFERRED}**(淘汰或悬置)→ 该问题被回答。证据天然淘汰劣势(§9 rule 4(b) refutation 沿 `competitor_group` 传播)。最优:1 个 PROVEN + 其余 REFUTED;可接受:1 个 PROVEN + 其余 DEFERRED(弱淘汰)**——PROVEN 的那一个仍受 C0a 约束(PROVEN-FULL,不是 PROVEN-INITIAL)**
- **C1** `claim-register.yaml` 每个 claim 有 `boundary_type`
- **C2** 每个 open boundary 有非空 `promotion_gate` AND `promotion_attempts ≥ 1`
- **C3** 每个 fact `status ∈ {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}`(terminal 五类)
- **C4** 每个 composite note(`type ∈ {note, supersede-update, refutation}` AND `facts_used` 长度 ≥2)cited fact 满足 C1-C3
- **C5** `lint-notes.py` exit 0
- **C6** 无 orphan intent 残留
- **C7** 软收敛:**C0 满足 AND 连续 3 轮无新 PRIMARY claim** → close(防 synthesis 无限 mint;background claim 不阻塞关闭)

### 阻断(唯一非收敛出口,极少)
- **B1a** infra 全坏**且不可写** → exit,不写 meta-note
- **B1b** 所有 worker 失败**但可写** → 写 meta-deferred note,收尾
- **B1c (v1.8.2 新增)** worker died without notification — worker 进程退出/crash 但 post_check 未跑,status 文件停在 in-progress。检测: `worker_budget.py::read_active_workers` 找到无对应终止的 `w<ts>` 行 + `TaskList` 找不到 agentID。处理: log `blockers/B1c-<timestamp>-<workerID>.md` + redispatch claim(同 `[TN tools=...]` 前缀)。**严禁 SendMessage 死 worker** — 会阻塞 orchestrator。详见 SKILL.md §6-pre F5
- **B2** 用户显式 stop

### per-claim defer cap
同一 claim `promotion_attempts ≥ 3` → 强制 `status=DEFERRED`(终态),记 known-gap fact。

## 8.5 搜索策略:贪心 best-first + iterative deepening (v1.8)

RE 是搜索问题(状态 = fact base,算子 = worker,目标 = C0-C7)。选定 **贪心 best-first(每轮选最高价值 claim)+ iterative deepening(跨 claim tier 门控)**——2 算法组合。排除 A*(需 admissible heuristic,RE 不可估)、MCTS(rollout 太贵)、full beam(浪费)。

### tier 定义(证据成本阶梯)
| tier | 操作示例 | 门控 |
|---|---|---|
| 1 (cheap) | grep / strings / DIE / CTI 读 / 反编译 | 无门 |
| 2 (medium) | 仿真(malware-framework)/ 跨引用追踪 | 须所有 open claim `evidence_tier_attempted ≥ 1` |
| 3 (expensive) | VM 起爆(vmr-shell)/ Frida 真跑 / **x64dbg MCP step-into call site** | 须所有 open claim `evidence_tier_attempted ≥ 2` |

### 门控机制
- claim-register 每 claim 加 `evidence_tier_attempted: int`(初始 0)
- 派工时 orchestrator 在 Agent `description` 前缀声明:`[T<N> tools=<逗号分隔>] <任务描述>`
- §11 PreToolUse (e) 强制(见下)
- worker 完成 tier-N 证据 → 该 claim `evidence_tier_attempted = max(current, N)`
- claim 达 terminal → 不再 escalate

### pass 结构(隐式涌现,无显式 pass 状态)
- Pass 1:所有 claim 跑 tier-1(广扫,信息增益最高)
- Pass 2:仍 open 的 claim 上 tier-2
- Pass 3:仍 open 的关键 claim 上 tier-3
- pass 间 = 自然 re-plan 时机(§9 rule 4,cheap 发现重排后续优先级)

### 竞争假设(v1.7)嵌在贪心内
`need: model_selection` 的 K 互斥 claim 是贪心的内部策略(高信息量节点优先),非第三搜索算法。

### 8.6 动态 RE worker 工具优先级(v1.8.1)

Tier-3 动态 RE worker(VM 起爆/Frida)的目标是**在原始 artifact 上观察样本行为**。当目标涉及**单个特定 call site**(如 `CryptUnprotectData`、`NtCreateThreadEx`、`connect` 到具体 IP),worker 工具优先级:

| 优先 | 工具 | 适用 | 原因 |
|---|---|---|---|
| 1 | `mcp__x64dbg__*`(step-into / read_memory / set_breakpoint) | call-site stepping、读取 syscall 参数、walk 反汇编 | **直接走原始 artifact**:CPU 在被调函数入口停下来 → 寄存器/栈里的参数就是样本真实传的 payload;**单步可穿透 garble CFF / 反射 thunk band**(因为走 CPU 不走 decompile 文本) |
| 2 | `rev-frida`(Frida hook) | 截一批同型调用(call counts / API resolution set / 反射加载列表) | 能批量观察但**只能看到 hook 帧之前的内容**;若样本有 anti-hook / hook-detect 则失明 |
| 3 | `vmr-shell`(VM 起爆 + pcap) | 全程跑样本、捕网络流量、看 file/registry 实际写 | **最后一道兜底**——只能看 OS 层 IO,看不到 call site 内部栈 |
| 4 | `malware-framework`(Qiling 仿真) | 离线 unicorn 模拟 syscall | 实战经验:Go runtime init 依赖未仿真 syscall 时直接 NEGATIVE(garble CFF + Go runtime init 双阻)——只能做初筛,不能当结论 |

**派工硬约束**:
- call-site stepping 类任务(`"step into CryptUnprotectData"`)→ worker **必须先列 `mcp__x64dbg__*`**;不允许直接跳 Frida hook 或 VM detonation。
- 批量观察类任务(`"collect all reflective API resolutions"`)→ Frida 优先;x64dbg 可补强但非必需。
- "判断样本整体行为链"类任务 → VM detonation 兜底;但仍须 step-into 关键 call site 拿参数。
- in-session 反例:iter 2.2 用 Frida 30 s 跑出 74 unique API 但没有 step-into `CryptUnprotectData` 看 `pDataIn`/`pDataOut`;用户当场要求改用 x64dbg。

## 9. 硬禁律

1. **禁止中途提问**(澄清/确认/等指示)。歧义 → 选高证据解释 + 写 fact `reasoning` + 继续。
2. **禁止级联跳过**。claim C 失败 = C 的数据。C 转 deferred。**其他 claim 零影响**。
3. **用户反馈双层怀疑**(见 §10)。禁止中途澄清问询;接收用户主动反馈,但认知 + 程序两层怀疑,**orchestrator 全程自决**。
4. **re-plan 规则**:(a) 正向已验发现 OR (b) refutation of premise downstream depends on(沿 `claim_deps.yaml` 传播)OR (c) **task_spec 被外部更新**(用户加问题/改 scope/松约束,下次 MONITOR 读到 diff)。**永不因单纯失败**。
5. **禁止"等用户决定"** (v1.8.1 自打脸补丁,in-session 2026-07-28):orchestrator pause 不带选项 1/2/3、dispatch description 不带 self-cap、env 失败时先读 skill cookbook 自己修、note 写盘后**必须** spawn verifier subagent (per `~/.claude/skills/learned/orchestrator-proactive-loop.md`)。in-session 三个反模式:
   - "x96dbg.exe not installed → 选项 A/B/C 给用户选" → 错;读 qiling-framework `references/installation.md` 自己下
   - "iter 2.2 单 worker 跑完才派 iter 2.3" → 错;独立 claim 并行 dispatch (≤3 cap)
   - "note-024 写完不跑 verify-note.py" → 错;每个 note 写盘后**强制** verifier subagent + `verify_status: passes` 才能 cite 进 hr-report

## 10. 用户反馈(双层怀疑)

用户在途反馈不只**真伪由 artifact 裁决**,连**何时/按何优先级处理**也由 orchestrator 自决。

| 层 | 裁决者 | 内容 |
|---|---|---|
| **认知层** | artifact | 用户说的 X 是真是假 |
| **程序层** | orchestrator | 这条反馈**何时验、验多深、插不插队** |

### 处理流程
```
用户消息 → 写 claim-register:C-NN, source: user_feedback, confidence: hypothesis, status: OPEN
   ↓
orchestrator 依 task_spec + plan 评估优先级(用户 source 不抬高):
   - 关联 PRIMARY 且 load-bearing → 高优先,派 worker 取证
   - 已被现有 fact 覆盖 / background → 排队,不插队
   - 与在飞 worker 重复 → 等 worker 完,比对
   ↓
VERIFY(§12)→ RECORD:
   artifact 证实 → 提升(若推翻前提,沿 claim_deps 传播,可能 supersede 旧结论)
   artifact 反驳 → 标 status=REFUTED + 记原因,**旧结论不动**
   ↓
progress.txt 记:用户假设 + orchestrator 处理决定 + 求证结果(事后可审,中途不交互)
```

**核心**:artifact 是 ground truth,用户是可错观察源(同 V3 对 CTI 的态度)。用户反馈和 CTI 一样——外部观察,进 claim register,过同样取证-验证管线。用户打断**不转移控制权**。

## 11. 强制机制(双 hook + 约束)

| hook | 动作 |
|---|---|
| **PreToolUse**(挂 Agent) | (a) 读 `active_workers` 段,≥3 → reject(exit 2);(b) 读 `claim-register.yaml`,目标 claim `promotion_attempts ≥ 3` → reject;(c) 读 dispatch payload 的 **`intended_tools` 字段**(orchestrator 派工时声明),与 task_spec.constraints 比对,违反(如 vm=forbidden 却列 vmr-shell)→ reject;(d) 读 `analysis_state.txt` 的 `deadline_ts`,now ≥ deadline → reject(time_budget 用尽);(e) **tier 门控(§8.5)**:解析 dispatch `description` 前缀 `[TN tools=...]` 得 tier=N,若 ∃ open claim with `evidence_tier_attempted < N-1` → reject;(f) **v1.8.2 新增**:`detect_self_cap` 扫 dispatch description 是否含 `_SELF_CAP_RE` 模式("30 min cap" / "wait 5 min" / "stop after 30 min" / "run for 1 hour" 等),task_spec.time_budget_minutes=0 时 reject(防 orchestrator 自身 prose 吸收后 self-reject;详见 SKILL.md §7);通过 → 写 entry(`worker_id`/`claim_id`/`dispatched_at`/`intended_tools`/`tier`)到 `active_workers`(hook 写) |
| **PostToolUse**(挂 Agent) | worker 返回 → 从 `active_workers` 移除 entry(hook 写);**扫 worker 实际工具调用记录,若用了 `intended_tools` 之外的禁用工具 → claim 降级 DEFERRED + 记违规到 `blockers/`** |

两 hook 覆盖全生命周期。orchestrator 不自计数,不靠意志守约束。

## 12. VERIFY(分静态/动态)

| claim 类型 | VERIFY |
|---|---|
| **静态**(反编译/字符串/字节) | orchestrator 跑 fact `reproduce:`(只读 grep/python/xxd),byte-exact 比 `expected:` |
| **动态**(仿真/trace) | orchestrator **用相同输入重跑同一动态工具**,取**归一化 trace** 比 diff。归一化 = 提取结构化事件序列(API call 名 + 参数哈希 + 顺序),剥指针/时间戳/地址非确定字段。trace 用工具结构化输出(Qiling `report.to_dict()` / Frida call log)非 raw stdout |
| **非确定性**(真网络/真 VM) | claim 上限 `confidence=single-source-dynamic`,必须 defer 待静态佐证 |

复现 ≠ 采集。

## 13. cold-restart 协议(8 文件)

每轮 MONITOR 第一步,**固定**读(不自由发挥):

0. **`task_spec.yaml`** — 价值函数,最高优先(决定本轮目标)
1. **`claim-register.yaml`** — 全部 claim(C-NN + boundary_type + source + promotion_attempts + status)。**用户反馈(§10)持久化在此**;C1/C2/cap 据此验
2. `analysis_state.txt` — 结构段(current task / VERIFIED-FACTS LEDGER / IOC REGISTER / GATE STATUS / active_workers / in_flight intents / deadline_ts)
3. `global_plan.txt` + `claim_deps.yaml`(依赖图)
4. `progress.txt` 结构段(VERIFIED-FACTS LEDGER / 决策 rationale)
5. `lint-notes.py` 输出 → **error check**(C5)
6. `blockers/` 目录(若非空)
7. **`facts/_INDEX.md`** — status 计数源。一行一 fact:`F0NN | status | claim_id | 一行结论`。orchestrator 单写者,原子 rename。读它判 all-passes 是 O(1)

每轮当 cold start。judgment 质量跨轮均匀——long-horizon 根基。

## 14. WAL crash-safety(幂等)

- **fact_id = content-sha256(claim + reproduce + expected)**。重派同 work → 同 fact_id → 同文件(幂等)
- dispatch 前:append intent 到 `analysis_state.txt`(`intent_id`/`claim_id`/`worker_id`/`dispatched_at`/`status=in_flight`)。intent log 行级 checksum + 原子 rename
- worker 写 fact(用 fact_id 作文件名)
- orchestrator 标 intent `status=completed`
- cold-restart 对账:任一 `in_flight` → 重派(幂等)。fact 无 intent → orphan → `blockers/orphan-<id>.md`

## 15. plan 演化 + 版本归档

re-plan:`global_plan.txt` → `global_plan_vN.txt`(快照)+ `global_plan_diff_vN_to_vN+1.patch`(diff)。`claim_deps.yaml` 同步归档。

**task_spec 变更检测**:每次 MONITOR 比对 `task_spec.yaml` 与快照 `task_spec_snapshot.yaml`(orchestrator 在 re-plan 后写)。diff → §9 rule 4(c) 触发:新 primary_question → 新 PRIMARY claim;scope 缩 → 相关 claim 出队;约束松(如 vm forbidden→allowed)→ 扫 DEFERRED claim 的 `deferred_until`,可激活的重派。比对后更新 snapshot。

触发:§9 rule 4 的三类。

## 16. always-produce-a-record

每轮 ≥1 fact 写/改。**可写但全失败** → meta-deferred note。**不可写**(B1a)→ exit 无 note。per-claim cap 保终态可达。

## 17. SKILL.md 是契约

含:目标 + 输入契约 + 禁律 + 预算 + 模块目录(无顺序)+ 收敛语义 + cold-restart + WAL + 双 hook + Phase 0 SETUP。
不含:状态机步骤、worker-type 表、dispatch 表、claim 优先级规则。方法 orchestrator 自决。

## 18. system 边界

| 内 | 外 |
|---|---|
| orchestrator + workers + 模块 + fact base + state 文件 + verify 闭环 + 双 hook + Phase 0 | hr-report(下游)、报告生成、符号恢复、CTI 重查 |

---

## 附录 A:schema(对齐 malware-veri-notes 实际)

- **boundary_type 九类**:`confirmed`/`capability_not_executed`/`link_not_closed`/`source_derived`/`numeric`/`observation`/`coordinate`/`pure_negative`/`contradiction`。**open = {capability_not_executed, link_not_closed, observation, source_derived, numeric}**(对齐 lint `OPEN_BOUNDARY_TYPES`)
- **fact.status**:lint `VALID_STATUS`={PROVEN, INFERRED, NEGATIVE, REFUTED, OPEN, DEFERRED, VERIFIED}。**terminal = {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}**。fact 不用 verify_status
- **note.type**:lint 接受={note, refutation, negative, deferred, caveat, supersede-update, open-question}(**不含 finding**)。composite 用 {note, supersede-update, refutation} + facts_used≥2
- **note.verify_status**:{pending, passes, partial, fails, stale}
- **task_spec.yaml**:见 §2
- **claim.source**:{cti | static_re | dynamic_re | user_feedback | synthesis} — 标 claim 来源,影响处理(用户反馈走 §10 双层怀疑)
- **note `answers_question`**(主)+ fact `answers_question`(辅):值 = task_spec.primary_questions[].id。C0 据此判定 primary 是否被回答(**C0 要求 note verify_status=passes + cites ≥1 terminal fact**)
- **promotion_attempts**:claim-register 字段,int,§11 hook 读
- **evidence_tier_attempted**:claim-register 字段,int(0/1/2/3),§8.5 tier 门控用,§11 hook (e) 读
- **claim_deps.yaml**:邻接表 `C-NN → [C-MM,...]`。**+ `competitor_group`**:`competitor_group: <q_id>` 标互斥竞争组(同组 K 个 claim,证据淘汰劣势,C0b 判定该组是否回答了 q)
- **facts/_INDEX.md**:`F0NN | status | claim_id | 一行结论`
- **known-gap fact**:`status=DEFERRED` + `deferred_reason` + `promotion_attempts=3`
- **meta-deferred note**:`type=deferred` + `deferred_until`

## 附录 B:sample-class 检测

PE/ELF/Mach-O/shellcode → 全可用。dump → volatility。pcap → deferred_until。无适用工具 → meta-deferred,不进循环。

---

## changelog

### v1.8.1 → v1.8.2(7 条 — orchestrator 在-session 反复违反的失败模式 + paraphrase hygiene)

| # | 修 | 条 |
|---|---|---|
| 1 | **SKILL.md §6-pre "Anti-forgetting protocol"**:6 行紧凑表(F1 傻等 / F2 忘记心跳 / F3 后台监视不 ping / F4 不根据 subagent 返回优化 / F5 死锁僵尸 / F6 弃用专业 agent),把 orchestrator 在-session 反复违反的失败模式集中到 SKILL.md 主体读取位置(不再埋在 §6e / §6f.1)。每个 F 行:title 含可观察症状 + 中段引用具体 § 文件 + 末尾显式禁令 | SKILL.md §6-pre |
| 2 | **B1c blocker type**:新阻断类型 "worker died without notification" (worker 进程退出/crash 但 post_check 未跑,status 文件停在 in-progress 死循环)。日志路径 `blockers/B1c-<timestamp>-<workerID>.md`;检测路径: cross-check `worker_budget.py::read_active_workers` + `TaskList` 双 liveness signal,**DEAD CHECK FIRST, THEN PING**(严禁 SendMessage 死 worker 会阻塞 orchestrator)| §8 + §11 |
| 3 | **F3 单 worker focus bug 修复**:heartbeat 必须 `for worker in active-worker registry` 穷举,不能 short-circuit 到 last-dispatched worker ID。`converge-checklist.md` "Active workers" 表为 load-bearing 状态机。明确引用 `references/guardrails.md §6b.1`,SKILL.md 主体不再重复完整 prose | §6-pre F3 + §6b.1 |
| 4 | **F6 stage-agent-bypass 修复**:`general-purpose` 从 soft "last resort" 升级为 hard `last resort — must justify`,违反触发条件明确为 "<50-line dispatch + general-purpose 即 §6e 违规"。claim→agent map(Ghidra 关键词→ghidra-light / Go pcln→go-symbols / Authenticode→pefile-signature / floss→floss-filter / verdict→verdict-scorer / 其它→kunglao-worker);"Never general-purpose for a single-step claim" *(CTI agents removed batch 4)*| §6e + §6-pre F6 |
| 5 | **§7 self-cap-safe-prose**:v1.8.1 `_SELF_CAP_RE` 反讽 —— SKILL.md 主体 prose("every ~5 min"/"30-min frida trace"/"Interval: 15 min T3")会让 orchestrator 写出 self-cap dispatch 触发自身 reject。§7 列 `_SELF_CAP_RE` 4 行 verbatim 模式 + 7 行 negation allowlist + 10 行 safe paraphrase 表("wait 5 min" → "heartbeat until done";"30-min frida trace" → "long-running frida trace";带 negation phrase 的 dispatch 例)| §7 |
| 6 | **Description frontmatter 推 pushiness**:`description:` 重写把 3 个被埋的义务加粗(**actively pings silent workers every ~5 min** / **dispatches next open claim before idling** / **re-plans after every worker return**);`triggers:` 从 6 行扩展到 11 行,加 5 个英文触发器(RE orchestrator / run the RE loop / malware sample triage / claim-driven RE / byte-anchored fact base) | SKILL.md frontmatter |
| 7 | **§6e 优先表硬约束**:`general-purpose` cell 加 "<50-line dispatch + general-purpose = §6e violation"。新增"Detection rule (in-session)"段:违反时自纠正(取消 dispatch + 用正确 stage agent 重派 + 在 dispatch reasoning 记录偏差)| §6e |

### v1.8 → v1.8.1(2 条 — 自打脸补丁)

| # | 修 | 条 |
|---|---|---|
| 1 | **C0a 加 PROVEN 不打折约束**:正向归因型问题(q1/q3/q4, model_selection/yes_no/protocol_description)cited fact 必须 `status=PROVEN` 且 `confidence_band=PROVEN-FULL`(或无 band)。`PROVEN-INITIAL`(单 VM 短窗口 annotation band)不闭合 C0a。设计目的:防止单 VM 短窗口 "PROVEN" 打标 → 主循环误判收敛 → 提前开环(in-session 案例:iter 2.2 把 C-202 PROVEN-INITIAL 当 C0 满足,用户当场拒绝: "我们说好的闭环了？怎么就这么快开环了？") | §8 C0a |
| 2 | **hook `check_no_self_cap` 闸**:worker_budget.py 加 `_SELF_CAP_RE` + `detect_self_cap` + `check_no_self_cap` 闸。task_spec.time_budget_minutes=0 时拒绝任何 dispatch 含自加时间上限(in-session 案例:iter 2.2 sub-agent 在 dispatch 里加 "30 s" cap,违反用户 "无预算直到开环" 约定) | §11 |
| 3 | **§9 rule 5 "禁止等用户决定"** + learned skill `orchestrator-proactive-loop.md`:orchestrator pause 不带选项 1/2/3、env 失败先读 skill cookbook 自己修、note 写盘后**强制** spawn verifier subagent。in-session 三个反模式自打脸:(a) "x96dbg 未装 → 让用户装" 错;读 qiling-framework installation.md 自己装;(b) 单 worker 串行跑 iter 2.2 才跑 iter 2.3 错;独立 claim 并行 dispatch;(c) note-024 写完不跑 verify-note.py 错;每个 note 强制 verifier 字节级 reproduce | §9 rule 5 + `~/.claude/skills/learned/orchestrator-proactive-loop.md` |

### v1.7 → v1.8(1 条 — 搜索算法选定)
| # | 修 | 条 |
|---|---|---|
| 1 | iterative deepening tier 门控:claim-register 加 `evidence_tier_attempted`;§8.5 定义 tier 1/2/3 + 门控规则;§11 PreToolUse (e) 强制;派工 description 前缀 `[TN tools=...]`。把"RE 是搜索问题"落进架构——贪心 + iterative deepening 2 算法组合,排除 A*/MCTS/full beam | §8.5, §11, 附录 A |

### v1.6 → v1.7(1 条 — beam search 替代)
| # | 修 | 条 |
|---|---|---|
| 1 | 显式竞争假设模式:`need: model_selection` 问题 → Phase 0.7 展开成 K 互斥竞争 claim(共享 `competitor_group`)+ C0b(K 中 ≥1 terminal 且其余 REFUTED/DEFERRED → 问题回答)。替代 full beam search,用 claim 层竞争拿模型并行收益,不引入多世界 fact base | §2, §7 0.7, §8 C0b, 附录 A |

### v1.5 → v1.6(6 条 — Santa R4 接缝缺口)
| # | 修 | 条 |
|---|---|---|
| 1 | C0 改为 note 持 verify_status + cites terminal fact(含 NEGATIVE/REFUTED/DEFERRED)——解 schema 矛盾(fact 无 verify_status)+ 不可答问题死锁 | §8 C0, 附录 A |
| 2 | claim-register.yaml 入 cold-restart(8 文件)——用户反馈跨 session 不丢 + C1/C2 可验 | §5, §13 |
| 3 | task_spec 变更检测:task_spec_snapshot.yaml 比对 + re-plan 触发细则 | §15 |
| 4 | time_budget 强制:Phase 0 写 deadline_ts,§11 PreToolUse (d) 检查 | §7 0.4, §11 |
| 5 | hook 工具意图通道:dispatch payload `intended_tools` 字段 + PostToolUse 实际工具扫描后置校验 | §11 |
| 6 | Phase 0 全步幂等 + 0.5 schema 迁移(pre-v1.5 claim-register) | §7 |

### v1.4 → v1.5(3 条)
| # | 修 | 条 |
|---|---|---|
| 1 | task_spec.yaml 作一等输入(问题/范围/约束/深度/交付);加 O0 + C0;re-plan 加 task_spec 外部更新触发 | §1, §2, §8, §9, 附录 A |
| 2 | Phase 0 SETUP(hook 安装 + scaffold + task_spec 摄入 + pre-flight + claim 种子) | §7 |
| 3 | 用户反馈双层怀疑(认知 artifact 裁决 + 程序 orchestrator 自决);硬禁律 #3 重写;打断不转移控制权 | §9, §10 |

### v1.3 → v1.4(2 条)
open 集合加 numeric / terminal 集合加 NEGATIVE+REFUTED(收敛死锁修复)

### v1.2 → v1.3(9 条)
C3 用 fact status / C4 composite type 排 finding / lint 作用=error check / ≤3 双 hook / _INDEX schema / per-claim cap hook / C7 软收敛 / WAL 幂等 / 动态 trace 归一化

### v1.1 → v1.2(12 条)
C4 机器验 / re-plan refutation / 动态 verify / cold-restart 多文件 / 纯度 redefine / ≤3 hook / defer cap / 目录无序 / 术语 / agent type 澄清 / WAL / sample-class
