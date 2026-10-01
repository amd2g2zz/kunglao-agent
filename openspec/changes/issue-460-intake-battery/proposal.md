# Proposal — issue-460-intake-battery

## Why

Issue #460's predict-before-try activation is blocked on one cold fact:
instance features (probe facts) only exist AFTER the agent spends acts
learning to order the probes. The Part B prior therefore starts every
run on an empty token set — gain 1.0 for every probe category, no
borrowing, cold-start thrash intact — and the EX-5 A/B can never see
battery-fed data because no battery exists to feed it.

Owner ruling (the instrument framing): a 2-3 probe battery at intake is
a legitimate INSTRUMENT, not a behavior rule. It reads the environment
once, before the first claim dispatch; its measurable benefit is that
die/apkid features exist from run #1, feeding the feature-conditioned
prior and the mined feature table instead of waiting for learned
ordering. Instruments degrade — they never gate.

## What changes

- **New module `scripts/intake_battery.py`** — the battery face:
  runs die-probe (CLI face `tools/static/die_probe.py --binary … --out
  evidence/die.json`) and apkid-prescan (library face
  `apkid_scanner.run(ws, sample)` → `evidence/apkid.json`) over the
  ALIGNED `bins/` sample; writes the battery ledger
  `evidence/intake-battery.json` (schema `intake-battery/1`, one fact
  row per probe: ran / outcome / evidence path / reason). Never raises;
  a CLI re-run face mirrors `intake_promise.py`'s shape.
- **Wiring in `scripts/kunglao-init.py`** — the battery runs inside the
  existing `if not skip_toolchain:` block, immediately BEFORE the #813
  intake-promise block (probe, then record): the promise's
  evidence-presence fallback and `obfuscation_prior` see fresh t=0
  artifacts, so one init pass produces a coherent snapshot (capability
  facts + evidence + promise). Unexpected battery failure follows the
  promise block's pattern: WARN-tier ERROR line + `env_incident`, never
  an init failure.
- **Capability-fact honesty fold in `scripts/intake_promise.py`** —
  `_probe_evidence_present` upgrades parseable → USABLE (die: a data
  block survived per `difficulty_calibration._die_usable`; apkid:
  `status == "ok"` per `_apkid_usable`): a fail-open
  unavailable/error artifact must record the capability fact as
  missing, not available. One Part B pin updated (its fixture gains
  `status: ok`).
- **Fixture extension (the minability proof)** — the
  feature-mining-460 fixture's `e2e-ws-a` gains battery-produced
  `evidence/die.json` + `evidence/apkid.json`; the pinned golden table
  row gains die/apkid values (usable, packers, entropy_max) instead of
  absence — the miner picks battery outputs up with ZERO miner changes.

## Non-goals

- No flag: the battery is unconditional (an instrument producing
  evidence; `KUNGLAO_PREDICT_BEFORE_TRY` gates SELECTION, not evidence
  production — battery-fed data is the prerequisite for the EX-5
  re-evaluation that could flip it).
- No feature-table schema change: `probe_outputs` stays exactly
  {die, apkid}; no third probe whose output has no mined consumer.
- No dispatch/selection behavior change: the battery does not order,
  gate, or consume acts; the first-claim flow is untouched.
- No change to toolchain CHECK_SETS, #436 resource gates, or the
  toolchain apkid recommendation prose (arm-shaped, stays).
