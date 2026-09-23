---
name: case-distilled-gap-report-D1
description: '#364 internal campaign distillation wave (D1, android risk-control lane, desensitized):
  algorithmic clustering record (TF-IDF + spherical k-means, silhouette-selected k) and per-cluster
  verdicts, six case-distilled cards with dedup lines, overlap rows citing our cards, abandoned
  case-specific rows, candidate tool adoptions (route through #359), and the desensitization audit
  result with blocklist extension categories. Read before extending the android case-distilled lane
  or judging a follow-up adoption.'
domain: android
family: case-distilled
source_id: D1
source_license: internal
retrieved: 2026-09-23
epistemic: evidence-derived
distill_bar: general+heuristic
dedup: new
---

# #364 Case distillation wave 1 (D1) — gap report (desensitized)

> Internal-campaign distillate, desensitized by construction: campaign id D1
> + internal item ids only. Private ledger + pipeline log live in untracked
> scratch. Pipeline spec: references/contracts/distill-pipeline.md.
> Epistemic classes in this wave: `evidence-derived` (campaign's own verified
> experiments) vs `community-claim` (public-source testimony from the
> campaign's strategy draft, marked inline in cards) — never merged.

## Clustering record (algorithmic; owner ruling)

Assignment is algorithmic, not hand-curated: TF-IDF (latin words + CJK
bigrams, stopword-filtered) + L2 norm + spherical k-means (cosine), 40 seeded
restarts per k, k in [4,12] chosen by mean silhouette.

| k | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|
| silhouette | 0.0058 | 0.0041 | 0.0068 | 0.0066 | 0.0059 | **0.0088** | 0.0064 | 0.0072 | 0.0070 |

Chosen k=9 (silhouette 0.0088; binary-TF robustness variant k=6 / 0.0099 —
same weak-separation verdict). Honest finding: method-vocabulary statements
share house vocabulary, so bag-of-words structure is SOFT. Clustering served
as (a) dedup net and (b) unbiased structure evidence; assessment-stage
consolidation into six groups is recorded with per-card cluster provenance
(`campaign_cluster` frontmatter + private pipeline log).

## Per-cluster verdicts (three-valued)

| Group | Members | Verdict | Landed |
|---|---|---|---|
| A hardened dispatch recovery (C7,C1,C3 + cross) | 22 items | distill | case-hardened-dispatch-recovery |
| B kill-evidence counterplay (C1/C8/C0 cross) | 6 items | distill | case-kill-evidence-counterplay |
| C identity + channel epistemics (C5 + cross) | 16 items | distill | case-identity-channel-epistemics |
| D emulation campaign discipline (C6/C8 cross) | 14 items | distill | case-emulation-campaign-discipline |
| E observation + claim discipline (C0/C2/C4 cross) | 17 items | distill | case-observation-claim-discipline |
| F constant-fingerprint attribution (C7/C8 cross) | 5 items | distill | case-constant-fingerprint-attribution |

## Overlap rows (cite OUR cards)

| Item | Overlaps | Delta kept where |
|---|---|---|
| output-shape header reading | web-re-quickref crypto-algorithm signatures + unidbg-algo-recovery output-length priors | compatible layers: shape-first triage vs length-prior constant search; noted in cards F/E intros |
| VMP trace schema (per-step opcode/handler records) | jsvmp-triage instruction-trace methodology | schema detail is a small delta on jsvmp-triage's opcode-map step; not landed |
| layered ISA recovery artifacts | vm-protection-anatomy + jsvmp-triage | practice folded into jsvmp-triage's methodology outline conceptually; not landed |

## Abandoned rows (case-specific, desensitized one-liners)

- Endpoint/host inventories, query templates, collection scheduling and
  level-acceptance specifics — identity/ops, no generality after stripping.
- License/auth literals, constant-table values, header-name structures —
  campaign intelligence; placeholders only in cards.
- Long-link (QUIC-class) transport frame/body reconstruction detail —
  case-specific; the general encrypted-channel skeleton is in card C.
- Community article pipeline specifics — identity-bound; the reusable
  remap-table discipline is kept as a `[community-claim]` row in card D.
- Device-reset command specifics — identity-bound; the rule survives in C.
- Address/offset inventories, IDA annotation scripts, crash-dump specifics —
  case artifacts, not methodology.

## Candidate adoptions (capability-level; adoption = route through #359's filter)

1. **Constant-folding batch script family** — regex extraction of
   (table-entry, mask, const, mask, const, key) tuples + relocation-aware
   fold + disassembly-prologue validation; candidate kunglao CLI beside the
   existing native static shelf.
2. **Handler-slide patcher** — locate `adr/mov lr/ret` runs and patch a
   COPY of the .so so decompilers recover handler bodies; candidate pairing
   with the fold script.
3. **Pairwise window state-diff recorder** — per-window state snapshot
   (cache/attestation state) emitted beside each capture so window
   comparisons enforce state parity (card E's rule,机械化 face).

## Desensitization audit

Pre-commit audit over the full diff: campaign blocklist + extensions
(categories recorded privately; the extensions cover app/package aliases,
SDK module names, internal state-file prefixes, additional signature-header
names, monitoring/CDN hosts, app-id and device-id literals, version-code
literals, opCode hex prefixes, community-source site names, certificate
subject tokens, confusable in-binary strings, hotfix tokens). Any 6+ digit
numeric literal flagged for manual judgment. Result: clean at PR time
(reviewer re-verified over `git diff origin/dev...HEAD`).

## Lane naming decision (documented per issue #364)

`external-distilled` = #358's lane for external-source distillates with
S-id + license discipline. Internal-campaign distillates use
`case-distilled/` under the owning domain (android first): provenance class
differs (internal evidence vs external sources), so the lane name differs.
Frontmatter carries `source_id: D1` (campaign id), `source_license:
internal`, `epistemic: evidence-derived`.
