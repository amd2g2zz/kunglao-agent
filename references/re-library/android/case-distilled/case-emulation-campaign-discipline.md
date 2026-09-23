---
name: case-emulation-campaign-discipline
description: 'Offline emulation campaign discipline for Android native risk-control chains
  (case-distilled, internal campaign D1): byte-exact state extraction into the emulator file
  resolver, milestone rung sequencing (string-decryptor first), the poison-gate rule (validation
  bypass yields structurally-valid key-less success), living architecture map, session handoff
  packages, and route-portfolio planning with switch rules. Use when planning or resuming a
  unidbg-class campaign, when a harness runs clean but answers wrong, or when handing a campaign
  between sessions.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: overlap(unidbg-env-filling, unidbg-harness-bringup — campaign layer is the delta)
campaign_cluster: D (I38-I40,I45-I47,I72,I74,I77-I79,I82; community rows I68,I70 marked in-card)
---

# Emulation campaign discipline (case-distilled)

> Internal-campaign distillate (evidence-derived; provenance = D1 cluster D).
> unidbg-env-filling owns the environment-ANSWER catalog; unidbg-harness-bringup
> owns substrate/hook-slot decisions; unidbg-algo-recovery owns emulator-side
> verification moves. This card owns the CAMPAIGN layer: sequencing, state
> substrate, and the knowledge that must survive between sessions.

## Milestone rungs (planning layer)

Sequence emulation milestones cheapest-verifiable-first; each rung's artifact
is the next rung's input:

```text
rung 1  string-decryptor op standalone      # small, independently checkable output;
                                            # unlocks all hidden strings for later rungs
rung 2  context registration                # java callbacks answered one by one
rung 3  config consumption                  # config blob layout mapped into the harness
rung 4  license/validation chain            # the gate rung — see poison-gate rule
rung 5  sign-op end to end                  # only after rung 4 truly passes
```

Why this order and not sign-first: every later rung consumes strings, context
answers, and config layout from the earlier ones, and the license gate POISONS
failure (below) — attempting the sign op before the gate genuinely passes
produces structurally valid garbage that looks like progress.

## The poison-gate rule

Verdict algebra:
`validation bypass ⇒ structurally-valid, key-less execution`;
`genuine keys ⇔ validation genuinely passes`. When validation failure routes
through a thunk to a poison block (baked stack + branch to a computed target),
skipping the check does not skip the consequence — the session keys are
CONSTRUCTED during validation. Route: make the license chain pass for real
(analyze the validator's inputs; license blob, package/cert evidence), or
extract keys by the static route; never accept the bypass's clean-looking
empty output as success.

## Byte-exact state substrate

| Situation | Action |
|---|---|
| server-issued session state lives in local files | pull byte-exact through a base64 pipe (direct tar corrupts line endings); filename = content hash confirms provenance |
| state tree mapped into the emulator | register the file tree in the emulator's file resolver; the harness replays a REAL session's state, not a guess |
| replay diverges from live behavior with identical bytes | remaining variable is calling-context register residue — record as OPEN with what it blocks (pure offline re-derivation) and what it does not (engine-path execution), instead of forcing a conclusion |

## Architecture map + ledgers (campaign memory)

| Artifact | Content | Update rule |
|---|---|---|
| living architecture map | one chain diagram boundary→core with per-edge confidence + evidence pointer | every session; it is the deliverable even when algorithm work stalls |
| disproved-hypothesis ledger | each dead hypothesis + the experiment that killed it | read BEFORE any retry; a retry without a new variable is forbidden |
| excluded-function ledger | functions ruled out + disqualifying reason | prevents re-investigation of ruled-out functions |
| session handoff package | unresolved todos with exact balances, ready tools, key sample pointers, start commands | next session resumes execution, not rediscovery |

`[community-claim]` Public work already proves emulation sign-factories are
mature (so the bottleneck is never the arithmetic itself), and a week-scale
pure-algorithm route exists for VM-protected packets (bound the VM window →
back-derive from the final packet → local dynamic trace → lift → byte-for-byte
native compare).

Route portfolio (campaign synthesis): main line + cheap parallel line +
explicit fallback + discouraged grey shortcut, each naming its blocking
condition, with the switch rule written down — the portfolio exists so a
blocked main line degrades to a prepared route instead of to improvisation.

`[community-claim]` External writeup adaptation: adopt pipeline STRUCTURE at
stated confidence, re-extract every constant and address locally, verify per
row of a remap table — structure transfers, constants never do.

## Companions

[case-identity-channel-epistemics](case-identity-channel-epistemics.md)
(the same chain's server-facing face),
[case-hardened-dispatch-recovery](case-hardened-dispatch-recovery.md)
(static partner route), [unidbg-env-filling](../emulation/unidbg-env-filling.md),
[unidbg-harness-bringup](../emulation/unidbg-harness-bringup.md),
[unidbg-algo-recovery](../emulation/unidbg-algo-recovery.md).
