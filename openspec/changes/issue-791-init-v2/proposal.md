# issue-791-init-v2 — lane-pruned yaml surfaces + bounded-intelligent intake

## Why

Task-shaped init was mechanical: a lane:web workspace (51job live
evidence, logs panel 2026-10-23) initialized with apkid/die prescan
entries it can never produce, a java_reachability face that is
meaningless for web material, a dead all-zero "easy" difficulty under
the binary factor map, and no machine-anchored capability state behind
the "device has no root" narration (host-missing frida got narrated as
device-unrooted; dynamic-trace was dispatched 9x on a known-DOWN
capability). The lane-blind composition of #669 (flat prescan), #15
(fixed difficulty families) and #412 (structural-only seeds) is the root
cause; each ruling was right locally.

## What Changes

1. **NEW `scripts/lane_profile.py`** — the lane DATA PROFILE registry
   (panel architecture-seat amendment): per lane, the prescan probe
   battery, the binary-only faces (java_reachability /
   obfuscation_prior), the obligation artifacts, the difficulty factor
   set and the capability vocabulary (device_root FIRST-CLASS).
   Unknown lane fails open to the pre-#791 binary yaml with a LOUD
   WARN — never a guessed new shape.
2. **`intake_promise` consumes the registry** — out-of-lane probes are
   DROPPED at init (never emitted as WARN stubs): lane:web gets ZERO
   apkid/die entries, no java_reachability, no obfuscation_prior; the
   promise carries the resolved lane; lane:malware keeps today's
   battery byte-for-byte.
3. **`difficulty_calibration` gains factor sets** — `factor_set` joins
   the output schema (difficulty-calibration/1 keeps its fields); web
   names captcha_anti_bot / auth_session / pagination_integrity /
   rate_limit; a non-binary lane whose extractors report nothing (or
   has no validated weight table) calibrates UNKNOWN — never easy
   (panel amendment 2, the honest-null inversion). Unknown lane ->
   today's binary map.
4. **R2 capability axis** — `device_root` joins env_state_probe's
   ANDROID_CAPS (probe mirrors the init-time toolchain check: adb shell
   su -c id; skip when adb/device absent — never fabricated). NEW
   dispatch-gate face `_lane_capability_gate`: a dispatch whose
   DECLARED tools mechanically require a capability the near-time
   env-state records DOWN is REJECTED (evidence class) with the
   component + the #634 wake condition; skip/absent/stale/unreadable
   state = no opinion. Representation (#791) vs execution (#812)
   division respected: this face only READS runs/env-state.json.
5. **NEW `scripts/intake_draft.py`** — the bounded-intelligent intake
   draft (§3): init scaffolds runs/intake-draft.yaml (schema
   intake-draft/1) carrying the classification consequence echo and
   empty distillation lists; the dialogue drafts deliverables /
   acceptance / not_done / diff_vs_verbatim + primary_questions
   (FIRST-CLASS, addendum 1) and the user confirms; confirm() is the
   ONE declared_ts stamping path (goal-operationalization scaffolds
   UNSTAMPED now — the existing R4/convergence-INVALID gate makes the
   dialogue un-skippable). R2 rubber-stamp refusal, R1 non-empty
   not_done, R6 witness passthrough, R5 untouched (constitution
   discipline unchanged; stamped goal-ops are never rewritten).
   #412 stays: the machine validates and echoes, it never invents
   analysis.

## Capabilities

### lane-profiles-791
- registry-driven promise pruning + difficulty factor sets + capability
  vocabulary + the dispatch env floor.

### intake-draft-791
- the confirm-before-declared_ts intake draft face.

## Coordination

- #794 `_supply_admission` / #800 claims_store: untouched; the
  capability gate runs alongside them in the dispatch teeth chain and
  rides the same unified-log trace face; env-state.json stays the ONE
  capability-state surface both can read.
- #812 (in flight): owns probe EXECUTION; this card owns capability
  REPRESENTATION (vocabulary + state consumers). Additive both ways.
- Out of scope (stays open on #791): the router face (addendum 2/3 —
  route_capability abstention contract) — separate face, not assigned
  to this dispatch.

## Impact

- Behavior change (intended): init-scaffolded goal-operationalization
  ships declared_ts: "" — convergence INVALID until the intake draft is
  confirmed. Pre-#791 stamped workspaces are untouched (additive).
