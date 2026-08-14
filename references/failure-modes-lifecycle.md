---
name: kunglao-agent-failure-modes-lifecycle
description: Lifecycle (F1-F6): dispatch / heartbeat / worker routing (split from failure-modes.md for progressive disclosure). Load when the user reports a specific failure-mode pattern (e.g. 笨/卡/不匹配) and the dispatcher needs the matching F-row + enforcement script.
metadata:
  type: reference
  parent: failure-modes.md
---

# Lifecycle (F1-F6): dispatch / heartbeat / worker routing

Failure modes covering the orchestrator's core dispatch loop:
  - F1: idling with slots free
  - F2: forgot the heartbeat (never self-schedules /loop)
  - F3: background monitor but doesn't ping (only pings last-dispatched worker)
  - F4: doesn't re-plan based on subagent return
  - F5: deadlock / zombie wait
  - F6: discards stage-specific agents, uses general-purpose


## Full F-row table (this domain only)

| ID | Symptom | Self-check question | Blocker |
|----|---------|---------------------|---------|
| F1 | Idles with slots free, never dispatches next claim | are you idling with slots free? (slots<3 and open_claims>0 -> dispatch now) | B1a |
| F2 | Never self-schedules /loop | did you schedule /loop? (>=1 worker in flight or >=1 OPEN claim -> heartbeat required) | B1a |
| F3 | Only pings last-dispatched worker | did you check ALL registered workers, not just last-dispatched? (for worker in registry, no short-circuit) | B1d |
| F4 | Doesn't re-plan based on subagent return | did you re-read worker output + re-run priority.py? (every worker return -> re-plan) | B1b |
| F5 | Dead-worker / zombie wait | did you cross-check worker_budget active_workers + TaskList? (dead worker = post_check missing + liveness gone) | B1c |
| F6 | Discards stage-specific agents, uses general-purpose | is this really a general-purpose dispatch? (claim matches stage agent -> use stage-specific) | (self-violation) |

## Run all enforcement gates (orchestrator /loop heartbeat)

```bash
python scripts/progress_report.py <ws> && \
  python scripts/stale_blocker_prune.py <ws> --dry-run && \
  python scripts/claim_expiry.py <ws> && \
  python scripts/plan_drift_detector.py <ws>
```

---

## Termination failures — premature-termination detection (#54)

The 6 dispatch/heartbeat F-rows above cover the orchestrator's RUN loop. A
different failure lives at the CLOSING utterance: the orchestrator declares
"task complete" with open items ≠ 0. This is the 3rd documented recurrence
(2026-07-28 / 07-30 / 2026-08-11; issue #54). Behavior rules #3 (cost is never
a stop reason) and #5 (commit ≠ progress) were already documented WITH
precedent and violated a third time — so a mechanical detector is required,
not another rule.

### Layering vs #43 / #44 (complementary, NOT duplicate)

| Layer | Issue | When | Reads | Catches |
|---|---|---|---|---|
| Runtime drift | #43 | per loop iteration | `.convergence_ledger.jsonl` signature rotation | loop SPINNING (frozen state) |
| Per-turn re-anchor | #44 | Agent-tool completion (hook) | ledger + claim-register + workers | context rot (forgot open claims) |
| Declaration-time | #54 | on the closing utterance | the declaration TEXT + task_text | DECLARING DONE with open items ≠ 0 |

#43 and #44 read MECHANICAL STATE. Neither reads what the agent SAID. The
2026-08-11 session (a2b5e25c) had a HEALTHY moving ledger (3 of 6 gaps fixed)
while the declaration abandoned the user's goal ("全面分析") and cited cost
("$52.85 — informational") as stop reasoning — only #54 catches that.

### The 4 fingerprints (PT1-PT4) + detector

Detector: `scripts/premature_termination_detect.py` (pure stdlib, regex/keyword
heuristics, NO LLM). `detect(transcript, task_text=None) -> dict` or CLI
`python scripts/premature_termination_detect.py <transcript-file>` → JSON
report, exit 0 clean / 1 fired / 2 unreadable input.

| ID | Fingerprint | 2026-08-11 instance evidence | Heuristic |
|---|---|---|---|
| PT1 | self-anchoring | "Substantive task complete" while user said "全面分析" | self-summary done-phrase + task_text anchors absent from the agent region |
| PT2 | self-invented tiering | "备注级（记录即可）" for G4-G6; "deferred" for #10-#12 | tier keyword (not grounded in task_text) + open-item ref |
| PT3 | cost-semantic drift | "$52.85 — informational" in the declaration | cost figure + informational qualifier in one sentence (behavior #3 violation) |
| PT4 | false completion | "task complete" + "Deferred (#10 #11 #12) — queued" | completion declaration + open-items-remaining signal (zero-open phrasing excluded) |

Acceptance: all 4 fire on the issue #54 现象段 regression fixture; 0 fire on a
clean genuine completion. The detector is DETECTION only — the hard Stop-hook
gate is #55's scope (completion_gate.py + task-oracle.yaml), which consumes
this detector's JSON report.
