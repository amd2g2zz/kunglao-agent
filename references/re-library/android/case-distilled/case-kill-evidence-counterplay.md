---
name: case-kill-evidence-counterplay
description: 'Anti-tamper triage from kill evidence on hardened Android targets (case-distilled,
  internal campaign D1): hook-install crashes as attribution problems (mechanical explanations before
  intent), prohibition-list and safe-list ledgers with evidence pointers, code-region self-check
  coverage beyond function entries, hook-fatigue cooldown discipline, and the flag-register
  breakpoint-probe pattern. Use when a hook kills the target, when planning which addresses may be
  instrumented, or when a previously survivable hook starts dying.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
campaign_cluster: B (I26,I29,I30,I31,I32,I33; C1/C8/C0 cross-cluster)
---

# Kill-evidence counterplay (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster B).
> anti-analysis owns the generic detection catalog; dynamic-observation-ladders
> owns channel descent. This card owns the EVIDENCE DISCIPLINE around what
> kills the target: every kill is a ledger entry with an attributed cause, and
> attribution has an ordering rule.

## Crash attribution comes before counterplay

Verdict algebra:
`hook-install crash ⇒ attributed cause required before any retry`;
`attributed cause = mechanical explanation ≠ detection intent` — and the
mechanical check comes FIRST, because it is cheaper and it changes the fix:

| Observed at crash | Mechanical explanation to check first | Detection reading only if mechanics ruled out |
|---|---|---|
| inline hook on a function whose address is used in link-register arithmetic | the hook gateway replaced a register the target's arithmetic depends on — the crash is self-inflicted corruption, not a detector | self-checking code |
| tombstone register file equals a recognizable constant table | register poisoning: the target detected entry tampering and loaded known values before a wild branch | — (this IS the detection signature) |
| crash only after N clean rounds | hook fatigue: accumulated instrumentation cost, no single point of failure | degradation-based detection |
| crash with zero hook points triggered | environment-level tripwire or session budget; re-enter with the single lightest hook | broad anti-instrumentation |

The campaign's object lesson, kept as the canonical row: a hook on a
resolver-address function died with an illegal-instruction crash; the first
conclusion ("self-checking key derivation, keys bound to binary bytes") was
overturned when the function turned out to be a four-instruction
`return-to(x30+x0)` branch gadget — the inline hook had corrupted x30
arithmetic. Two sessions of conclusions inherited the wrong attribution.
**Mechanical explanations are enumerated before detection intent is claimed,
and a reversal is written back into every artifact that cited the original
claim.**

## The two ledgers

| Ledger | Content | Rule |
|---|---|---|
| prohibition list | addresses that killed the target + the kill evidence pointer + attributed cause | never re-hook; a prohibition entry survives hypothesis reversal only by explicit re-review |
| safe list | empirically survivable attach points + observed limits (e.g. rate-limited hot functions) | re-enter sessions through the safe list's lightest member first |

Why two lists instead of one "known" table: the lists have different failure
modes. A prohibition entry grows from a kill (strong evidence, one direction);
a safe entry grows from survival (weaker — survivable *so far*, under *that*
window's state). Conflating them makes survival look like safety.

## Coverage of self-checks

| Situation | Rule |
|---|---|
| function entry hook survives | entry survival does NOT clear the call sites — the campaign killed itself hooking a mid-block call point after the entry was proven safe; treat the checked region as (entry + call neighborhood) until measured otherwise |
| detection signature observed (register poisoning) | the poison source names what the target watches; stop touching that surface, switch to observe-only channels |
| static route exists for the same information | prefer static: bytes on disk cannot trip runtime self-checks — the folding route (see case-hardened-dispatch-recovery) recovered what hooks could not touch |

## Cadence

Hook-fatigue rules: consecutive heavy rounds caused early death even with no
hook point triggered — cooldown between rounds on the device, single lightest
hook on re-entry, and window liveness recorded as a data point per round
(liveness under hooks is evidence about posture, not a prerequisite to note
in passing).

Flag-register probe pattern (recognize before hooking the enclosing
function): `read flags / compare / write flags / branch / debug-break` —
writeability test of the condition register = breakpoint-detection class.

## Companions

[case-hardened-dispatch-recovery.md](case-hardened-dispatch-recovery.md)
(static route around hookable surfaces),
[case-observation-claim-discipline.md](case-observation-claim-discipline.md)
(window/state-parity rules for the hooks you do place),
[anti-analysis](../../anti-analysis/catalog/anti-analysis.md) (detection
catalog), [dynamic-observation-ladders](../../method/process/dynamic-observation-ladders.md)
(channel descent when hooks are impossible).
