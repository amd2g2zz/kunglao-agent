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
> contracts, and audit gates that seed does not name.

## The diagnose-driven stub loop

Do not stub from intuition. Run a mechanical loop where each iteration is
driven by observed missing-environment evidence:

1. **First diagnosis runs with ZERO stubs.** Execute the target in the
   sandbox and collect the undefined-path list (every global/property access
   that failed). This list, not a guess, is the work plan.
2. **Map paths to stub modules by prefix**, pull in declared dependencies,
   and order them by the loading contract (below).
3. **Re-diagnose with stubs loaded.** Compare: the undefined list shrinking =
   correct selection; new errors = loading-order or inter-module dependency
   problem; unchanged = the value needs real capture, not another stub.
4. **Residue handling:** covered by a module but still failing → order
   problem; not covered by any module → write a minimal new stub (define the
   property with a plausible default, keep it isolated and labeled); needs a
   real browser value → capture it from a real environment, never invent it.
5. **Stop conditions (avoid spinning):** load succeeds with no meaningful
   undefined paths left, OR two consecutive iterations produce the identical
   undefined list (dead loop — change approach, do not re-run), OR the
   residue is all instrumentation-internal symbols.
6. **Load-success is not usability.** The diagnostic verdict only means the
   script loads without throwing. The recovered capability (signature,
   encryption) needs its own functional verification — trigger the real code
   path and check the output shape — before any claim (see
   external-delivery-verification-gates.md).

## Loading-order contract

Stub initialization order is load-bearing; violations produce wrong-state
environments that fail far from the cause:

- Environment stubs load BEFORE the target script (the target reads the
  environment at load time, not lazily).
- Dependency order inside the stub set: low-level browser objects first;
  container objects before the elements they contain; network API stubs
  before higher-level network wrappers that reference them.
- **Capture/instrumentation hooks go in the MIDDLE**: fake globals before the
  target (the target must hook THEM), but value-capture hooks AFTER the
  target — targets may carry polyfills that overwrite any hook installed
  earlier, silently. The canonical chain: env stubs → fake globals → target
  script → capture hooks → initialization call → trigger.
- Initialization parameters are part of the environment. Independently-loaded
  SDK-style scripts commonly gate their signing behavior on init/config
  parameters captured at runtime; loading without them produces the
  **silent-skip failure mode**: everything loads, hooks fire, but the signed
  value is never produced and no error surfaces. When a hook-type SDK loads
  but never signs, capture the init parameters from a live page before
  touching any stub.

## Trace-first coverage planning

When a runtime trace of the target exists, plan the stub set from it BEFORE
writing the first stub: build the API-consumption inventory (every browser
API the trace shows being touched), mark each item implemented / sampling
/ deliberately-not-mounted, and implement the high-priority items in the
first round. A trace item that later surfaces as a failure is a process
defect (missed-from-trace), not bad luck — record it as such. Complexity of
the trace sets risk and priority only; it does not choose the runtime.

## Machine-audited fidelity

"Fills the values in" is the floor, not the bar. Three audit disciplines
separate a stub that runs from a stub that survives detection:

- **Runtime-contract audit (no-send mode).** Run the final entry with network
  sends disabled and diff the sandbox against a real-browser baseline:
  receiver identity, property descriptors, getter/setter presence,
  prototype chains, own-key sets, constructor behavior, and result/exception
  equality per touched API. The comparison must be machine-produced —
  hand-written "matched" status is not observation — and a field missing on
  BOTH sides is a mismatch too (absence of evidence on both sides hides a
  broken probe). Re-audit after every environment change.
- **Native-first object shape.** Detection reads object SHAPE, not just
  values: `toString` brand, `typeof`-class behavior, illegal-receiver
  throws, `instanceof` and cross-realm identity. Plain objects and simple
  functions fail these. Isolate internal state off the visible object
  (no underscore-prefixed or symbol own-properties leaking internals;
  module-scoped weak maps are the pattern). Host runtime leakage is part of
  shape: quarantine the host's own globals (process, module system, host
  timers, host network) before the target runs — a leaked host global is a
  detection point that no value-level stub can fix.
- **Fingerprint value provenance.** Every replayed fingerprint value carries
  its origin: captured from a real browser under the SAME baseline identity
  as everything else in the case (one profile/seed/locale/timezone/UA
  identity for all evidence and audits — record the baseline id and switch
  it only deliberately). Watch for capture-side truncation of long values
  (length near the capture buffer cap is a tell); record full length and a
  hash of each value. Guessed, random, default, or synthesized values are
  not replay material — absent real capture, mark the API unmounted and
  record the gap instead of fabricating.

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
