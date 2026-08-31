# User-facing summary has zero constraints: uncertainty vanishes in transcription (#831)

Child of #825.

## Why

The facts layer was *honest*: 76 lines of `unconfirmed / pending / hypothesis / T1-boundary` markers across F010-F017, with each fact documenting its own open items (§G/§D sections). The orchestrator's user-facing summary then declared "分析收敛完成 — 协议全链还原 / q1+q2+q3 全部闭合 / 16/16 PROVEN", dropping every uncertainty marker. An independent auditor answered the only question that matters: with these facts an engineer **cannot** send one authenticated request (no base URL, no reproducible signature, no wire sample).

This is the C-020 pattern (maker-checker.md incident: correct evidence → wrong report via transcription loss) recurring at the **conversational** layer: nothing hooks the assistant's own summary text. CLAUDE.md carries a soft vocabulary ban ("avoid FINAL / TRULY / complete / convergence achieved without explicit user sign-off") with no enforcement, and the located-vs-reproduced distinction (know where the algorithm lives vs able to re-run the algorithm) is not encoded anywhere in the schema.

## What Changes

- Machine-checkable uncertainty propagation at handoff: the deliverable summary must be generated from the fact base, and a checker (reuse the hr-report-side `manual_audit.py` pattern) verifies every unconfirmed/pending marker in facts appears in the summary or is explicitly waived with reason. Missing waiver → block delivery.
- Stop-hook vocabulary check on the session's final message: completion words (完整 / 全部闭合 / CONVERGED / 还原 / fully reverse-engineered) require a companion evidence-tier declaration listing every NOT-independently-verified claim (in the incident: the 15 INFERRED), else the hook injects a correction request.
- Schema: add `reproduction_level: located | reproduced` per fact — summaries may claim `reproduced` only where facts carry it.