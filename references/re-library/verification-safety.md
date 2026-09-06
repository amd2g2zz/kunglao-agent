---
name: verification-safety
description: Safety and evidence discipline around the verification loop — the safe-to-invoke gate that decides whether a differential-verification harness may call a candidate function at all, the minimal-patch discipline that keeps every bypass a probe license rather than a modification license, and the evidence-type vocabulary that bounds what each evidence class may and may not update in the claim and hypothesis layers. Use before auto-invoking candidate functions against captured samples, before applying any bypass patch, and when typing a new evidence item to decide which state transition it justifies.
---

# Verification Safety (invocation gate + patch discipline + evidence vocabulary)

Three disciplines wrap the verify loop:

- **A — safe-to-invoke gate**: may the harness call this candidate at all?
- **B — minimal patch discipline**: a bypass is probe license, not modification license.
- **C — evidence-type vocabulary**: what each evidence class is allowed to move.

## When to Use

- A differential harness is about to auto-invoke candidates against captured samples.
- A bypass patch is about to be applied to make a flow observable.
- A new evidence item needs a home: which claim/hypothesis state may it
  advance?

## A — safe-to-invoke gate

Blindly invoking a candidate can fire real requests, force a logout, or
mutate server-visible state — a false verification AND a footprint. Gate
every harness invocation.

**Decision inputs (function purity cues):**

- no reachable network entry points from the candidate;
- no storage writes (prefs, databases, files);
- idempotency/determinism markers: a pure transform over its arguments,
  no clock or nonce consumption.

**Rules:**

- Gate says NO → **skip-with-reason**: record the refusal in the harness output. A
  silent skip corrupts the promotion statistic — untested reads as untestable.
- Promotion to `verified` requires **≥ 2 matches**: the same candidate
  reproducing the captured output on at least two distinct samples. One
  matching sample is a candidate, not a verdict.

### Few-shot — safe-to-invoke decision skeleton (synthetic)

```python
def safe_to_invoke(fn_symbol, callgraph) -> tuple[bool, str]:
    reasons = []
    if reaches(fn_symbol, NETWORK_SINKS, callgraph):   # connect/send-class
        reasons.append("reaches network sink")
    if reaches(fn_symbol, STORAGE_SINKS, callgraph):   # prefs/db/file writes
        reasons.append("performs storage write")
    if consumes_dynamic_input(fn_symbol):              # clock/nonce/PRNG seed
        reasons.append("consumes time or nonce input")
    if reasons:
        return False, "; ".join(reasons)   # skip-with-reason, never silent
    return True, "pure over arguments"

# harness loop:
for sample in captured_pairs:
    ok, why = safe_to_invoke(candidate, callgraph)
    if not ok:
        log_skip(candidate, why)           # the refusal is itself evidence
        continue
    matches += (replay(candidate, sample.inputs) == sample.output)
promote = matches >= 2                     # one match is not a verdict
```

## B — minimal patch discipline (bypass = probe license)

A bypass exists to make one phenomenon observable. It is never a
modification to ship.

**Loop:**

1. **Record the unpatched phenomenon first** — rejected request, silent
   hook, crash: the "before" is half of every comparison.
2. **Apply exactly one minimal patch** — one check neutralized, one flag
   flipped, one stub returning a fixed value.
3. **Compare before/after** on three questions: does the request now
   complete? does the hook now emit? is the call stack now visible?
4. **Accept** only if the patch (a) produced new evidence and (b) its
   impact surface is explainable in one sentence.
5. **Quarantine it.** A bypass patch NEVER leaks into the final
   deliverable — the deliverable documents the phenomenon; it does not
   carry the probe.

**Forbidden:** stacking multiple unverified bypasses — the first failure becomes
unattributable; widening a fake environment (broad stubbing, spoofed global
state) to raise the odds the flow "seems to run" — that manufactures comfort,
not evidence.

### Few-shot — single-patch verification loop (bash, synthetic)

```bash
# 1. record the BEFORE state (unpatched phenomenon)
frida-trace -p $(pidof com.target.app) -i "*ptrace" 2> before.log
# hook silent, login rejected -> evidence/e-before.json

# 2. ONE minimal patch: neutralize a single anti-debug check
frida -p $(pidof com.target.app) -l patch_ptrace_check.js   # ~6 lines

# 3. re-run the SAME probe; compare on the three questions
frida-trace -p $(pidof com.target.app) -i "*ptrace" 2> after.log
diff before.log after.log        # request completes? hook emits? stack visible?

# 4. acceptance: new evidence + one-sentence impact + quarantine
cp after.log evidence/e-after.json && mv patch_ptrace_check.js probes/
# 5. the patch path is recorded as probe metadata — never shipped
```

## Evidence-type vocabulary

The categorical update channel consumes exactly this vocabulary: each
evidence item is TYPED AT WRITE TIME, and the type bounds what the item
may move. Any type can be recorded; the table bounds what it can conclude.

| Type | One-line definition | May update | May NOT update |
|---|---|---|---|
| `name-keyword` | Identifier/class/method name matches a known pattern | Raise the candidate's prior; open a hypothesis | Never verdicts — names lie and obfuscation renames |
| `source-keyword` | Readable source or strings adjacent to the artifact | Raise prior; narrow the family | Never verdicts |
| `runtime-stack` | Live call stack observed passing through the artifact | Support entry-point hypotheses | Never algorithm identity on its own |
| `network-correlation` | Hook I/O correlates with a live field across samples | Strong support for entry/format hypotheses | Not `verified` without direct reproduction |
| `io-fingerprint` | Isolated invocation output equals captured I/O | Candidate → strong; one match is not a verdict | `verified` needs ≥ 2 matches (gate A) |
| `export-path` | Artifact reachable via export/deeplink/route enumeration | Capability claims only | Not identity, not capability-abuse conclusions |
| `cross-source-agreement` | Two independent sources agree | Raise the confidence band | Still not `verified` — shared-origin risk |
| `direct-verification` | Harness replay reproduces captured output byte-identically | The ONLY type that may judge `verified` | May not promote beyond its sample set |

A mis-typed item is a finding about the pipeline, not a free upgrade — re-type it, never re-grade it.

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Invocation allowed | Gate pass with reasons, or skip-with-reason recorded |
| Candidate promoted | ≥ 2 io-fingerprint matches on distinct samples |
| Patch accepted | New evidence + one-sentence impact + quarantined probe |
| Evidence recorded | Typed against this vocabulary at write time |

## Cross-references

- Falsifier supply per hypothesis family:
  [falsifier-library.md](falsifier-library.md)
- The replay gate `direct-verification` points at:
  [native-sign-recovery.md](native-sign-recovery.md#closure-summary)
- Static vs dynamic verification strategy split:
  [../verify-static-vs-dynamic.md](../verify-static-vs-dynamic.md)
- Protection recon BEFORE patching (order principle):
  [stacked-protections.md](stacked-protections.md#order-principle-observation-first-analysis-second)
