---
name: external-captcha-perception-methods
description: 'External-distilled perception methods for 19 captcha families
  (slider, rotation, jigsaw, trajectory, scratch-card, area, text/icon/word-order
  click, font-style, OCR, arithmetic, spatial-reasoning, match-3, gomoku,
  9-grid, difference-click, obstacle-avoidance, audio). Four-operator spine
  (locate, resolve, plan, humanize), route tables with accuracy bands, and
  nine routing heuristics: protocol leak before vision, locate-then-match,
  embedding similarity as universal comparator, detect-connect-plan,
  self-supervised labels first, end-to-end measurement, re-fetch over parse,
  compound labels over head-stacks, version-exact crops. When choosing an
  attack route for an interactive-perception captcha and deciding whether
  to train, match, or read the protocol.'
domain: web
family: external-distilled
source_id: S9-S68
source_license: mixed
retrieved: 2026-11-03
epistemic: external-derived
distill_bar: general+heuristic
dedup: overlap(web-crawler-engineering captcha triage; external-algorithm-recovery-chains L2/L3)
---

# Captcha perception methods (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized
> paraphrase; provenance = S-id ledger above. Advisory doctrine: route
> selection and method shape — per-vendor accuracy must be measured
> end-to-end before trusting any band below.

## The four-operator spine

Every family composes the same four operators; families differ in which
operator carries the load.

| Operator | Content | Anchor sources |
|---|---|---|
| locate | single-class detection (hundreds of labels suffice) or fixed-geometry crop | S14 ~200 boxes; S33 synthetic ~10k; S57 150-300 |
| resolve | Siamese match vs prompt crop / embedding top-k / lexical corpus / relation vectors / protocol matrix | S27-S31, S36, S47, S50-S52 |
| plan | drag distance, A* with inflated obstacles, ordered skeleton, swap sequence | S12, S22-S24, S56 |
| humanize | eased jittered event stream (33 ms base, 16 ms floor, non-zero deltas, overshoot-correct); perfect mechanics are a signature | S11, S12, S15 |

## Routing heuristics (the generalizable core)

1. Protocol leak before vision — leaked board matrices give 100% at
   ~60 lines vs 98% for the CNN route (S52 vs S50).
2. Locate-then-match beats end-to-end recognition on closed sets;
   classifiers only win on open charsets (S30: ~80% multi-class vs ~90%
   pairwise binary Siamese).
3. Embedding similarity is the universal comparator (query-vs-candidates
   cosine top-k: S50/S51, S56-S59).
4. Detect-connect-plan for spatial-structure families (S22-S26, S56).
5. Self-supervised/synthetic labels first (S16 rotation, S19 probe
   stroke, S38 glyph rendering, S41 simulate-then-transfer).
6. Measure end-to-end, never per-module — order tails multiply error
   (S31: val 0.88 -> pass 0.35 @200 imgs; S36 top-k phrase rescue).
7. Re-fetch beats parse on bad captures (S12 reroll; S19 single-use;
   S62 retry loop).
8. Compound labels beat one-hot head stacks for multi-attribute objects
   (S47: 91-class detector mAP@50 0.984, live 86-98%; LLM-on-raw-image
   collapses to ~31% — documented anti-pattern).
9. Version/layout exactness is silent — per-version crop sizes and
   layout-locked boxes degrade without errors (S44, S54).

## Route table (condensed)

| Family | Best route (band) | When it wins | Sources |
|---|---|---|---|
| slider | strip diff (86% live) / template match / YOLO / synthetic CenterNet (85-90% bench) | decoys -> YOLO; both states -> strip; piece PNG -> template | S9-S15, S25 |
| image-rotation | CSL 128-bin CNN (6.59 deg cross-domain) / ring-masked Sobel sweep (~97% claim) | photos collectible -> CNN; no data -> sweep | S16-S19 |
| jigsaw | edge cosine + backtrack (>95% scenery, <70% periodic) / position-as-class / GA | art repeats -> classify; else edge search | S19-S21 |
| trajectory | skeleton route (robust) / keypoint route (cheap) | crossings -> skeleton + ordered branches | S19, S22-S25 |
| scratch-card | probe stroke + YOLO + circle (single recipe) | confidence-gate, re-fetch on failure | S19, S25 |
| area | Harris dots -> dye-spread dilate -> contourArea (no ML) | knobs match vendor dot pitch | S26, S19, S25 |
| text-click | YOLO+Siamese (96% site bench) / classifier loop (open charset) | order assignment is the hard part | S27-S32 |
| icon-click | nano-YOLO + Siamese (mAP ~94) | dedup pipeline is the maintenance core | S33, S34, S57 |
| word-order | top-k crops + lexical resolution (jieba/freq/search) | phrase-level rescue absorbs char errors | S36, S37 |
| font-style | 3-class head + separated-noise aug (98.8-99.8% bench) | beat the darkness-vs-morphology confound | S38, S39, S32 |
| var-length OCR | ddddocr + set_ranges (90%+ claim) -> CRNN fine-tune | charset restriction is the cheapest lever | S9, S10, S40-S42 |
| arithmetic | recognition + hardened parse-and-compute tail | operator branches and '/' typing are the failure surface | S43-S46, S35 |
| spatial | compound-label detector + relation vectors (86-98% live) | never LLM-on-raw-image (~31%) | S47-S49 |
| match-3 / gomoku | leaked matrix solve (100%) / embedding top-3 (98% live) / MD5 fast path | check the API before training anything | S50-S54, S63 |
| 9-grid | YOLOv8 6/8 classes + texture-class model / version-exact crops (>99.9%) | texture classes never transfer; crops are per-version | S19, S54, S55 |
| difference-click | embedding outlier argmin (no comparator training) | verify argmax/argmin direction vs prompt | S57-S59 |
| obstacle | one-class YOLO + Siamese pick + A*, dilate 6-8 px, bottom barrier (99% live) | near-misses fail validation; invest in detection recall | S56 |
| audio | ffmpeg -> denoise-if-noisy -> SenseVoiceSmall -> tag strip + numeral normalize | local API-free ASR; pin the language | S60-S62 |

Companions: [external-algorithm-recovery-chains.md](external-algorithm-recovery-chains.md)
(challenge five-line decomposition — this card is the L2/L3 perception
layer), [web-crawler-engineering.md](../crawler/web-crawler-engineering.md)
(captcha triage and response budget).
