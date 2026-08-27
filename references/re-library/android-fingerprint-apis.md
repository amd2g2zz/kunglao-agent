# Android Fingerprint APIs — taint seed reference (#692 WP5)

> Capability doc for the `android:data-flow` provider chain: the seed table
> (`android-fingerprint-seeds.yaml`, same directory) drives
> `tools/static/dexdc_scanner.py --mode taint` (upstream `--taint-api`
> seeds + `--taint-solve`). Read this when a claim asks whether the sample
> COLLECTS fingerprint-grade identifiers and where they FLOW (source ->
> sink chains, `evidence/dexdc_taint.json`).

## What this table is

- **Data, not code**: entries are consumed by the dexdc wrapper as taint
  seeds; extending detection = add an entry (yara-rules lifecycle — no code
  change, no re-register).
- **Categories** map findings to hypothesis-candidate labels
  (`taint:<category>:<api>` via `hypothesis_seeder.seed_taint_candidates`)
  and to the anomaly concentration score
  (`anomaly_detector.observe_taint` — distinct high-risk families).
- **Risk tiers**: `high` = directly identifying (IMEI/SIM/serial-class:
  getDeviceId, getSubscriberId, getSimSerialNumber, MAC, clipboard);
  `mid` = correlating/behavioral (SSID, sensors, advertising id,
  SIM operator).

## The two competing explanations this table feeds (#662)

A taint finding is evidence FOR both:
1. **Risk-control collection** — legitimate SDK/device-fingerprint
   behavior (anti-fraud, push attribution);
2. **Malicious tracking** — spyware-grade identifier harvesting.

The seeder appends the finding as a COMPETITOR CANDIDATE on the
pq-family scaffold — adjudication stays the analyst's job (refute via
refuting_fact_id / supersede per #528). The anomaly note
(`notes/taint-observation.md`) is an OBSERVATION, never a verdict
demotion (#663 D8 posture).

## api shape

Bare method names — the upstream `--taint-api` argument shape
(`dex-decompile ... --taint-solve --taint-api getLastLocation`,
per the androguard/dex-decompiler README). Overloaded names resolve
upstream by method context.
