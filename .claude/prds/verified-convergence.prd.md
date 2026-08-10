# Verified Convergence — 自主的信任前提

> PRD(requirements 级)。实现细节(file/task)留给 `/plan`。
> 证据来源:`docs/refactor/loop-engineering.md`(研究)+ 2026-08-10 workspace 实测诊断 + 先例调研。

## Problem

kunglao-agent 的"CONVERGED"今天**不保证产出可信**——实测当前 workspace 的 47 条 PROVEN claim 中 **46 条未经独立 BLIND 验证(≈98% 假 PROVEN)**。maker-checker 机制(v1.9.22 BLIND verifier)存在但**未强制覆盖到每条 promotion**。结果:无人监督跑出来的"收敛"建立在未验证的结论上,"高质量"不可能。**这是自主的硬拦截器,不是限制条件**——自主要么可信,要么没意义。

## Evidence

- **实测(2026-08-10 workspace 诊断)**:47 PROVEN,仅 1 条在 `facts/_INDEX.md` 有 BLIND 签字 → **46/47 未独立验证(98%)**。
- **实测**:18/54 orphan claims 收敛时 terminal(未链 `primary_question` 就结了)。
- **实测**:`progress.txt` 中 `doubt_checker` 仅 2 次提及 → 验证门几乎没触发。
- **实测**:primary_questions q1-q5 均有 terminal claim,但若这些 claim 属于 46 条未验证之列,则"答完"≠"可信答完"。
- **先例**:[Towards AI — multi-agent self-verification](https://pub.towardsai.net/how-multi-agent-self-verification-actually-works-and-why-it-changes-everything-for-production-ai-71923df63d01)"a single LLM can't reliably verify its own outputs; a separate LLM evaluates against a structured rubric";[LangChain forum — Independent Verification Layer](https://forum.langchain.com/t/independent-verification-layer-for-llm-output-beyond-retrieval-guardrails/2869);[EmergentMind — Verification Agent](https://www.emergentmind.com/topics/verification-agent)。**独立验证是自主质量的已知机制**,kunglao 有它但没强制。

## Users

- **Primary**:无(自主前提 = 产出对系统自身可信,无 mid-analysis human gate)。
- **Not for**:需要在分析过程中人工判断的场景(那是 assistant,不是 autonomous engine)。

## Hypothesis

我们相信**{把 BLIND 独立验证强制覆盖每条 PROVEN promotion + 完整性门(primary_questions 全 BLIND 答完 + 零 orphan 收敛)}** 会 **{让"CONVERGED"等价于"全部可证可信"}** 对 **{自主 RE 协作}**。我们将在**{真实样本无人监督跑完,产出 100% PROVEN 过 BLIND + 0 orphan 收敛 + 0 假收敛}** 时知道自己对了。

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| BLIND 覆盖率 | 98% → **100%** PROVEN | 脚本:`facts/_INDEX` BLIND 签字数 / PROVEN claim 数 |
| orphan 收敛 | **0** | 收敛门:orphan claims terminal 时 block CONVERGED |
| 假收敛(假 CONVERGED) | **0** | SPINNING flatline 检测 + primary_q 全答门 |
| primary_question 可信答 | **5/5 BLIND-verified** | 每 q 的 terminal claim 经 BLIND |

## Scope

**MVP** — 让"PROVEN"与"CONVERGED"机械反映真实验证与完整(不是"没活干"):
1. **BLIND 强制**:每条 PROVEN promotion 必须有独立 verifier 签字,否则降级 STAMP(不可信)。
2. **完整性门**:CONVERGED 需 primary_questions 全部 BLIND-verified + 零 orphan。
3. **假收敛拦截**:SPINNING flatline + false-completion 的机械检测。
4. **loop 跑到真收敛**:heartbeat 不假死(让门 1-3 能 fire)。

**Out of scope**
- hill-climbing L4(SaaS 规模,单用户 ROI 负)
- digest 冷启动接线(Opus 1M 非瓶颈)
- loop-audit / STATE-drift(与 acceptance_check / plan_drift_detector 重叠 90%+)
- "家族归属等判断不可自动"——伪命题(CLAUDE.md V3:对 artifact 求证,硬编码指纹机器可证)

## Delivery Milestones

<!-- 业务结果,非工程任务。/plan 把每个转成实现计划。 -->

| # | Milestone | Outcome(用户可见) | Status | Plan |
|---|---|---|---|---|
| 1 | PROVEN = verified | 每条 PROVEN 必有 BLIND 签字(98%→100%);无签字自动降级 STAMP | pending | — |
| 2 | CONVERGED = complete + verified | 收敛需 primary_q 全 BLIND 答 + 零 orphan + 零假收敛 | pending | — |
| 3 | Loop 跑到真收敛 | heartbeat 不假死,门 1/2 能在无人监督下 fire 到真完成 | pending | — |
| 4 | 现存 46 假 PROVEN 清账 | 批量补验证 / 标 UNVERIFIED / 重跑,诚实暴露历史假自主 | pending | — |

## Open Questions

- [ ] 现存 46 条未验证 PROVEN 如何处理?批量补 BLIND / 标 UNVERIFIED / 重新跑?(里程碑 4)
- [ ] 强制 BLIND 后,verifier 持续 REFUTE 会不会让 loop 卡死?需 escalation 路径。
- [ ] BLIND verifier 对每条 claim 的 token 成本可接受吗?是否需批量验证或 tier 分级?
- [ ] orphan claims 的"链 primary_question"是 seed 时补,还是收敛门强制归类?

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 强制 BLIND 大幅增加 token(verifier 调用 ×N) | 高 | 中 | 批量验证 / 关键 claim 优先 / tier 分级 |
| 现存 46 PROVEN 补验证发现大量错误 → 大返工 | 中 | 高 | 诚实接受;这是"假自主"的必要暴露 |
| verifier 自身不可靠(LLM-as-judge 局限) | 中 | 高 | 多 path 验证(verifier ≥2 法一致才 PROVEN) |
| heartbeat 修复后仍偶发 STALE(RC3-5 未全修) | 中 | 中 | F1 先行,F2-F4 渐进 |

---
*Status: DRAFT — requirements only. Implementation planning pending via `/plan .claude/prds/verified-convergence.prd.md`.*
