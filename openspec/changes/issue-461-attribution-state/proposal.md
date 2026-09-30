# Proposal — issue-461-attribution-state (Phase 1)

## Why

Issue 461 (owner ruling 2026-09-30): premature "cannot analyze"
conclusions are a failure of attribution, not honesty — a human
attributes failure causes and finds the breakthrough. But the fix is
NOT a gate/rule patch (the owner explicitly rejected verdict-face
enforcement — rules do not generalize). Attribution must enter the
system as STATE. Today a failed act leaves behind prose (the
`## failure` block) and nothing the kernel can discriminate on:
without causes in state, all dead-ends look identical and neither
termination nor prediction can tell "dead forever" from "wrong so
far".

Research grounding (the issue's own citations):
- REFLECT (arXiv 2606.09071): intervention-supported attribution
  beats Reflexion-style verbal reflection on silent failures — an
  attribution is a controlled experiment, not prose.
- Option-Critic (2017): "when to quit" is a learned termination
  function INSIDE the option, not a sibling arm.
- ICML 2025 agent-failure attribution: responsible-component +
  decisive-step structure.

Phase 1 is the state half: the obstacle object, its capture into the
state signature, the worker intervention protocol that produces it,
and the synthetic trap-trajectory data Phase 2 will train on.

## What changes

1. **Obstacle object schema `obstacle/1`** (new module
   `scripts/rlvr/obstacles.py`): structured files
   `runs/obstacles/OBS-<n>.json` carrying
   {kind, cause, evidence_path, method_family, ts} (+ id, schema, and
   optional join keys claim / dispatch_id). `kind` is a closed enum
   (missing_env_entry | detection_trigger | encryption_layer |
   tool_limit | other); `cause` is a single machine-checkable line
   (<= 200 chars); `evidence_path` cites an intervention experiment
   artifact that must EXIST at record time and carry a probe-execution
   marker (the blocker-schema-v2 differential-probe discipline,
   extended from blockers to act failures). The registry lives under
   runs/ beside the q-cell log / posterior store — NOT under
   evidence/: the evidence-index pipeline sweeps evidence/ as raw
   evidence and an obstacle row is a derivation from its probe
   artifact, so an evidence/ placement would invert the raw/derived
   hierarchy (design-review CRITICAL fix; the issue's
   "evidence/obstacles/" was an e.g., the placement is the reviewer-
   corrected deviation). Obstacle rows are NOT obstacle claims
   (origin failure-obstacle) and license no death declaration.
2. **Observe-face capture**: `scripts/rlvr/state.py` (the state
   signature face) reads the obstacle registry and (a) exposes an
   obstacle digest {present, count, kinds} in the canonical snapshot,
   (b) adds an `ob=<sorted kind-count pattern>` segment to the
   canonical signature string (`-` when none) so cause-bearing failure
   states are discriminable keys. The signature schema tag advances to
   state-sig/2 (eight-segment form; the ob= segment inserts before the
   reserved sides tail so sides never re-keys). The V(s) anchor is
   UNTOUCHED — attribution is evidence, not progress. The format
   change re-keys all signatures (safe: the kernel is runtime-inert
   pre-462); the two byte pins in tests/test_state_signature_396.py
   are re-pinned in the same change.
3. **Worker intervention protocol**: agents/kunglao-worker.md gains
   the failure-time protocol — when an act fails, run an isolation
   probe that discriminates the suspected cause, save the probe
   artifact under runs/probes/, record the obstacle row via the helper
   CLI, and cite the OBS id in the `## failure` block. Evidence-first:
   the artifact is an experiment result, not narration. One probe
   artifact may serve both the obstacle row and a blocker's
   probe_evidence when the same experiment backs an ESCALATE.
4. **Synthetic fixtures + trap experiment**: three canonical failure
   signatures (missing env entry / anti-analysis trigger / encrypted
   layer) as unit-test substrate with expected obstacle rows; and
   EX-4 `experiments/ex4_attribution_trap.py` — the declared-synthetic
   five-step trap trajectory replay over REGISTERED family tokens
   (dynamic-trace → replay-harness-verification → static-decompile →
   obfuscation-peeling → crypto-core-identification breakthrough;
   frida-detected → unidbg-env-error → static-tool-limit → encrypted
   layer → breakthrough), producing one obstacle row per failing step
   — the Phase-2 termination estimator's training shape (the
   launcher's "E2 data production" experiment; the repo sequence
   EX-2/EX-3 is taken, so this is EX-4).

## Non-goals (Phase boundary)

- NO Bayesian option-death termination, NO q_cells changes, NO
  kernel wiring — that is Phase 2 and the concurrent 462 change
  (kernel-actuation) owns the runtime surfaces. Nothing here touches
  scripts/rlvr/q_cells.py, compose.py, or hooks.
- NO gates: no verdict-face gate, no mandatory-ledger check, nothing
  rejects a cause-free failure. Obstacle production is protocol
  guidance + a helper; consumption is a pure read into state. Behavior
  change (termination) emerges in Phase 2 from state + posteriors.
- No V(s) change and no new decision input: Phase 1 is recording-only
  (the 396 freeze posture — no dispatch/gate/settlement face imports
  the obstacle module, pinned by extending the freeze test with
  full-module-string checks).
- No evidence/_index.json coupling: obstacle rows are kernel telemetry
  under runs/, never indexed as raw evidence; fact citation of probe
  artifacts is a follow-up only if a face needs it.
