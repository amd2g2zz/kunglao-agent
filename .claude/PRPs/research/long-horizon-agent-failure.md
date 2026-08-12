# Research: long-horizon agent failure / execution drift / premature termination / state-management failure

**Source**: deep-research workflow `wf_5c50b792-f7c` (2026-08-11), 107 agents, 25 sources fetched, 124 claims extracted, 25 verified (18 confirmed / 7 refuted / 0 unverified). Full output: `C:\Users\hr\AppData\Local\Temp\claude\D--works-samples-2026-07-01\b3f676f3-8924-4859-aa9f-c1a2c2c2987a\tasks\wz5jjv9rq.output`.

**Purpose**: ground the #39 external-kicker redesign (and #36/#38 more broadly) in the literature on long-horizon agent failure, replacing the oversimplified "detect idle → restart session" framing with a trajectory-length / state-representation model.

---

## Verified findings (cited)

### F1 — The dominant failure surface is process/state-level, not model-capability (HIGH, 3-0 / 2-1)
HORIZON (arXiv 2604.11978, Wang et al., UC Berkeley, 3100+ trajectories, 4 domains, GPT-5/Claude-4) attributes **72.5% of failures to process-level causes** (planning, environment, instruction, history error) vs **27.5% design-level** (memory limitation, catastrophic forgetting, false assumptions). A 7-category taxonomy validated by a trajectory-grounded LLM-as-a-Judge pipeline (human-judge kappa=0.84 vs inter-annotator kappa=0.61). Stronger models reduce invalid proposals but do **not** remove the need for durable state, audit trails, permission boundaries, and side-effect governance.

> **Implication**: fixing the harness/orchestrator (process layer) is the correct altitude — not swapping models. kunglao's gates, ledger, claim-register are the right machinery; the gap is enforcement, not capability.

### F2 — Degradation is a qualitative regime shift, not linear decay (MEDIUM, 2-1)
Success stays near-optimal on short/mid-horizon tasks then **collapses abruptly at domain-specific horizon thresholds**, after which no model differential remains ("a universal breaking point is unattainable"). Scaling model size or training length alone cannot fix it. Strong per-subtask competence does **not** reliably translate into end-to-end success (the plan-execution gap).

> **Implication**: detection cannot be linear-time-based ("25 min of inactivity"). An agent mid-flight with fresh heartbeat can already be past its collapse threshold. The detector must read **state signatures**, not clock.

### F3 — Execution drift (SED): step-local-invisible, self-amplifying (MEDIUM, 3-0 / 2-1)
Semantic-Execution Drift (ReflectiChain, MDPI Electronics 15(15):3452): executed actions progressively deviate from the original language constraints **even when the agent appears to reason competently at each step**. Recurrence `D(t+1)=α·D(t)+ε(t)+β·P(t)`; α≥1 → self-amplifying (ReAct α=1.047); α<1 → contraction (ReflectiChain α̂=0.823, 95% CI [0.794, 0.852]). "An agent can complete a task successfully while systematically violating constraints through reinterpretation" — **drift can be invisible to task-success and constraint-compliance metrics**.

> **Implication**: the "呆住" the user observed is not "session idle" — it is **active-but-drifting**: orchestrator keeps ticking, keeps writing ledger rows, but state never advances because it is operating on a degraded internal representation. Time-stale detection (no new rows) misses this; only **state-signature rotation** (repeated identical snapshots) catches it.

### F4 — Termination failures: commitment drift, not attention/binding drift; "LLM saying done is not an event" (MEDIUM, 2-1 / 3-0)
arXiv 2608.04066 ("The LLM Proposes, the Executive Disposes"): ablating the external, code-executed **commitment store** flips goal-abandonment from **0.00 → 1.00** while binding error stays flat at 0.00 (52 runs, ~17M tokens, 200-400-action horizons on ARC-AGI-3). Goal abandonment is **commitment drift, not binding drift**. Verbatim (§2): *"achievement is a fired predicate over logged events ('an LLM saying done is not an event')"*.

> **Implication**: kunglao's behavior #5 (false-completion trap: open-claim count is truth) is the right principle. The kicker's resume prompt for a kicked session must be built from **fired predicates over logged state** (ledger last row + claim-register open + facts count + worker-status files), never from the dying session's self-narrative of "what I was doing".

### F5 — Remediation = externalize belief into a deterministic runtime (MEDIUM, 2-1 / 3-0)
arXiv 2608.04066 + Cambridge Open Engage (Chen, v2 2026-07-11): the remedy direction is to give a **deterministic Executive** ownership of all belief (the LLM may only file typed proposals), use **append-only stores** with **computed-never-overwritten status**, and admit a claim only when a prediction **pre-registered before acting** is matched against observation by code ("the model cannot author a match it did not pre-commit to"). *"Future long-horizon agent reliability will depend less on prompt accumulation and more on explicit runtime systems that manage what the model is allowed to know, change, commit, forget, and recover."*

> **Implication**: kunglao already does most of this (ledger append-only; convergence_check computes decisions from files; verifier = blind forward-derivation). The missing pieces: **forget** (trajectory compaction / context rotation) and **recover** (external kicker — exactly #39). The re-anchor injection (state_anchor hook) is the missing "what the model is allowed to know" governance at the per-turn level.

### F6 — Trajectory-level failure attribution is immature (HIGH, 3-0)
IEEE TSE early-access survey (DOI 10.1109/TSE.2026.3717765, 2026-08-10, 55 papers 2025-04-2026): agent failures are **not code defects** — they are embedded in lengthy, language-heavy execution trajectories that obscure root causes. Step-level failure attribution accuracy remains limited; benchmark diversity is a bottleneck.

> **Implication**: our mechanical detectors (state-signature rotation, stale-worker mtime) are pragmatic approximations, not ground truth. The plan must keep thresholds tunable and treat the rotation heuristic as "best-evidence signal, escalate to hook re-anchor before kick", not as a hard correctness oracle.

---

## Refuted claims (do NOT cite as evidence)
- *"explicit state tracking improves success by 9pp (p=0.02)"* — 0-3 killed, fabricated source (zenodo).
- *"failures cluster into six mutually exclusive categories: prompt decay 29% / tool misuse 22% / … / Fleiss κ=0.82"* — 0-3 killed, fabricated.
- *"deterministic planning heuristics outperform stochastic sampling by 68% vs 12pt deficit (p=0.004)"* — 0-3 killed, fabricated.
- *"reasoning degradation up to 30% on hard tasks"* — 0-3 killed.
- *"models below 13B cannot self-correct reasoning via prompting"* — 0-3 killed.

These are repeated in low-quality aggregators/zeroshare mirrors — treat any uncited numeric in this space as suspect.

---

## Caveats (carry into the plan)
1. **Source-quality skew**: only F6 (IEEE TSE survey) is top-tier peer-reviewed. F1 rests on an unpeer-reviewed preprint; F3 on a mid-tier journal with a bespoke SED metric on one custom benchmark (Sema-Sim); F4 on a single-author preprint whose own empirical results are **null** (zero completions in 52 runs — it is an architectural stance, not a demonstrated efficacy).
2. **No independent replication** exists for any headline number (72.5/27.5, α̂=0.823, 0.00→1.00). Each is single-source, single-pipeline, and the HORIZON kappa=0.61 human-human < 0.84 human-judge pattern is unusual.
3. **Benchmark-scale only**: all horizons studied are minutes-to-~400-actions; none cover multi-day real-world deployments. Applicability to kunglao (multi-hour RE workflows) is an extrapolation.
4. **Time-sensitive**: every source is April–August 2026. F1's paraphrased phrases were verifier-flagged as non-verbatim (the 72.5/27.5 split and process/design labels are verbatim; the qualitative-distinctness phrasing is not).

---

## Mapping to kunglao-agent architecture

| Literature concept | kunglao mechanism | Gap addressed by #39 redesign |
|---|---|---|
| context rot (F2/F3) | cold-start 8-file read; mid-iteration re-read heuristic | **state_anchor hook**: per-turn mechanical state injection (prevention, not just detection) |
| execution drift / step-local-invisible (F3) | convergence_health.py reads ledger | **state-signature rotation detector**: ≥3 identical ledger rows → drift; time-stale alone misses active drift |
| commitment drift / "LLM saying done ≠ event" (F4) | behavior #5 false-completion trap; blind verifier | **fired-predicate resume prompt**: kick prompt built from ledger/facts/claims, never from dying session's narrative |
| deterministic Executive owns belief (F5) | ledger append-only; convergence_check computes | #39's kicker = "recover" governance (the missing runtime function); hook = "what model may know" per turn |
| qualitative regime shift at horizon threshold (F2) | 35-min heartbeat stale | **dead = time; drift = signature** — two distinct detectors for two distinct failure classes |

## Open questions for kunglao (carried forward)
- Do the SED α and 0.00→1.00 ablation numbers apply to RE orchestrators (domain-stratified decay suggests no universal threshold)?
- Is the "呆住" we see commitment drift (F4) or constraint reinterpretation (F3) — same underlying mechanism (loss of externalized constraint representation) or distinct? Affects which detector fires first.
- Where is kunglao's horizon-collapse threshold? At 5-min ticks × N turns × M workers — measure before fixing thresholds.

---

## Sources (canonical URLs only)
- https://arxiv.org/abs/2604.11978 — HORIZON (F1, F2, F6 partial)
- https://www.mdpi.com/2079-9292/15/15/3452 — ReflectiChain / SED (F3)
- https://arxiv.org/abs/2608.04066 — LLM Proposes, Executive Disposes (F4, F5)
- https://www.cambridge.org/engage/coe/article-details/6a4abb75810b9dcc82ce84f2 — Chen, State-Aware Runtime (F1, F5)
- https://arxiv.org/abs/2607.05775 — Beyond the Leaderboard synthesis (F2)
- https://www.computer.org/csdl/journal/ts/5555/01/11626967/2iuF5rxPMqs — IEEE TSE trajectory-analysis survey (F6)
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents — Anthropic harness guidance (heartbeat/checkpoint; objective-tracking artifact vs "declare done")
- https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools — Anthropic context engineering ("context rot")
