---
name: external-captcha-perception-atlas
description: 'The per-family route atlas for 19 captcha families (companion
  to external-captcha-perception-methods): full route tables with
  engineering-grade parameters (Canny thresholds, binarization levels,
  CSL bin counts, A* grid specs, dilate kernels, easing intervals),
  accuracy bands split live/bench/claim, when-each-route-wins conditions,
  and the source anchors per route. Read alongside the routing card; this
  file carries the parameters its route table condenses.'
domain: web
family: external-distilled
source_id: S9-S68
source_license: mixed
retrieved: 2026-11-03
epistemic: external-derived
distill_bar: general+heuristic+parameters
dedup: overlap(external-captcha-perception-methods routing card — this is its parameter layer)
---

# METHODS ATLAS — 19 captcha families (distill-captcha run, 2026-11-03)

Consolidated cross-family map from the three research groups' corpus files
(same directory, one `<family>.md` each). Source ids reference the
reconciled ledger in [SOURCES.md](SOURCES.md) (S9–S68; URLs live only
there, never in repo-side material). Each row links the family file that
carries the full method, tool parameters, and pitfalls.

## The shared spine (read before any per-family route)

Every family reduces to some ordered composition of four reusable
operators; the families differ only in which operators carry the load:

1. **Locate** — single-class detection or fixed-geometry cropping.
   Hundreds of labels suffice almost everywhere (slider S14: ~200 boxes;
   icon-click S57: 150–300; match-3 S51: ~500; difference-click S57:
   150–300); annotation-free synthetic compositing scales further
   (icon-click S33: ~10k imgs → mAP 94).
2. **Resolve** — turn detections into an answer: similarity matching
   (Siamese vs prompt crop), embedding ranking (query-vs-candidates
   cosine top-k), lexical/corpus constraint (word-order), spatial relation
   algebra (spatial), or protocol matrix solve (match-3/gomoku).
3. **Plan** — geometry → action: drag distance (slider), A* with inflated
   obstacles (obstacle-avoidance), ordered skeleton path (trajectory),
   swap sequence (jigsaw/gomoku).
4. **Humanize** — any emitted gesture must be an eased, jittered event
   stream (33 ms base interval, 16 ms `mousemove` floor, non-zero deltas,
   overshoot-and-correct; S11/S12/S15). Perfect mechanics are themselves
   a bot signature (S12: pass rate decays after repeated identical runs).

## Cross-family routing heuristics (the atlas's generalizable core)

- **Protocol leak before vision.** When the challenge API leaks game
  state, solve on the matrix and skip perception entirely: match-3/gomoku
  `ques` boards give 100% at ~60 lines of Python (S52) — strictly better
  than the 98% CNN route (S50). Vision is the fallback, not the default.
- **Locate-then-match beats end-to-end recognition.** A small detector +
  similarity verification survives unseen classes; per-crop classifiers
  only win on open charsets (text-click S30: multi-class Siamese ~80% vs
  pairwise binary ~90%; icon-click survives unseen icon types via
  Siamese, S57).
- **Embedding similarity is the universal comparator.** match-3 (S50/S51),
  difference-click (S59/S57), obstacle target pick (S56), icon-click
  (S57) all rank candidates against a query with frozen features +
  cosine, or a small Siamese when pretrained features under-separate.
- **Detect-connect-plan** for spatial-structure families: area (corner
  dots → dilate-to-close → contourArea, S26), obstacle-avoidance (boxes →
  inflated A*, S56), trajectory (mask → skeleton → ordered branches,
  S22–S24).
- **Self-supervised and synthetic labels first.** Rotation labels are
  free (rotate any photo, S16); scratch-card's probe stroke makes
  collection deterministic (S19); OCR simulates 200k–500k before
  transferring (S41); font styles render synthetically (dilate/erode/
  contour, S38).
- **Measure end-to-end, never per-module.** Order/phrase/answer tails
  multiply error: text-click Siamese val 0.88 → full pass ~0.35 at 200
  images (S31); word-order survives per-char errors only via top-k
  combinatorial phrase checks (S36); arithmetic scores the computed
  answer, not glyph accuracy (S43).
- **Re-fetch beats parse on bad captures.** Malformed slider strip →
  reroll (S12); scratch cards are single-use → confidence-gate the final
  gesture and re-fetch (S19); audio retries on failure (S62).
- **Compound labels beat head-stacks for multi-attribute objects**
  (spatial: one 91-class detector, mAP@50 0.984, vs one-hot head stacks
  with error propagation, S47).
- **Version/layout exactness is silent.** Grid-captcha crops differ per
  vendor version (v3 112×112 vs v4 100×86, S54); training on v4 and
  testing on v3 is "embarrassing" (S54); fixed-box segmentation dies on
  any layout shift (S44).

## Captcha route atlas (external-distilled)

Accuracy bands: **live** = measured on production traffic; **bench** =
measured on held-out test sets; **claim** = practitioner-reported,
unverified. Full parameter sets in the linked family files.

| Family | Route | Tools | Accuracy band | When this route wins | Sources | Corpus file |
|---|---|---|---|---|---|---|
| **slider** | template match (Canny 100/200 + `TM_CCOEFF_NORMED`, alpha-aware via `slide_match`/`simple_target`) | ddddocr / OpenCV | claim 90%+; fails on icon decoys | default first try; needs the piece PNG | S9, S10, S25 | slider.md |
| | state-pair 1-D strip diff (vertical max-pool → binarize ~48 → 4 transitions) | numpy/OpenCV | live 86% (43/50), decays after bursts | art-heavy vendors; no piece PNG; both states obtainable | S12, S11 | slider.md |
| | single-class YOLO on ~200 labeled gap boxes | YOLOv3/v8 + LabelImg | bench conf 0.9999 | decoy-laden vendors (icon fills, rotated decoys) | S14, S13, S25 | slider.md |
| | CenterNet heads on Lite-HRNet-18-FPN, ~300k synthetic | sider-captcha-solver | bench 85% @5px / 90% @7px, MAE ~1px | industrial scale; trains against rotated decoys + Perlin noise | S13 | slider.md |
| **image-rotation** | ring-masked gradient-overlap angle sweep (Sobel) | OpenCV warpAffine + Sobel | claim ~97% (dual-ring ceiling) | no training data; textured discs; mask the angle-invariant outer ring first | S19, S18, S25 | image-rotation.md |
| | color-distribution brute-force sweep | OpenCV + numpy | claim: validated on 2 live sites | zero thresholds to tune; fragile under style change | S17 | image-rotation.md |
| | CNN angle classification, **CSL-smoothed 128 bins** (never naive 360-class CE) | PyTorch RegNet (rotate-captcha-crack) | bench cross-domain 6.59° vs 53.47° naive | labels are free (self-rotation); generalizes across backgrounds; graceful degradation on low texture | S16 | image-rotation.md |
| **jigsaw-restore** | position-as-class ResNet | ResNet18/50 | claim high with recurring art | few tiles, repeating background pool; breaks on pool rotation | S19 | jigsaw-restore.md |
| | edge-descriptor cosine matrices + greedy/backtrack (threshold 0.1) | numpy/skimage | bench >95% scenery / 70–90% flat / <70% periodic | training-free; per-image solve; periodic textures are the kill case | S21, S19, S25 | jigsaw-restore.md |
| | GA over permutations, boundary-compatibility fitness | numpy | claim: standard at larger n | n beyond 3×3; cites Sholomon CVPR 2013 | S20, S19 | jigsaw-restore.md |
| **trajectory-trace** | YOLO-pose K keypoints + connect, canonical keypoint order | YOLOv8-pose | claim: viable, ordering-supervised | short strokes, few salient points; crossing paths need ordered heads | S19, S25 | trajectory-trace.md |
| | segmentation → `skeletonize` → Skan ordered branches, prune short spurs | Mask R-CNN/PSPNet + skimage/Skan | bench-validated pipeline (PathNet) | long curvy strokes, many crossings; every stroke pixel supervised | S19, S22, S23, S24, S25 | trajectory-trace.md |
| **scratch-card** | deterministic mid-band probe stroke → YOLO exposed fragment → closing circle; re-fetch on low confidence | YOLOv8 | claim: single known recipe | the only documented route; single-use challenges make re-fetch the recovery path | S19, S25, S67(dead) | scratch-card.md |
| **area-computation** | Harris corner dots → open 4×4 → dye-spread dilate 7×7 → `RETR_EXTERNAL` → `contourArea` max → centroid click | OpenCV only, no ML | claim: reference impl passes | dotted-boundary vendors; knobs = open kernel + dilate radius ≈ dot pitch/2 | S26, S19, S25 | area-computation.md |
| **text-click-order** | YOLO locate + Siamese match vs prompt crops ("match, don't recognize") | YOLOv5/v8 + Siamese, ONNX | site bench 96% @300 imgs; **e2e honest: val 0.88 → pass 0.35 @200 imgs** | fixed site, small charset; no OCR needed | S27, S28, S30, S31 | text-click-order.md |
| | YOLO + per-crop classifier, semi-supervised relabel loop | darknet19/ResNet head, 4,277 classes | claim: scales with corpus | open charset / site-agnostic; ~360k crops | S29, S19 | text-click-order.md |
| **icon-click-order** | nano-YOLO + Siamese verification vs prompt icons | YOLOv5n/YOLOv12 + VGG16 Siamese | live-ish mAP50-95 ~94 (~10k synthetic imgs) | easiest click family; vector icons; dedup pipeline is the maintenance core | S57, S33, S34, S19 | icon-click-order.md |
| **word-order-selection** | locate → top-5/crop → cartesian product → jieba+word-freq permutation resolve → search-engine fallback | YOLO + classifier + jieba | claim ~96%/char classifier viable via phrase-level rescue | phrase captchas; fixed idiom corpus variant skips segmentation | S36, S37, S19, S66(dead) | word-order-selection.md |
| **font-style-classification** | 3-class bold/thin/outline gating head; synthetic style rendering + Otsu-mask separated noise (sigma 30) | small ResNet/CNN | bench 98.8–99.8% clean fonts; vendor figures = folklore | style-gated recognition; beat the darkness-vs-morphology confound | S38, S39, S32, S19 | font-style-classification.md |
| **variable-length-ocr** | ddddocr zero-shot + `set_ranges` charset restriction | ddddocr ONNX | community claim 90%+; one 72h case >95% | always try first; init-once, png_fix for alpha | S9, S10 | variable-length-ocr.md |
| | dddd_trainer CRNN fine-tune (auto-ONNX at acc .97 / cost .05) | dddd_trainer | bench 0.97 target | site non-standard; CRNN mandatory for multi-char (CNN mode = single-char only) | S40, S42 | variable-length-ocr.md |
| | simulate 200k–500k → CRNN pretrain → small real transfer | CRNN (Holmeyoung) | claim: zhihu case | scarce real data; greedy CTC (beam too slow) | S41, S42 | variable-length-ocr.md |
| **arithmetic-challenge** | ddddocr expression string → branch-parse → compute (guard `/` typing, validate format) | ddddocr | claim: works on clean glyphs | zero-shot default; **operator-branch parsing bugs are the top real failure** (all branches splitting on '+') | S43, S46, S35 | arithmetic-challenge.md |
| | YOLO + per-crop classifier (digits, operators, Chinese numerals) | YOLO + classifier | claim: hardened variants | Chinese numerals / patterned backgrounds; sort boxes by x, segment number-groups by spacing | S19, S46, S35 | arithmetic-challenge.md |
| | fixed-box pixel-density features, exact-match tables | PIL only | claim: works until layout shifts | brittle fallback; nearest-neighbor distance instead of exact equality | S44 | arithmetic-challenge.md |
| **spatial-attribute-click** | ONE compound-label detector (shape×color×orientation, 91 classes) + prompt-strip OCR + relation vectors | YOLO-class detector | live 86.45–98.45% across 6 vendors; mAP@50 0.984 @1,200 imgs | multi-attribute reasoning; beats one-hot head stacks (no error propagation) | S47, S48, S19 | spatial-attribute-click.md |
| | detector + one-hot attribute heads + rule-based selection | YOLO + small heads | claim 55% → 96% with prompt/art split | simpler vendors; region size/position = free attributes | S19, S48 | spatial-attribute-click.md |
| | LLM reads raw image (no perception pipeline) | GPT-4o/R1 | **collapses: ~31% zero-shot, 7–33% R1** | never — perception must be explicit; document as the anti-pattern | S47, S49 | spatial-attribute-click.md |
| **match3-triple-select** | grid crop → embedding cosine top-3 vs query (fc head reused as feature space) | ResNet18 + ONNX | live 98% over 50 production tests (~500 imgs) | any vendor; generalizes to classes unseen in training | S50, S51, S63, S19 | match3-triple-select.md |
| | exact-crop MD5 grouping | hashlib only | 100% when cuts align | free fast path before any model | S19, S51 | match3-triple-select.md |
| | leaked `ques` matrix solve (3 same in a row/col) | protocol only | 100%, zero vision | GeeTest v4 when `ques` leaks; **column-major warning** | S52 | match3-triple-select.md |
| **gomoku-line-complete** | leaked 5×5 `ques` matrix + exhaustive line search (rows, cols, **diagonals**) | protocol only | 100%, ~60 lines of Python | v4 `winlinze` when state leaks; no `setLeft`/`track` fields — slider payload code must be stripped | S52, S53 | gomoku-line-complete.md |
| | fixed-geometry color classification + line scan | ResNet18/MD5 | claim: inherits match-3 pitfalls | vision fallback when `ques` unavailable | S19 | gomoku-line-complete.md |
| **ninegrid-street-scene** | stitch → YOLOv8 m/l/x (6/8 classes) + separate classifier for the 2 texture classes (crosswalk, stairs) | YOLOv8 | claim: 6/8 detectable | street-photo grids; texture classes never transfer from object detectors | S19, S54 | ninegrid-street-scene.md |
| | version-exact crops + ResNet18 / PP-HGNetV2-B4, or YOLO11n+DINOv3 embed | PaddleClas/ONNX | bench >99.9%; DINOv3: 1 err / 4,613 | GeeTest-style grids where query comparison, not open detection, is the task | S54, S51 | ninegrid-street-scene.md |
| | VLM auto-labels → train small classifier | VLM + small CNN | claim 98%, low annotation cost | data-cheap bootstrap | S55 | ninegrid-street-scene.md |
| **difference-click-similarity** | embed all candidates → click argmin mean cosine (the outlier) | frozen ResNet50 + YOLO locate | claim: ~150–300 labels for detection | N-similar-plus-one layout; no comparator training needed unless textures confound | S19, S59, S57, S58, S51 | difference-click-similarity.md |
| | Siamese embedding, rank by argmax/argmin per prompt wording | VGG16 Siamese | claim ~90% pairwise | under-separated pretrained features; verify direction (argmax vs argmin) against prompt | S57, S58 | difference-click-similarity.md |
| **obstacle-avoidance-line** | one-class YOLO boxes → Siamese picks target → A* (320×160 grid) with **obstacle dilation 6–8 px + manual bottom barrier** | YOLOv8/11 + Siamese + numpy A* | live "stabilizes around 99%" (repeated 100-run tests) | near-misses fail validation — inflation is mandatory; residual ~1% = detection misses, invest in labels not planners | S56, S19 | obstacle-avoidance-line.md |
| **audio-asr-challenge** | ffmpeg → denoise (noisy sources only) → SenseVoiceSmall → strip emotion/event tags → normalize numerals → retry loop | FunASR / faster-whisper CPU / ONNX+GGUF | field: sub-second transcription; 4-digit = easy, ticketing noise = denoise-first | local, API-free ASR; pin `funasr>=1.3.26`; `language` pinned beats auto on short noisy digits | S60, S61, S62, S19 | audio-asr-challenge.md |

## Route-selection shortcuts (per family, one line)

- **slider** — piece PNG? template match. Both states? strip diff. Icon decoys? YOLO.
- **image-rotation** — textured disc + no data? gradient sweep. Any photos collectible? CSL CNN.
- **jigsaw** — art repeats? position-as-class. Fresh art? edge cosine + backtrack (n≤3) / GA (n>3).
- **trajectory** — few salient points? keypoints. Curvy/crossing? skeleton.
- **scratch-card** — one recipe only; confidence-gate the circle, re-fetch otherwise.
- **area** — pure CV chain; tune two knobs to the vendor's dot pitch.
- **text-click** — fixed site? Siamese. Open charset? classifier loop. Budget 1–2k imgs for honest e2e.
- **icon-click** — dedup pipeline first, model second.
- **word-order** — always top-k crops + phrase-level resolution.
- **font-style** — synthetic styles + separated-noise augmentation; audit confusable pairs.
- **variable-length-ocr** — ddddocr + set_ranges, escalate to CRNN only on failure.
- **arithmetic** — recognition is the easy half; harden the parse-and-compute tail.
- **spatial** — compound labels + explicit perception; never LLM-on-raw-image.
- **match3 / gomoku** — check the API for a leaked board first; vision second.
- **ninegrid** — texture classes need their own model; match crop sizes to the vendor version.
- **difference-click** — embedding outlier; verify argmax/argmin direction.
- **obstacle** — inflate obstacles, seal the bottom, add the time dimension.
- **audio** — denoise only when noisy; strip tags; pin the language.

## Provenance

- 19 family corpus files (this directory) carry full methods, tool
  parameters, and pitfalls per family; each cites the reconciled ledger.
- SOURCES.md holds the URL ledger (operator-local, never committed).
- Precedent card shape for repo-side promotion:
  `references/re-library/web/external-distilled/external-algorithm-recovery-chains.md`
  (frontmatter: name/description/domain/family/source_id/source_license/
  retrieved/epistemic/distill_bar/dedup; generalized body; S-id
  provenance only).
- Landing-face outcome for these prose cards: staged attempt
  `ws-sandbox/runs/distill-candidates/attempt-1-method-cards` — see
  [DISTILL-RUN-REPORT.md](DISTILL-RUN-REPORT.md).

## Tool reference (canonical public addresses)

The studied-source URLs live in the operator ledger (S-ids above). The
TOOLS the routes build on are public packages — their canonical
addresses are method infrastructure, not sources:

| Tool | Canonical address | Role | Families |
|---|---|---|---|
| ddddocr | `pip install ddddocr` · github.com/sml2h3/ddddocr | zero-shot OCR (set_ranges) + slider gap (`slide_match`/`simple_target`) | var-length OCR, arithmetic, slider |
| dddd_trainer | github.com/sml2h3/dddd_trainer | the training half of ddddocr (ImageHeight 64, SGD lr 0.01, early-stop acc 0.97) | var-length OCR fine-tune |
| Ultralytics YOLO (v5/v8/v11/pose) | `pip install ultralytics` · github.com/ultralytics/ultralytics | locator / compound-label detector / keypoint mode | slider, all click families, spatial, obstacle, trajectory, 9-grid, arithmetic |
| bubbliiiing/Siamese-pytorch | github.com/bubbliiiing/Siamese-pytorch | the Siamese match-vs-prompt-crop comparator (VGG-style backbone, ONNX export) | text-click, icon-click, difference-click, obstacle |
| torchvision ResNet18/50/101 | pytorch.org/vision (torchvision.models) | position-as-class, per-crop classifiers, frozen feature extractor | jigsaw, font-style, match-3, word-order, difference-click |
| rotate-captcha-crack | github.com/zhenglin-li/rotate-captcha-crack | the CSL-smoothed rotation CNN (RegNet_Y_3_2GF, self-supervised rotation labels) | image-rotation |
| OpenCV | `pip install opencv-python` (docs: docs.opencv.org) | Canny/Sobel/warpAffine/matchTemplate/contours/Harris — the whole CV spine | slider, rotation, jigsaw, area, trajectory |
| scikit-image | `pip install scikit-image` (`skimage.morphology.skeletonize`, `medial_axis`) | skeleton extraction (trajectory scheme 2) | trajectory, jigsaw |
| Skan / FilFinder | `pip install skan` · `pip install fil_finder` | ordered branch extraction from the skeleton graph | trajectory |
| FunASR + SenseVoiceSmall | `pip install funasr` · model id `iic/SenseVoiceSmall` (+ fsmn-vad) | sub-second ASR for short audio clips | audio |
| faster-whisper | `pip install faster-whisper` | CPU-only ASR fallback (no-torch setups) | audio |
| PaddleOCR | github.com/PaddlePaddle/PaddleOCR | prompt-text OCR (spatial reasoning instructions) | spatial |
| jieba | `pip install jieba` | lexical resolution over click-order permutations | word-order |
| AntiCAP | pypi: AntiCAP | packaged multi-type solver incl. math (baseline comparator) | arithmetic |
| LabelImg | github.com/HumanSignal/labelImg | manual bounding-box annotation | slider, click families |
| ONNX Runtime | `pip install onnxruntime` | CPU serving for detector+matcher exports | click families, font-style |
| Roboflow keypoint recipe | notebook: train-yolov8-keypoint.ipynb | the standard keypoint training recipe | trajectory |
