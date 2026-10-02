---
name: anti-debug-bypass
description: Anti-debug and anti-analysis detection surfaces (ptrace, timing, integrity
  self-checks) and the minimal bypass for each detection class.
domain: anti-analysis
family: catalog
---
# Anti-debug detection + bypass

Detection surfaces and their minimal counters. When a target dies under
observation, classify the detection before patching.

## Surfaces

- ptrace self-attach checks (anti debug class): bypass via parent
  replacement or a tracer that never detaches.
- Timing-based detection: rdtsc deltas between decoy blocks; freeze the
  clock source rather than patching each check.
- Integrity self-checks: hash regions before/after instrumentation and
  restore on the fly.
