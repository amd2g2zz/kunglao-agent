# EX-4 — attribution trap trajectory replay (issue 461 Phase 1)

**DECLARED SYNTHETIC** (the issue's owner-authored five-step trap
scenario, replayed through the REAL obstacle record + state signature
faces on a throwaway workspace; no campaign data). This is the
launcher plan's "E2 data-production" experiment — the repo experiment
sequence EX-2 (gamma calibration) / EX-3 (bucket calibration) is
taken, so it ships as EX-4.

Reproduce: `uv run --project . python experiments/ex4_attribution_trap.py`
(raw numbers: `experiments/ex4-results.json`, same commit).

Purpose: produce the training shape the Phase-2 Bayesian option-death
termination estimator will consume — cause-bearing failure states:
one obstacle row per failing step, over REGISTERED method-family tokens
(the production Q-key vocabulary, `scripts/method_families.yaml`),
plus the per-step signature evolution.

## The trajectory (issue 461)

| step | act (family — registered) | outcome | obstacle kind |
|---|---|---|---|
| 1 | dynamic-trace (frida attach) | failure | detection_trigger |
| 2 | replay-harness-verification (unidbg) | failure | missing_env_entry |
| 3 | static-decompile (jadx) | failure | tool_limit |
| 4 | obfuscation-peeling (config read) | failure | encryption_layer |
| 5 | crypto-core-identification (decryptor) | **success** | — (breakthrough) |

Each failing step writes a synthetic probe artifact (command + rc +
verbatim output — the shape the record face validates) and records
one obstacle row citing it; the breakthrough records nothing and lands
one synthetic fact (the evidence the whole chase was for — the state
moves by evidence, not by attribution).

## Expected obstacle sequence (the Phase-2 training shape)

```
OBS-001  detection_trigger        dynamic-trace
OBS-002  missing_env_entry        replay-harness-verification
OBS-003  tool_limit               static-decompile
OBS-004  encryption_layer         obfuscation-peeling
```

Signature evolution (ob= segment, from the results JSON):

```
step1  ob=detection_trigger=1
step2  ob=detection_trigger=1|missing_env_entry=1
step3  ob=detection_trigger=1|missing_env_entry=1|tool_limit=1
step4  ob=detection_trigger=1|encryption_layer=1|missing_env_entry=1|tool_limit=1
step5  (unchanged — the inventory freezes at the breakthrough)
```

Every failing step advances the cause-bearing state (different kinds
produce different signatures — the discriminability Phase 2 needs to
separate "dead forever" from "wrong so far"); the breakthrough step
changes the signature only through its landed fact (fc bucket moves),
never through attribution.

## Determinism

Fixed ts per step, sorted iteration, no clock reads; the determinism
pin lives in `tests/test_ex4_attribution_trap_461.py` (byte-identical
result document across replays, machine-local workspace path stripped
from the shipped JSON).

## Phase boundary

This experiment produces DATA, not behavior: no termination
estimator, no q_cells fold, no kernel wiring here. Phase 2 (issue 461
Phase 2, after the 462 kernel-actuation wiring) trains the option-death
posterior on this shape; the breakthrough at step 5 is the label that
keeps the trap a trap — a decay-only policy abandons the chain, the
attribution-bearing policy reads the four obstacles as the priced
detour it actually was.
