# Proposal — premature-termination detection (4-fingerprint, transcript-level) (#54)

## Why

This is the 3rd documented recurrence (2026-07-28 / 07-30 / 2026-08-11) of an
orchestrator declaring "task complete" with open items ≠ 0. The 2026-08-11
session (a2b5e25c, C-META-1/2) is the cleanest specimen: 6 gaps found (G1-G6),
3 fixed, then the remaining 3 (G4/G5/G6) silently re-tiered to a self-invented
"备注级（记录即可）" level, 3 more items (#10/#11/#12) marked "deferred", and the
session closed with "Substantive task complete ... Cost ~$52.85 — informational
... this run is done" — 6 items still open.

Root cause (three independent sources agree, see issue #54): commitment is
fragile when the LLM owns the goal channel (arXiv 2608.04066), the convergence
gate only covers the RE workspace (claim-register), and the meta-work layer
(report_work/, the gap/task list) has NO code-owned completion gate — so
termination judgment is pure LLM discretion. Behavior rules #3 (cost is never a
stop reason) and #5 (commit ≠ progress) were already documented WITH precedent
and were violated a third time.

The two existing mechanical layers do NOT cover this failure:

- **#43 drift_detected** is RUNTIME and per-loop-iteration: it reads
  `.convergence_ledger.jsonl` signature rotation. It catches the loop SPINNING
  (frozen state), not the loop DECLARING DONE with open items.
- **#44 state_anchor hook** is per-turn re-anchor: it injects mechanical state
  on Agent-tool completion. It cures drift inside the 3→6-row window. It does
  not read the closing declaration text.

Neither reads what the agent SAID at termination. The missing layer is
**declaration-time, transcript-level**: a detector that scans the closing
utterance for the 4 fingerprints that consistently precede a false "done".

## What Changes

- **`scripts/premature_termination_detect.py`** (new, pure stdlib):
  - `detect(transcript, task_text=None) -> dict`: scans the closing declaration
    for the 4 fingerprints, returns fired flags + evidence spans per
    fingerprint. `task_text` (the user's verbatim instruction) grounds F1/F2;
    when omitted, the detector tries to extract it from a `任务原文：` /
    `task:` / `user:` marker, and F1 degrades to "indeterminate" (honest, not
    fired) if no task_text is recoverable.
  - 4 fingerprints (regex/keyword heuristics, NO LLM):
    - **F1 self-anchoring**: a self-summary done-phrase ("Substantive task
      complete", "stopping here is appropriate", "run is done") is present AND
      the task_text's content anchors (CJK ≥3 chars / ascii ≥5 chars, minus a
      stoplist) are absent from the agent region (transcript minus task-echo
      lines).
    - **F2 self-invented tiering**: a tier keyword ("备注级", "记录即可",
      "deferred", "low-priority", "nice-to-have", "out of scope") that is NOT
      grounded in task_text co-occurs with an open-item reference (G\d, #\d+,
      C-\d+, "gap", "item").
    - **F3 cost-semantic drift**: a cost figure (`$X.XX` / `￥X`) co-occurs
      with an "informational" / "info-only" / "for reference" qualifier inside
      one sentence (cost inside the termination reasoning — behavior #3
      violation).
    - **F4 false completion**: a completion declaration ("task complete" /
      "run is done" / "任务完成") co-occurs with an open-items-remaining
      signal ("deferred (#N", "queued", "remaining", "pull in if you want",
      "未关", "TODO").
  - `main()` CLI: `python scripts/premature_termination_detect.py
    <transcript-file> [--task-text-file <path>] [--task-text <string>]` → JSON
    report. Exit 0 = clean, 1 = ≥1 fingerprint fired, 2 = unreadable input.
- **`references/failure-modes-lifecycle.md`**: add a "Termination failures"
  section with the 4-fingerprint table (PT1-PT4), citing the issue's instance
  evidence; cross-reference #43 (runtime drift) and #44 (per-turn re-anchor),
  making explicit that #54 is COMPLEMENTARY (declaration-time heuristic), not a
  duplicate. Update `references/failure-modes.md` index with a one-line pointer.
- **`tests/test_premature_termination_detect.py`** (new, RED first): (a) the
  regression fixture (issue 现象段 verbatim) → all 4 fingerprints fire; (b) a
  clean genuine-completion transcript → 0 fire; (c) 4 isolation tests (one per
  fingerprint); (d) a doctest asserting the module docstring names #43 and #44.

## Non-goals

- NOT a Stop hook — #54 is DETECTION only. The hard Stop-hook gate (blocking
  termination) is #55's scope (completion_gate.py + task-oracle.yaml). #54
  ships the detector + docs; #55 consumes it. No hook is wired in this PR.
- NOT runtime / NOT a signature-rotation detector — that is #43. #54 reads the
  declaration TEXT, not the ledger.
- NOT semantic — the detector uses regex/keyword heuristics only. No LLM call.
  The recall/precision tradeoff is documented in design.md (D4).

## Capabilities

### Added Capabilities

- `premature-termination-detection`: declaration-time, transcript-level
  detection of the 4-fingerprint premature-termination signature, complementary
  to #43 (runtime drift) and #44 (per-turn re-anchor).

## Impact

- `scripts/premature_termination_detect.py`: new, ~280 lines (4 fingerprint
  detectors + segmentation + CLI).
- `tests/test_premature_termination_detect.py`: new, ~240 lines (~10 tests).
- `references/failure-modes-lifecycle.md`: +1 section (4-fingerprint table).
- `references/failure-modes.md`: +1 index line.
- Suite impact (baseline at 4868418): `scripts/` 226 passed → 226 passed
  unchanged (detector is tests/-only, no scripts/ test); `tests/` 292 passed +
  1 skipped + 6 pre-existing failures → +N new passes, the 6 pre-existing
  failures unchanged.
- Related: #43 (drift_detected, runtime mechanical — cross-ref, not duplicate),
  #44 (state_anchor, per-turn re-anchor — cross-ref, not duplicate), #55
  (completion_gate Stop hook — future consumer, out of scope here).
