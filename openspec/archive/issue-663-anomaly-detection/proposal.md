## Why

v0.1.3 milestone review surfaced a gap: human RE analysts notice "this is unusual" observations throughout investigation (e.g., "TLS to 192.0.2.1:8443 from a binary with no other network code"). The current kunglao loop has no mechanism to register these observations — `scripts/fact_contradiction_gate.py` detects **contradiction** between PROVEN facts but NOT **anomaly** (a fact unusual against a baseline or expected pattern).

Root cause: facts are evaluated in isolation (single-fact gates) and against each other (contradiction gate) but never against a baseline corpus of "what's normal for this domain". The AES example: agent sees AES, dispatches "check hardcoded key", never registers "AES + BCryptGenerateSymmetricKey + no key in plain memory = unusual, this binary likely rotates keys at runtime" (a baseline-relative observation, not a contradiction between facts).

## What Changes

- **New `scripts/anomaly_detector.py`** (pure function, mirrors `fact_contradiction_gate.py` shape): `score_fact(fact, baseline_corpus) -> float` in `[0, 1]`; `scan_anomalies(index_path, facts_dir, baseline) -> list[dict]`; `check_fact_anomaly(fact_id, facts_dir, baseline) -> (allowed, reason)`; CLI.
- **`scripts/lint_facts.py`**: Add `"anomaly"` to `VALID_BOUNDARY_TYPE` (parallels `contradiction`, sits in `EMPTY_GATE_TYPES`). Bump `ACTIVE_SCHEMA_REV` 1 → 2 (additive, backward-compatible).
- **`scripts/convergence_check.py`**: New DRAIN event `ANOMALY_DETECTED` between `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN` (per #443 state machine, additive). New action builder + event predicate + STAGE_PROBES + TRANSITIONS rows.
- **Baseline corpus sourcing** (`references/re-library/patterns.md` + new `references/anomaly-baseline.md`): RE-library pattern docs + prior completed samples from `~/.kunglao/samples/` (when present) + operator-provided patterns via `analysis_state.txt` `baseline_corpus: <path>`.
- **Optional** (separate decision, not blocking this change): feed high-anomaly facts into `hypothesis_store.py` as candidate competitors (links #662 hypothesis seed work).

## Capabilities

### New Capabilities

- `anomaly-detection-gate`: each PROVEN fact gets an anomaly score in `[0, 1]` against a baseline corpus (RE-library refs + prior samples + operator config). Score above `ANOMALY_THRESHOLD` (configurable, default 0.7) auto-promotes to a note with `boundary_type: anomaly`. Surfaced in `convergence_check` DRAIN stage as `ANOMALY_DETECTED`. Threshold lives in `analysis_state.txt` (`anomaly_threshold: 0.7`) so operators can tune per-engagement.

### Modified Capabilities

- `fact-frontmatter-schema`: `boundary_type` enum gains `"anomaly"`; `ACTIVE_SCHEMA_REV` 1 → 2 (additive — existing facts are untouched; `lint_fact` allows the new value with empty `promotion_gate` per `EMPTY_GATE_TYPES`).
- `convergence-decision-machine`: DRAIN stage events gain `ANOMALY_DETECTED` between `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN` (per #443 explicit state machine, additive only — no state removed, no precedence changed).

## Impact

- **New files**:
  - `scripts/anomaly_detector.py` (~120 lines, pure function, no I/O at module import): `score_fact`, `scan_anomalies`, `check_fact_anomaly`, CLI with `--json`.
  - `tests/test_anomaly_detector.py` (~250 lines): RED1-RED6 + boundary edges + integration with `claim_migrator` + integration with `convergence_check` DRAIN.
  - `references/anomaly-baseline.md`: baseline corpus sourcing rules + ANOMALY_THRESHOLD config docs.
- **Modified files**:
  - `scripts/lint_facts.py` (~5 lines): add `"anomaly"` to `VALID_BOUNDARY_TYPE`; bump `ACTIVE_SCHEMA_REV = 2`.
  - `scripts/convergence_check.py` (~30 lines): new `Event.ANOMALY_DETECTED` enum value, new `_act_anomaly` action builder, new `_anomaly_detected` predicate, `STAGE_PROBES[State.DRAIN]` insertion at index between `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN`, `TRANSITIONS[(State.DRAIN, Event.ANOMALY_DETECTED)] = (State.BLOCKED, _act_anomaly)`.
  - `references/_INDEX.yaml`: add `anomaly-baseline.md` to the references list.
  - `CHANGELOG.md`: noted under v0.1.4.
- **Backward compatibility**: existing facts (boundary_type in the prior set) untouched; `DRAIN_ANOMALY_DETECTED` only fires when `scan_anomalies` produces results; missing baseline corpus returns `[]` (fail-open with one `kunglao_log` warning, never blocks cold-start).
- **Maker-checker interaction**: anomalies are detected against baseline, not against verifier judgment — `verifier_sign_off` is unchanged; an anomaly is a reader-facing observation, not a verdict demotion. No `claim_migrator` change required (no `STAMP` downgrade for anomalies; the existing PROVEN status stays; the anomaly just becomes a co-resident note).
- **Related**: #358 (P4 v0.2 batch — re-library gap-fill may overlap with baseline corpus seeding; coordinate before merge); #634 (loop cost burn — different layer, complementary); #662 (hypothesis seed — optional follow-up links anomalies to hypothesis competitor groups).
