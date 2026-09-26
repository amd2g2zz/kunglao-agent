---
name: external-env-stub-generation
description: 'Environment-stub generation for running obfuscated web JS in a sandbox (external-distilled,
  S1/S2/S3): diagnose-driven undefined-path loop with stop conditions, stub loading-order and injection-order
  contracts, trace-first API coverage planning, machine-audited environment fidelity (no-send runtime contract,
  native-first object shape, host-leakage quarantine), fingerprint value provenance. When recovering a signer
  that must run outside the browser and stubbing the environment is the chosen path.'
domain: web
family: external-distilled
source_id: S1,S2,S3
source_license: none,MIT,none
retrieved: 2026-09-23
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(web-re-quickref Path B)
---

# Environment-stub generation (external-distilled)

> External-derived methodology (never directly PROVEN; same epistemic class as
> WebSearch results). Generalized paraphrase of three independent external
> sources; provenance is the S-id list above, nothing more. The seed concept —
> replicate the browser environment in a sandbox and diff detection points —
> is web-re-quickref Path B; this card lands the loop mechanics, ordering
> contracts, and audit gates that seed does not name. Advisory: the loop is
> methodology, not proof — load-success is not usability, the functional
> verification gate owns that verdict.

## The diagnose-driven stub loop

One question first: *what environment read does the target actually make?*
The loop is driven by observed missing-environment evidence, never by
intuition.

```text
// round 1: diagnose with ZERO stubs — the undefined list IS the work plan
node diagnose.js target.js                    -> success, error, undefinedPaths[]
// map each path to a stub module by PREFIX + declared dependencies
undefinedPaths -> prefix match -> modules (ordered per the contract below)
// re-diagnose and branch on the delta:
undefinedPaths shrinks  -> selection correct, continue
new errors appear       -> loading-order or inter-module dependency problem
list unchanged          -> value needs REAL capture, not another stub
// residue routing:
in a module but failing -> order problem
in no module            -> minimal isolated labeled stub (plausible default)
needs live value        -> capture from real env; NEVER invent
```

Verdict algebra for the stop decision:
`stop ⇔ load-ok ∧ residue-meaningless ∨ two-identical-rounds ∨ residue-all-internal`.
The identical-rounds clause is the anti-spin ratchet: change approach, do not
re-run. `success:true` means the script LOADED; the recovered capability
(signing, encryption) needs its own functional verification before any claim
(external-delivery-verification-gates.md owns that verdict).

## Loading-order contract

Order is load-bearing; violations produce wrong-state environments that fail
far from the cause. Injection protocol, in order:

1. **Environment stubs first** — the target reads the environment at load
   time, not lazily.
2. **Fake globals before the target** — the target must hook THEM.
3. **Capture hooks after the target** — targets carry polyfills that
   overwrite any hook installed earlier, silently.
4. **Init call after target load, before trigger** — params captured from a
   live page (`set_breakpoint_on_text("SDK.init(")`-class anchor).
5. **Trigger last** — standard open/setRequestHeader/send flow.

Inside the stub set: low-level browser objects first; container objects
before the elements they contain; network API stubs before higher-level
wrappers that reference them.

**Init parameters are part of the environment.** Silent-skip failure mode:
SDK-style scripts gate signing on init/config params — without them
everything loads, hooks fire, the signed value never appears, no error
surfaces. Hook-type SDK loads but never signs → capture init params from a
live page before touching any stub.

## Trace-first coverage planning

When a runtime trace of the target exists, plan the stub set from it BEFORE
writing the first stub:

| Step | Action | Evidence produced |
|---|---|---|
| inventory | every browser API the trace shows being touched | `trace-api-inventory` |
| triage | mark each: implemented / sampling / deliberately-not-mounted | coverage matrix |
| round one | implement P0/P1 before the first env write | first-pass stub set |
| defect rule | a trace item failing later = missed-from-trace, recorded as a process defect | coverage ledger |

Trace complexity sets risk and priority only; it never chooses the runtime.

## Machine-audited fidelity

"Values filled in" is the floor. Three audits separate a stub that runs from
a stub that survives detection:

| Audit | What it checks | Rules |
|---|---|---|
| runtime-contract (no-send) | receiver identity, descriptors, getter/setter, prototypes, own-keys, constructor behavior, result/exception equality vs a real-browser baseline | machine-produced comparison only (hand-written "matched" is not observation); field missing on BOTH sides = mismatch too; re-audit after every env change |
| native-first object shape | `toString` brand, typeof-class, illegal-receiver throws, `instanceof`, cross-realm identity | plain objects/functions fail; internal state OFF the visible object (no `_x`/`__x`/symbol own-props; module-scoped WeakMap pattern); quarantine HOST globals (process, module system, host timers, host network) before target runs |
| fingerprint value provenance | origin capture under the SAME baseline identity (one profile/seed/locale/timezone/UA id for all evidence; record baseline id) | length near capture-buffer cap = truncation tell; record full length + hash; guessed/random/default/synthesized values are NOT replay material — unmounted-and-recorded beats fabricated |

Why host-leakage is a shape concern, not a values concern: a leaked host
global is a detection point no value-level stub can fix, because detection
reads object SHAPE and identity, not just values.

## Path-selection note

Stubbing is one of three routes, not the default: run the code in a real
browser behind a bridge, stub the environment in a sandbox, or recover the
pure algorithm. Choose stubbing when the algorithm is welded to environment
reads that a sandbox can satisfy cheaply; prefer the minimal runnable subset
(full-window fidelity is a cost trap); when the target collapses to a pure
function, STOP expanding the stub set — the task has become an algorithm-
recovery task (external-algorithm-recovery-chains.md).

Companions: [web-re-quickref.md](../labs/web-re-quickref.md) (Path B seed),
[web-risk-control.md](../risk-control/web-risk-control.md) (detection-point
attribution loop).

## Tool section — the mechanical diagnose loop (registered CLI)

The loop above is mechanical end to end; `tools/web/js_env_diagnose.py`
(tag `js:env-diagnose`, registered in `tools/_INDEX.yaml`) runs it as a CLI.
Reach for it when: the bundle must execute outside the browser and the
missing-env list is unknown — the miss list replaces the eyeball pass
as step 1 of the planning order.

```bash
# first diagnosis: bare Node-VM sandbox, zero browser env — the miss list
# IS the patch list
python tools/web/js_env_diagnose.py --target bundle.js

# verify a stub suppresses its miss before writing it into the workspace
python tools/web/js_env_diagnose.py --target bundle.js --prelude stub_navigator.js
```

Read the `undefined_paths` from the JSON verdict as the module-selection
step, one sandbox iteration per patch round; `success:true` with the
target still misbehaving in the browser means the residue is
fingerprinting, not environment (switch lanes — do not keep patching).
