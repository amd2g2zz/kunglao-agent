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

## Evidence-discipline rules for PROVEN promotion (F8 family)

F8 ("self-confident false PROVEN") is the orchestrator-level symptom. The
rules below specialize it for specific evidence pathologies; they fire at
PROVEN-promotion time in `scripts/kunglao_record.py::claim_migrator`
(PROVEN branch) with a register-write backstop in
`hooks/worker_budget.py::compare_register_change_proven_gate`.

### Environmental negative-evidence downgrade (#56; generalizes #48)

**Incident (F040, a2b5e25c, 2026-08-11).** A `dynamic_re` BP that got 0
hits was inferred as "HandleCommand NOT on the inject path" and used to
"correct" the F034/F035 two-tier dispatch model. The provenance self-reported
an environment fault (debuggee PID 6500 WSS reconnect goroutine stalled,
never reconnected), so **all** BPs got 0 hits — not just HandleCommand; only
HandleCommand's 0-hits were singled out as "not on path" (self-contradictory
under the same fault). Static xref later proved HandleCommand IS on the path
(F049 superseded F040, PROVEN).

**Rule.** Environmental negative evidence — BP 0 hits / 无调用捕获
(no call captured) / no calls observed — under a self-reported environment
fault (`stalled` / `never reconnected` / `reconnect` / `未触发` / `timeout`):

1. **must NOT** establish a routing ("not on the inject path") OR existence
   ("does not exist" / "absent") conclusion. NEGATIVE conclusions must be
   method-justified — `scripts/failure_analysis_gate.py`'s three-question
   mechanism (method_assumption / assumption_validity / next_method —
   "failed attempt ≠ negative result") is the basis of this rule.
2. **MUST** do static xref first (Ghidra ReferenceManager / capstone
   call-site scan) before any routing/existence conclusion.
3. Routing/existence conclusions are allowed only from static evidence OR
   env-healthy dynamic evidence.

**Enforcement.** `scripts/blind_gate.py::check_inference_blind_scope`:

- `is_inferential_claim` flags routing/causal patterns (`routing`, `route`,
  `not on ... path`, `correction`, `corrects F<NN>`, `gate`, `0 hits`,
  `0 occurrences`) **and** NEGATIVE-existence conclusions (`does not exist`,
  `absent`, `not present`, 不存在, 未发现) — so existence claims reach the
  diagnostic instead of short-circuiting as non-inferential.
- the env-fault diagnostic rejects when `_has_env_negative_basis` (0 hits /
  0 occurrences / no call captured / no calls observed / 无调用捕获) **and**
  `_has_env_fault` both hold and the sign-off lacks independent static
  evidence (`xref` / `disasm` / `decompile` / `capstone` / `ghidra` / `ida` /
  `call graph` / `callsite`). Effective status: STAMP.
- Complementary to #48 ("BLIND sign-off covers inference assertions"): same
  gate function and wire points, not a duplicate gate. #56 broadens the
  trigger vocabulary (no-call-captured, not just 0-hits) and generalizes the
  forbidden conclusion from routing to routing **or** existence.

**Self-check.** "Is this NEGATIVE conclusion (not-on-path / does-not-exist)
drawn from a dynamic miss under a self-reported env fault? If yes — did I do
static xref first, or am I inferring 'absent' from a stalled debuggee?
(else `check_inference_blind_scope` downgrades PROVEN to STAMP.)"
