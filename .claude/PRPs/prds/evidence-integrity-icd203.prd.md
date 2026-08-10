# Evidence Integrity & ICD-203 Conformance

> PRD(requirements 级)。实现细节留给 `/prp-plan`。
> 证据来源:本会话 research(loop-engineering / verified-convergence M1-M4 / ICD-203 gap / 证据完整性实测)+ workspace 诊断。

## Problem Statement

verified-convergence(M1-M4)刚让"PROVEN / CONVERGED"机械可信(BLIND 强制 + 完整门),但 **PROVEN 背后的证据本身仍有损且不合规**:实测 F023 的 provenance 引派生 `summary.json` 而非旁边的原始 `full_trace.txt`;无 evidence index(原始存在却不可溯/不可引);ICD-203 tradecraft 三缺口(源可靠性未标 / 概率阶梯 3 档 vs 7 档 / dissent 无记录位);46 历史假 PROVEN 因无索引无法批量溯原始 re-verify。结果:自主产出的证据链**有损(摘要代原始)+ 非 ICD-203 合规**,既不可信也不达标。

## Evidence

- **实测(F023 反例)**:`facts/F023-no-network-30s.md` provenance = `analysis_artifacts/vm_runtime/summary.json`(派生),而 `analysis_artifacts/vm_runtime/full_trace.txt`(原始)就在旁边却没进证据链。
- **实测**:`evidence/_INDEX` 不存在 —— 无证据索引层;fact 靠路径 ad-hoc 引(`evidence/x64dbg-*.txt`),无注册表。
- **实测**:facts 87% 有 verbatim,但**动态维(F020-F025)summary-only**(引派生不引 raw)。
- **ICD-203 gap(本会话分析)**:源可靠性(Admiralty A-F/1-6)只在 verdict-scorer,fact/evidence 级无;`confidence` 3 档(confirmed/highly_likely/suspected)vs ICD-203 7 档;BLIND REFUTE/DIFF 无正式 dissent 记录位。
- **C-020 事故(全局规则 maker-checker.md)**:审查者查转述摘要不查原始字节 → 全链错锚。存储 verbatim ≠ verifier 收 raw。
- **46 假 PROVEN(M4 审计)**:无 evidence index → 无法批量溯每条的原始证据做 re-verify。

## Proposed Solution

建**证据索引层 + 机械门 + ICD-203 tradecraft 编码**:每条原始证据完整存盘 + 进 `evidence/_INDEX`(eid→完整路径+hash+type+provenance);fact provenance 必引索引条目(指向完整原始),派生(summary.json/correlated.json)不算证据,缺则 invalid;每条证据标 ICD-203 源可靠性(Admiralty)+ 概率阶梯扩到 7 档 + BLIND verifier 的 REFUTE 结构化为 dissent。这层让证据链**非有损(索引引完整原始)+ ICD-203 合规**,且解锁 46 假 PROVEN 的批量 re-verify。

## Key Hypothesis

我们相信**{证据索引层 + provenance 引原始门 + ICD-203 tradecraft 编码}** 会**{让自主产出的证据链非有损 + 合规}** 对**{自主 RE 协作}**。我们将在**{真实样本跑完后,evidence-index 覆盖 100% facts、0 派生-cite、ICD-203 tradecraft 检查全过、46 历史可经索引溯原始}** 时知道自己对了。

## What We're NOT Building

- **内联所有原始进 markdown** —— 大二进制(pcap/dump)存盘 + 索引引路径 + hash,不内联(体积不是降保真理由,但内联不是机制;索引才是)。
- **重写证据采集** —— 原始大多已采(full_trace.txt 存在),只缺索引;不重采,只索引 + 引。
- **ICD-203 全套合规认证** —— 只做 tradecraft #1(源可靠性)/#2(概率阶梯)/#5/#8(dissent)/#9(引证)五条与证据直接相关的;timeliness/independence(已在 M1)等不重复。
- **verifier 自动重跑所有 raw** —— forward-derive 是方向,但"强制 verifier 重解析 pcap"超出本 PRD;本 PRD 只保证 verifier **能**经索引拿到 raw(路径可溯),不强制其重跑。

## Success Metrics

| Metric | Target | How Measured |
|---|---|---|
| evidence-index 覆盖率 | **100%** facts 有索引条目引完整原始 | 脚本:fact provenance → index eid → path 可解析 + hash 匹配 |
| 派生-cite 数 | **0**(fact 不得仅引 summary.json/correlated.json) | provenance gate 拒派生-only |
| ICD-203 源可靠性覆盖 | **100%** evidence 条目带 Admiralty 评级 | index 每条有 source_reliability 字段 |
| 概率阶梯 | **7 档**(almost certain → almost no chance)映射 | confidence schema 扩 + 现有 3 档映射 |
| BLIND dissent 记录 | **100%** REFUTE/DIFF 结构化记录 | blind_gate 写 dissent 块(verifier finding) |
| 46 历史可溯 | **46/46** 经索引找到原始证据路径 | 审计脚本扩展 |

## Open Questions

- [ ] 源可靠性评级谁来打?maker 标 + verifier 校?还是按证据类型机械默认(binary 直接观察=A1,CTI 第三方=C5)?
- [ ] 概率阶梯 7 档映射:现有 `confirmed` → `almost certain`,`highly_likely` → `very likely`,`suspected` → `roughly even`?中低档如何引入不破坏现有?
- [ ] 大二进制证据(pcap/dump)存哪?进 git(LFS)?还是 workspace 本地 + hash 锚(不进 git)?
- [ ] dissent 记录位:进 fact 文件?独立 `dissents/D-NN.md`?还是 claim-register 字段?
- [ ] evidence index 格式:markdown 表格(人读)vs json(机读)?或双格式?

---

## Users & Context

**Primary User**
- **Who**:自主 RE loop 本身(须自证证据可信)+ 报告消费者(信其可溯合规)。无 mid-loop human gate。
- **Current behavior**:产 fact/note 引证据,但部分引派生、无索引、无源评级、概率 3 档、dissent 不记。
- **Trigger**:verified-convergence 后,证据层成下一失效面(research 刚指出)。
- **Success state**:每条证据经索引可溯完整原始 + ICD-203 合规 + 46 可批量 re-verify。

**Job to Be Done**
当自主 loop 产出一条 PROVEN claim 时,我要它的每条证据都能经索引回溯到完整原始(非派生、非摘要)、带源可靠性与不确定度、且异议有记录,这样报告消费者能信 + 审计能过。

**Non-Users**
- 需 mid-analysis 人工判断的场景(assistant 非 autonomous)。
- 不需证据可溯/合规的快筛(本 PRD 是 deep 分析的信任前提)。

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|---|---|---|
| Must | **Evidence Index**(`evidence/_INDEX` + 注册现有 raw) | 整个机制的前提;无索引则 provenance 无处引 |
| Must | **Provenance Gate**(fact 必引索引条目→完整原始;派生拒) | 治"摘要代原始"根因(C-020/F023) |
| Must | **ICD-203 源可靠性**(每条 evidence Admiralty 评级) | Tradecraft #1,ICD-203 合规核心 |
| Should | **概率阶梯 7 档**(扩 confidence schema + 映射) | Tradecraft #2 |
| Should | **BLIND dissent 结构化**(REFUTE 记录 verifier finding) | Tradecraft #8 + 闭环 maker-checker |
| Could | **46 re-verify 流程**(经索引批量溯原始) | 解锁 verified-convergence 未竟;依赖索引 |
| Won't | 内联大二进制 / 重采集 / verifier 强制重跑 raw | 见 NOT Building |

### MVP Scope

Evidence Index + Provenance Gate + 源可靠性评级 —— 这三件事让证据链非有损 + 每条证据标源可靠性。其余(概率阶梯/dissent/46 re-verify)增量。

### User Flow

`worker 采证据 → 原始存盘 → 注册进 evidence/_INDEX(eid+path+hash+type+source_reliability) → fact provenance 引 eid → provenance gate 验(path 解析+hash 匹配+非派生)→ PROVEN 提升时 BLIND verifier 经索引拿 raw 做 forward-derive → REFUTE 结构化为 dissent → 报告引索引(消费者可溯)`

---

## Technical Approach

**Feasibility**:HIGH —— 原始证据大多已采(full_trace.txt 等);机制是索引 + 门 + schema,非重采集。M1 blind_gate 已证明"机械门 on provenance"模式可行,复用。

**Architecture Notes**
- `evidence/_INDEX.md`(人读)+ `evidence/_index.json`(机读)双格式,index 为权威。
- provenance gate 扩 M1 的 `blind_gate` 模式:校验 fact provenance → index eid → path 解析 + sha256 匹配 + type≠derivation。
- Admiralty 评级:按证据类型机械默认(binary 直接观察=A1,decompile=A2,CTI 第三方=C5,sandbox=D3)+ maker 可改 + verifier 校。
- 概率阶梯:confidence schema 扩 7 档 + 现有 3 档向后兼容映射。
- dissent:blind_gate REFUTE 路径写 `dissents/` 或 fact 内结构化块。

**Technical Risks**

| Risk | Likelihood | Mitigation |
|---|---|---|
| 大二进制(pcap)存储/hash 成本 | 中 | 存盘+hash 不内联;git LFS 或本地+hash 锚 |
| 现有 46 fact 回填索引工作量大 | 高 | 脚本批量注册(原始路径已知)+ 人工补 hash |
| 源可靠性评级主观(maker 乱标) | 中 | 机械默认 + verifier 校(同 BLIND) |
| index 格式双写漂移(md/json) | 中 | index.json 权威,md 由脚本生成 |

---

## Implementation Phases

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|---|---|---|---|---|---|
| 1 | Evidence Index | 建 `evidence/_INDEX` + 注册现有 raw(eid/path/hash/type/provenance) | complete | - | - | PR#28 `86b6ae1` |
| 2 | Provenance Gate | fact provenance 必引索引→完整原始;派生拒(M1 blind_gate 模式扩展) | complete | - | 1 | PR#29 `5728d90` |
| 3 | ICD-203 Source Reliability | 每条 evidence Admiralty 评级(机械默认+verifier 校) | complete | with 4 | 1 | PR#31 `e78e064` |
| 4 | Probability Ladder + Dissents | confidence 扩 7 档 + BLIND REFUTE 结构化 dissent | complete | with 3 | 1 | PR#30 `676f83b` |
| 5 | 46 Re-verify via Index | 经索引批量溯 46 假 PROVEN 原始 + 补 BLIND/标 UNVERIFIED | complete(审计) | - | 1, 2 | PR#32 `121162b`(47 PROVEN:10 has-raw / 18 derivation-only / 19 unverifiable) |

### Phase Details

**Phase 1: Evidence Index**
- **Goal**:证据可溯 —— 每条原始证据注册进索引,完整路径+hash 可引。
- **Scope**:`evidence/_index.json`(权威)+ `_INDEX.md`(脚本生成);批量注册现有 evidence/ + analysis_artifacts/ 原始(full_trace.txt/x64dbg-*.txt/pcap/dump);每条 {eid, path, sha256, type, capture_provenance, source_reliability?, backs_claims}。
- **Success signal**:索引覆盖现有全部原始证据;随机抽 eid → path 解析 + hash 匹配。

**Phase 2: Provenance Gate**
- **Goal**:堵"摘要代原始" —— fact provenance 必引索引条目指向完整原始,派生拒。
- **Scope**:扩 blind_gate:`check_provenance_gate(fact) → provenance 引 eid → index 解析 → path 存在 + hash 匹配 + type≠(summary/correlated/derived)`;无索引引或仅引派生 → invalid。
- **Success signal**:F023 改引 full_trace.txt(经索引)后过门;新 fact 引派生-only 被拒。

**Phase 3: ICD-203 Source Reliability**
- **Goal**:每条证据标源可靠性(Admiralty A-F/1-6)。
- **Scope**:index 每条加 source_reliability;机械默认(binary direct=A1,decompile=A2,CTI=C5,sandbox=D3)+ maker 可改 + verifier 校。
- **Success signal**:100% evidence 条目带评级;verifier 抽校。

**Phase 4: Probability Ladder + Dissents**
- **Goal**:ICD-203 #2(7 档概率)+ #8(dissent 记录)。
- **Scope**:confidence schema 扩 7 档 + 现有 3 档映射;blind_gate REFUTE 路径写 dissent(verifier finding 结构化)。
- **Success signal**:confidence 7 档可用;BLIND REFUTE 产出 dissent 记录。

**Phase 5: 46 Re-verify via Index**
- **Goal**:经索引批量溯 46 假 PROVEN 原始,补 BLIND 或标 UNVERIFIED。
- **Scope**:审计脚本(audit_legacy_proven)扩展 —— 经索引找每条原始路径 → 批量派 BLIND verifier 或标 UNVERIFIED;产出清账报告。
- **Success signal**:46 条全处置(re-verified PROVEN 或 UNVERIFIED)。

### Parallelism Notes

Phase 1(索引)是前提,单独先行。Phase 2(门)依赖 1。Phase 3(源可靠性)+ Phase 4(概率/dissent)依赖 1 但**彼此独立,可并行**(都改 index/confidence schema 不同字段)。Phase 5 依赖 1+2。最大并行度:1 → (2) → (3 ∥ 4) → 5。

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| 证据引用机制 | 索引引完整路径 | 内联全文 / 仅 hash | 大证据不内联(体积),不裁剪(保真);索引引完整路径 = 无损+可导航 |
| 派生算不算证据 | 不算 | 派生可引 | 派生是有损压缩;C-020/F023 证明引派生=断链 |
| 概率阶梯 | 扩到 7 档 + 映射 | 保 3 档 | ICD-203 #2 要求 7 档;3 档缺中低分辨 |
| 大二进制存储 | 存盘+hash 不内联 | 内联 / 不存 | 保真(完整存)+ 可溯(hash 锚);不内联进 md |
| dissent 位置 | 结构化记录(verifier finding) | 自由文本 | ICD-203 #8 + maker-checker 闭环 |

---

## Research Summary

**Market/Standards Context**
- ICD-203(ODNI Analytic Standards):5 分析标准 + 9 tradecraft 标准;要求结构化概率阶梯、源可靠性描述、证据正确使用、dissent 记录。kunglao 部分符合(7/14),缺源可靠性/概率阶梯/dissent。
- 取证 chain-of-custody:证据须可溯到原始 artifact,不断在中间产物。
- maker-checker forward-derive(verifier 从 raw 正向推导,不读摘要):C-020 事故的根治原则。

**Technical Context**
- 现状:87% facts verbatim(静态 byte-backed);动态维(F020-F025)引派生 summary.json;无 evidence index;46 假 PROVEN 无索引难批量 re-verify。
- 可复用:M1 blind_gate(机械门 on provenance 模式)、audit_legacy_proven(审计脚本)、verdict-scorer 的 Admiralty 评级逻辑。
- 机制:索引引完整原始路径(用户指定)—— 不内联、不裁剪、不丢。

---
*Generated: 2026-08-10*
*Status: DRAFT — needs validation via 实测回填 + 真实样本端到端*
