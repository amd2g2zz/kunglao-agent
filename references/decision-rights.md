# Decision rights — who decides what (three-way matrix)

> Extracted from SKILL.md for progressive disclosure. Every decision falls to
> exactly one layer. No layer may delegate or override its own slice without a
> recorded reason.

| # | Decision | 机械 (script/hook) | LLM (orchestrator) | 用户 |
| --- | --- | --- | --- | --- |
| 1 | Should I dispatch now? (convergence 5-branch) | ✅ `convergence_check.py` | — | — |
| 2 | WHICH claim next? (action ranking) | ✅ `priority_ratio.py` / `priority.py` | — | — |
| 3 | Is the heartbeat alive? (dispatch gate) | ✅ `worker_budget.py` | — | — |
| 4 | May this worker be spawned? (≤3 / cap / tools / tier) | ✅ `worker_budget.py` | — | — |
| 5 | Is this fact byte-verified? (L1 mechanical) | ✅ `kunglao-verify` L1 | — | — |
| 6 | Is this claim adversarially confirmed? (L2) | — | ✅ kunglao-redteam 派发 | — |
| 7 | How to verify a claim? (which reproduce/method) | — | ✅ orchestrator 选 | — |
| 8 | Is a claim PROVEN-terminal? (promotion) | ✅ `claim_migrator`(maker-checker) | — | — |
| 9 | What value/cost weights? | — | ✅ 每轮重排 | — |
| 10 | Method graph update (new node/edge)? | — | ✅ escalate 后 | — |
| 11 | Which action is highest value (RAT value order)? | — | ✅ 按价值序排序 | — |
| 12 | Is analysis CONVERGED (end-to-end done)? | ✅ 收敛判定 | — | — |
| 13 | New sample mount / task scope? | — | — | ✅ |
| 14 | Cost policy / authorization boundary? | — | — | ✅ |
| 15 | VM detonation / x64dbg host-bind? | — | — | ✅ |

Counts: **机械 8** (rows 1-5, 8, 12) · **LLM 6** (rows 6, 7, 9-11) · **用户 5** (rows 13-15).
Mechanical rows run on every tick without LLM; LLM rows may be re-checked by
the next tick's mechanical gates; user rows are the only ones that wait on
human input. See `references/guardrails.md` for the full decision protocol.
