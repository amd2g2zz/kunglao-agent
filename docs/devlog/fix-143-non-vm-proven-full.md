# #143: Non-VM PROVEN-FULL Alternative Path

## Problem
PROVEN-INITIAL → PROVEN-FULL requires ≥2 independent tiers or ≥5min multi-VM
detonation. For static-only samples (scripts, config files, non-executable
artifacts), these conditions are permanently unmeetable → never converges.

## Design: Capability-Aware Convergence

### Capability Declaration (task_spec.yaml)
```yaml
capabilities:
  vm: false          # no VM available
  emulation: false   # no Qiling/unicorn
  static: true       # Ghidra + tools available
  frida: false       # no Frida
```

### Tiered Convergence Conditions

| Capability | PROVEN-FULL Condition |
|---|---|
| VM available | ≥2 independent tiers (current rule) |
| Emulation only (no VM) | ≥2 independent static methods + ≥1 emulation cross-check |
| Static only | ≥2 independent static methods (Ghidra + capstone/radare/pefile) cross-verified |
| Config/script sample | Single thorough static analysis + reviewer sign-off |

### Implementation Scope
1. `convergence_check.py`: read capabilities from task_spec, select rule set
2. `claim-register.yaml`: add `verification_method` field per claim
3. `kunglao-decide.py`: factor capabilities into DISPATCH_VERIFIER decision
4. Tests: each capability combination produces correct convergence rule

### Decision
Design approved; implementation deferred to sub-issue when first non-VM
sample is analyzed. Static-only path is the immediate priority.
