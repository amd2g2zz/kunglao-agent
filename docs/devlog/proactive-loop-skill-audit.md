# Orchestrator Proactive Loop Skill Audit (#126 / S2-8)

## Decision: Archived — superseded by mechanical gates

The `orchestrator-proactive-loop` learned skill (~/.claude/skills/learned/) is superseded
by the mechanical enforcement gates implemented in #95-#99:
- env self-recovery → hooks/dispatch_gate.py
- parallel dispatch → hooks/worker_budget.py (≤3 concurrent)
- note forced verifier → convergence_check.py DISPATCH_VERIFIER decision

No SKILL.md reference needed — the behaviors are now mechanically enforced.
