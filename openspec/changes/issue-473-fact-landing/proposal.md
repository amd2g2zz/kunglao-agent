## Why
Rounds 5-7A live evidence: workers do real RE (round-6 decoded the full algorithm skeleton in 51 min) but NEVER land a fact inside a 30-min act — 7×rc-1 timeouts in round-7A, facts=0, idle-circuit-breaker ends runs. Workers PLAN "facts written immediately as each parameter is pinned" but treat facts as requiring final verified answers and batch them at an end they never reach. The register supports intermediate facts (boundary_type positive_observation); workers don't use them mid-act.

## What Changes
1. Dispatch envelope guidance: intermediate findings MUST be written as facts (positive_observation) as soon as established; final numeric claims upgrade later facts rather than waiting for full verification. Plus the STATUS line protocol (STATUS: DONE / STATUS: BLOCKED) for precise outcome parsing.
2. CLAUDE_ACT_TIMEOUT_S becomes env-overridable (KUNGLAO_E2E_ACT_TIMEOUT_S, default 1800, garbage→default) so rounds can run longer acts without code changes.

## Impact
scripts/e2e/checkpoints.py (dispatch envelope), scripts/e2e/llm_faces.py (timeout). No behavior change for existing tests.
