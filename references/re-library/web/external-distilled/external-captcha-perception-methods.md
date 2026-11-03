---
name: external-captcha-perception-methods
description: 'External-distilled attack-route manual for 19 captcha families
  (slider, rotation, jigsaw, trajectory, scratch-card, area, text/icon/word-order
  click, font-style, OCR, arithmetic, spatial-reasoning, match-3, gomoku,
  9-grid, difference-click, obstacle-avoidance, audio). Built around the
  exploration procedure an operator actually runs: triage the challenge,
  capture the material, fire the cheap probes (API board-leak, crop
  exactness, decoy census, piece-asset check) BEFORE building anything,
  then select from the route table with accuracy bands. Four-operator spine
  (locate, resolve, plan, humanize), nine routing heuristics, and the
  universal traps (alpha-channel matching, scale ratios, trajectory
  biometrics, easing decay). When facing an unknown interactive-perception
  captcha and deciding what to capture, what to probe first, and which
  route to build.'
domain: web
family: external-distilled
source_id: S9-S68
source_license: mixed
retrieved: 2026-11-03
epistemic: external-derived
distill_bar: general+heuristic+procedure
dedup: overlap(web-crawler-engineering captcha triage; external-algorithm-recovery-chains L2/L3)
---

# Captcha attack-route manual (external-distilled)

> External-derived methodology (never directly PROVEN). Generalized
> paraphrase; provenance = S-id ledger above. Advisory doctrine: run the
> exploration procedure in order — every route below was chosen by some
> operator AFTER answering the same four questions this manual encodes.

## The exploration procedure (run this before building anything)

**Step 1 — Triage the challenge type.** What the challenge SHOWS names the
family: a background with a gap + a draggable piece (slider); characters
plus a prompt like "click these in order" (text-click); vector icons +
icon prompt (icon-click); characters forming a phrase/idiom (word-order);
objects with attributes + a written question (spatial); a disc to rotate
(rotation); a 3x3+ image grid, pick the same class (9-grid / match-3 by
pair count); a board with pieces (gomoku); shuffled tiles (jigsaw); a
path graphic to trace (trajectory); dotted boundary + a number (area);
near-identical images, click the odd one (difference-click); a play
button (audio); deliberately styled characters (font-style); a char
string input (alphanumeric); digits/operators + an input (arithmetic);
icons to avoid while drawing (obstacle); a scratch layer (scratch-card).

**Step 2 — Capture the material checklist.** The routes below are gated
on what you managed to capture, so capture greedily: BOTH slider states
(before/after) and the piece PNG if it ships as an asset; the prompt
text AND crops of the prompt characters (text/icon click); TWO captures
of every crop-able image (the exactness probe needs the pair); the
challenge/load API response RAW (look for a board/answer structure); the
audio URL; the exact rendered sizes vs served sizes (the scale probe);
the vendor/version fingerprint of the widget (crops are per-version).

**Step 3 — Fire the cheap probes. Ordered by expected value:**

1. **The board-leak probe** (minutes, can win outright): diff two
   challenge loads / read the load-API response — some vendors ship the
   answer structure to the client (a board `ques` matrix, an order
   array). A leak means the protocol path at ~60 lines beats any vision
   build.
2. **The crop-exactness probe** (two captures, pixel-diff): identical
   crops across loads → the md5 fast path (no model); drifting crops →
   classification.
3. **The decoy census**: count distractors and note rotation/noise — a
   few similar icons → matching still works; rotated/synthetic decoys →
   single-class detection (hundreds of labels suffice, annotation-free
   synthetic compositing scales further).
4. **The piece-asset probe**: does the slider piece ship as a
   transparent PNG? → template matching (mind the alpha trap below); no
   asset → capture both states and strip-diff.
5. **The language pin** (audio only): identify the language before
   choosing the ASR.

**Step 4 — Select from the route table** (below) using the probe
answers; build per the companion atlas's parameters.

**Step 5 — Measure END-TO-END, never per-module.** The documented
failure mode is module accuracy that collapses over the task's order
tail (a 0.88-validation Siamese passed only 0.35 of full tasks at a
200-image budget). And on bad captures: re-fetch the challenge — it is
cheaper than parsing garbage.

## The four-operator spine

Every family composes the same four operators; families differ in which
operator carries the load.

| Operator | Content | Anchor sources |
|---|---|---|
| locate | single-class detection (hundreds of labels suffice) or fixed-geometry crop | S14 ~200 boxes; S33 synthetic ~10k; S57 150-300 |
| resolve | Siamese match vs prompt crop / embedding top-k / lexical corpus / relation vectors / protocol matrix | S27-S31, S36, S47, S50-S52 |
| plan | drag distance, A* with inflated obstacles, ordered skeleton, swap sequence | S12, S22-S24, S56 |
| humanize | eased jittered event stream (33 ms base, 16 ms floor, non-zero deltas, overshoot-correct); perfect mechanics are themselves a signature | S11, S12, S15 |

## Routing heuristics (the generalizable core)

1. Protocol leak before vision (see probe 1).
2. Locate-then-match beats end-to-end recognition on closed sets;
   classifiers only win on open charsets (S30: ~80% multi-class vs ~90%
   pairwise binary Siamese).
3. Embedding similarity is the universal comparator (query-vs-candidates
   cosine top-k: S50/S51, S56-S59).
4. Detect-connect-plan for spatial-structure families (S22-S26, S56).
5. Self-supervised/synthetic labels first (S16 rotation, S19 probe
   stroke, S38 glyph rendering, S41 simulate-then-transfer).
6. Measure end-to-end, never per-module (see Step 5).
7. Re-fetch beats parse on bad captures (S12 reroll; S19 single-use;
   S62 retry loop).
8. Compound labels beat one-hot head stacks for multi-attribute objects
   (S47: 91-class detector mAP@50 0.984, live 86-98%; LLM-on-raw-image
   collapses to ~31% — documented anti-pattern).
9. Version/layout exactness is silent — per-version crop sizes and
   layout-locked boxes degrade without errors (S44, S54).

## Universal traps (cross-family; each one cost a real build)

- **The alpha-channel trap** (slider/template): `matchTemplate` ignores
  transparency — a transparent-PNG piece matched without masking returns
  garbage; mask-aware matching supports only `TM_SQDIFF`/
  `TM_CCORR_NORMED`.
- **The scale trap**: served image size ≠ rendered size — multiply
  distances by the render/source ratio or every number is off by a
  constant (the hardcoded fudge factors in public repos are symptoms).
- **The decoy census is the signal**: decoy style predicts the route —
  dimmer shadow notches (template still works), same-size icon fills
  (template dies, detection needed), rotated synthetic gaps (train
  against rotated + noised synthetics).
- **Trajectory biometrics**: perfectly linear motion is itself a bot
  signature; too-perfect easing DECAYS pass rate over bursts (measured:
  86% declining until the easing parameters were re-tuned). Chrome caps
  `mousemove` at ~16 ms; zero-delta events are detectable.
- **Two-phase desync** (slider): if the piece teleports on the first
  move, one calculated move fails — re-screenshot and correct instead of
  re-deriving.
- **The ink-darkness confound** (font-style): bold/thin/outline
  classifiers key on ink darkness, not morphology — Otsu-mask
  fg/bg-separated noise augmentation is the documented fix.
- **The operator-branch copy-paste** (arithmetic): splitting on `+` for
  every operator and the `/` float-vs-int typing are the two top real
  bugs in public implementations.
- **The lexical rescue** (word-order): per-crop top-5 candidates →
  cartesian product → lexical resolve (dictionary over the permutations,
  word-frequency tie-break, search-engine fallback) absorbs per-char
  errors that would otherwise kill the order.

## Route table (condensed; parameters in the companion atlas)

| Family | Route(s) (band) | Selected by | Sources |
|---|---|---|---|
| slider | strip diff (86% live) / template match / YOLO / synthetic CenterNet (85-90% bench) | probes 2+4 + decoy census | S9-S15, S25 |
| image-rotation | CSL 128-bin CNN (6.59 deg cross-domain) / ring-masked Sobel sweep (~97% claim) | training data available? | S16-S19 |
| jigsaw | edge cosine + backtrack (>95% scenery, <70% periodic) / position-as-class / GA | tile count + art repetition | S19-S21 |
| trajectory | skeleton route (robust) / keypoint route (cheap) | stroke length + crossings | S19, S22-S25 |
| scratch-card | probe stroke + YOLO + circle (single recipe) | confidence-gate, re-fetch on failure | S19, S25 |
| area | Harris dots -> dye-spread dilate -> contourArea (no ML) | dotted-boundary vendors | S26, S19, S25 |
| text-click | YOLO+Siamese (96% site bench) / classifier loop (open charset) | charset closed? | S27-S32 |
| icon-click | nano-YOLO + Siamese (mAP ~94) | vector icons | S33, S34, S57 |
| word-order | top-k crops + lexical resolution (jieba/freq/search) | phrase corpus reachable | S36, S37 |
| font-style | 3-class head + separated-noise aug (98.8-99.8% bench) | style classes fixed | S38, S39, S32 |
| var-length OCR | ddddocr + set_ranges (90%+ claim) -> CRNN fine-tune | charset restriction | S9, S10, S40-S42 |
| arithmetic | recognition + hardened parse-and-compute tail | operator branches hardened | S43-S46, S35 |
| spatial | compound-label detector + relation vectors (86-98% live) | never LLM-on-raw-image (~31%) | S47-S49 |
| match-3 / gomoku | leaked matrix solve (100%) / embedding top-3 (98% live) / MD5 fast path | probe 1 first | S50-S54, S63 |
| 9-grid | YOLOv8 6/8 classes + texture-class model / version-exact crops (>99.9%) | texture classes never transfer | S19, S54, S55 |
| difference-click | embedding outlier argmin (no comparator training) | verify argmax/argmin direction vs prompt | S57-S59 |
| obstacle | one-class YOLO + Siamese pick + A*, dilate 6-8 px, bottom barrier (99% live) | near-misses fail validation | S56 |
| audio | ffmpeg -> denoise-if-noisy -> SenseVoiceSmall -> tag strip + numeral normalize | probe 5 (language pin) | S60-S62 |

Companions: the route
**atlas** ([external-captcha-perception-atlas.md](external-captcha-perception-atlas.md))
carries the full per-route parameter sets this table condenses;
[external-algorithm-recovery-chains.md](external-algorithm-recovery-chains.md)
is the L2/L3 planning layer;
[web-crawler-engineering.md](../crawler/web-crawler-engineering.md)
owns the triage-and-response budget.
