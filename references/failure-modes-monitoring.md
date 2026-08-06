---
name: kong-agent-failure-modes-monitoring
description: Monitoring (F7-F13): worker help / self-doubt / state discipline (split from failure-modes.md for progressive disclosure). Load when the user reports a specific failure-mode pattern (e.g. 笨/卡/不匹配) and the dispatcher needs the matching F-row + enforcement script.
metadata:
  type: reference
  parent: failure-modes.md
---

# Monitoring (F7-F13): worker help / self-doubt / state discipline

Failure modes covering orchestrator discipline during in-flight work:
  - F7: orchestrator 视而不见 subagent 求助 (passive when worker asks help)
  - F8: 自信但错 (self-confident false PROVEN)
  - F9: 成本警告被打断 (cost warning interrupts workflow)
  - F10: hook 全开噪声 (no selective activation)
  - F11: 不会回退 (stuck -> still trying)
  - F12: 重复工作 (no reuse of existing facts)
  - F13: 反问 (orchestrator asks 'should I dispatch?')


## Full F-row table (this domain only)

| ID | Symptom | Self-check question | Blocker |
|----|---------|---------------------|---------|
| F7 | Orchestrator ignores worker help_request | has the worker been waiting >5 min without your response? (active_intervention.py gate) | B1d |
| F8 | Self-confident false PROVEN | verifier_id != worker_id? (no self-stamp; F-8 anti-pattern) | B1g |
| F9 | Cost warning interrupts workflow | are you at tier=advisory / pause_non_essential / HARD_PAUSE? (cost_gate.py output) | B1h |
| F10 | Hook noise (all hooks always on) | did you check is_active() before running? (hook_activation.py) | B1i |
| F11 | Stuck worker doesn't backtrack | did you require ## backtrack section? (stuck > 20 min -> backtrack_gate.py) | B1j |
| F12 | Workers do repeat work, no reuse | did you cite existing fact or justify fresh? (reuse_gate.py) | B1k |
| F13 | Orchestrator fan-wen (should I dispatch?) | are you about to ask user? (NO - see F-13: just decide) | B1k (self-redirect) |

## Run all enforcement gates (orchestrator /loop heartbeat)

```bash
python C:/Users/hr/.claude/skills/kunglao-agent/scripts/progress_report.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/stale_blocker_prune.py <ws> --dry-run && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/claim_expiry.py <ws> && \
  python C:/Users/hr/.claude/skills/kunglao-agent/scripts/plan_drift_detector.py <ws>
```
