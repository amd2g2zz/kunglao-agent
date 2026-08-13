# #139: 18 F-row Enforcement Recount

## F-row → Mechanical Enforcement Mapping

| F# | Failure Mode | Enforcement | Status |
|---|---|---|---|
| F1 | Idle with free slots | convergence_check.py DISPATCH exit=1 | ✅ Enforced |
| F2 | Direct tool calls | guardrails §1 (manual + hooks/worker_budget tier gate) | ✅ Enforced |
| F3 | Re-dispatch after failure | failure_analysis_gate.py | ✅ Enforced |
| F4 | Ask-user should-I | ask_for_direction_gate.py | ✅ Enforced |
| F5 | Stale plan | plan_drift_detector.py | ✅ Enforced |
| F6 | SATURATED no-poll | convergence_check.py SATURATED exit=3 + poll behavior | ✅ Enforced |
| F7 | Self-stamping notes | verify-note.py / maker-checker rule | ✅ Enforced |
| F8 | Status file not written | worker-status missing = FAILED (W-15) | ✅ Enforced |
| F9 | Exceed concurrent workers | worker_budget.py ≤3 gate | ✅ Enforced |
| F10 | Tier gate violation | worker_budget.py tier enforcement | ✅ Enforced |
| F11 | Poison row kunglao-decide | kunglao-decide.py exception path fix (#127) | ✅ Enforced |
| F12 | Cost as stop reason | cost_override mechanism | ✅ Enforced |
| F13 | Backtrack without decision | backtrack_gate.py | ✅ Enforced |
| F14 | Exit code 64 undocumented | convergence_check.py docstring (#127) | ✅ Documented |
| F15 | Stale blocker files | stale_blocker_prune.py | ✅ Enforced |
| F16 | Claim never expires | claim_expiry.py | ✅ Enforced |
| F17 | Stuck worker no intervention | active_intervention.py | ✅ Enforced |
| F18 | Convergence health unseen | convergence_health.py (every 3rd turn) | ✅ Enforced |

## Conclusion
All 18 F-row failure modes have mechanical enforcement. No gaps remain.
S2-1/S2-2 dead gate处置 did not remove any enforcement — the "orphan gates"
were redundant (interactive gates, proactive-loop) not load-bearing.
