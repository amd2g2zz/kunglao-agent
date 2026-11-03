# Acceptance — the observation-surface unification (#779 face one + #769)

Scope of this document: the T1 observation PR (branch `feat/779-observation`). Every acceptance command below is machine-checkable and was run for real in the PR's Verification section.

---

## 1. What to accept (deliverable → command → expected output)

### D1. Subagent hook-semantics probe (verdict (a)) + the attribution fix

- **Artifact**: `docs/architecture/subagent-hook-probe.md` (verdict (a): Task-spawned tool calls FIRE the workspace hooks on CLI 2.1.270; the payloads carry the PARENT `session_id` with the worker identity riding `agent_id`/`agent_type`).
- **Accept**:
  ```bash
  uv run pytest tests/test_subagent_attribution_779.py::TestAgentAttribution -q
  ```
  Expected: `9 passed` — step-record/1 rows carry `agent_id`/`agent_type` only when an identity exists (no key drift on parent rows); aggregation scopes by agent; the parent bucket excludes agent-tagged rows; the round-closure settle threads the SubagentStop `agent_id`.
- **Ledger evidence** (what "accepted" looks like on a real run): `runs/experience.jsonl` gains `step-record/1` rows with `"agent_id": "<agent-id>"` for every worker tool call, and one `step-record/2` row per worker stop with `agent_id` + `tool_calls` equal to THAT agent's call count (pre-fix: `tool_calls` counted the whole session's rows, or zero when hooks did not fire).

### D2. The policy-state projection (#769)

- **Artifact**: `scripts/policy_state.py`; `runs/policy-state.json` (schema `policy-state/1`).
- **Accept**:
  ```bash
  uv run pytest tests/test_policy_state_769.py::TestPolicyStateProjection -q
  uv run python scripts/policy_state.py <workspace>     # live one-liner
  ```
  Expected: `11 passed`; the CLI prints `policy_state: <ws>/runs/policy-state.json written=True` and a `{round, claim, chosen, admitted}` summary line.
- **Ledger evidence**: after any round close that follows a dispatch, `runs/policy-state.json` exists with `schema == "policy-state/1"` and the fields `round / candidates / admitted / chosen / posterior / ts`; `runs/logs/kunglao-*.jsonl` tail carries one `action: "policy_state_projected"` row per projection write.

### D3. The statusline consumer

- **Accept**:
  ```bash
  uv run pytest "tests/test_policy_state_769.py::TestPolicyStateProjection::test_statusline_carries_the_policy_face" -q
  ```
  Expected: `1 passed` — `build_snapshot()["policy"]` is `None` without the file, and carries `{round, claim, chosen, admitted, admitted_n, candidates_n, posterior, age_s}` with it.

### D4. The policy-state-fresh liveness fingerprint

- **Accept**:
  ```bash
  uv run pytest tests/test_policy_state_769.py::TestPolicyStateFingerprint -q
  uv run python devkit/liveness_gate.py --ledger <workspace>
  ```
  Expected: `4 passed`; the gate prints `[PASS] policy-state-fresh: 1 matching row(s) of 1` on a projected workspace and `[FAIL] … ledger missing` when the file is absent (absence of evidence is the failure).

---

## 2. Where it plugs in (integration points, before → after)

| # | Integration point | Before | After |
|---|-------------------|--------|-------|
| 1 | `hooks/step_record_capture.py:64` — `process_event` → `build_step_row` | rows keyed by the PARENT `session_id` only; worker rows indistinguishable | rows carry `agent_id`/`agent_type` from the hook payload |
| 2 | `scripts/rlvr/step_grain.py:85` — `aggregate_session_steps`; `settle_step` (`agent_id` param); `step_id_for` | aggregation = whole session bucket | agent-scoped aggregation; parent bucket excludes agent rows; ids deterministic in (session, agent, ordinal) |
| 3 | `hooks/round_closure.py:239` — settle face | `settle_step(ws, session_id, outcome)` | `settle_step(ws, session_id, outcome, agent_id=…)` |
| 4 | `hooks/round_closure.py:251` — NEW kernel face | — | `policy_state.run_face(ws)` in its own fail-open cage |
| 5 | `hooks/dispatch_gate.py:967` — `_write_plan_receipt` | row = `{schema, ts, claim, admitted, chosen}` | row += `state_signature` + `candidates` (per-key `{action_kind, cost, ratio, theta, alpha, beta}`); legacy keys untouched |
| 6 | `scripts/statusline_snapshot.py:1104` (`_policy_face`) + `:1307` (`"policy"` snapshot field) | — | snapshot carries the policy display face (None = hidden) |
| 7 | `devkit/liveness_fingerprints.json:29` | 5 fingerprints | 6 (`policy-state-fresh`) |

**Call chain (who writes, who reads):**

```
dispatch ALLOW tail (hooks/dispatch_gate._write_plan_receipt)
  └─ writes runs/plan-receipts.jsonl row {admitted, chosen, candidates, state_signature}
SubagentStop → hooks/round_closure._kernel_faces
  ├─ settle_step (agent-scoped step settlement)
  └─ scripts/policy_state.run_face  ← reads runs/plan-receipts.jsonl (last row)
       └─ writes runs/policy-state.json (atomic, deduped on the receipt identity)
            ├─ READ scripts/statusline_snapshot._policy_face → snapshot["policy"] → statusline_render.mjs (dumb view)
            └─ READ devkit/liveness_gate.py --ledger → fingerprint policy-state-fresh
```

## 3. How the connection works (boundary artifacts)

- **Schema crossing the boundary**: `policy-state/1` = `{schema, round, ts, claim, receipt_ts, candidates, admitted, chosen, posterior{state_signature, actions{kind:{alpha,beta}}}, receipt_key}`; `plan-receipt/1` grew additive `candidates`/`state_signature` (consumers of `admitted`/`chosen` unaffected); `step-record/1` grew conditional `agent_id`/`agent_type`; `step-record/2` grew conditional `agent_id`.
- **Store files**: `runs/plan-receipts.jsonl` (producer), `runs/policy-state.json` (projection, single-line JSON — also parseable by the gate's jsonl reader), `runs/experience.jsonl` (consolidated step records), `runs/.kunglao-statusline.json` (display projection).
- **EMIT word**: `policy_state_projected` (registered in `scripts/event_taxonomy.py:282`, sorted+unique; one row per projection WRITE — a deduped skip writes nothing).
- **Liveness fingerprints touched**: `rl-admission-consumed` (read face unchanged; its ledger grew additive fields) + NEW `policy-state-fresh`.

## 4. Assembly acceptance (after ALL Phase 1 modules land)

Run on a synthetic campaign replay workspace (the smoke/replay tier that produces a real workspace):

```bash
uv run python devkit/liveness_gate.py --ledger <replay-ws>
```

Must print **`liveness --ledger <replay-ws>: LIVE`** — all six fingerprints green. The per-face ledger evidence that proves the assembled loop:

| Fingerprint | Evidence row that must exist |
|---|---|
| `rl-sampler-exit` | `runs/strategy-log.jsonl` `{event: "dispatch", strategy: "sampled"}` |
| `rl-admission-consumed` | `runs/plan-receipts.jsonl` row with non-empty `admitted` |
| `policy-state-fresh` (this PR) | `runs/policy-state.json` with `schema: "policy-state/1"` |
| `rl-posterior-moved` | `runs/posterior-store.jsonl` `posterior-store/1` row |
| `oracle-armed` | `oracle/cases/*.yaml` with `channel:`/`update_map`/`hypothesis_ref` |
| `settle-credit` | newest `runs/logs/kunglao-*.jsonl` containing `task_terminal_settlement` |

Phase-1-specific assembly row (beyond the gate): at least one `step-record/1` row carrying a non-empty `agent_id` in `runs/experience.jsonl` — that is the #779 Face-1 acceptance ("step-ledger rows > 0" from worker activity) in its machine-checkable form.
