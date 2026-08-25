## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-687-workspace-export-contract` branch
      `issue-687-workspace-export-contract` off origin/dev `b2b3661` (unchanged head)
- [x] 1.2 Baseline: `uv run python -m pytest tests/test_workspace_export_540.py -q`
      = 30 passed, 1 failed (`test_manifest_sha256_is_actual`) — RED captured

## 2. Triage (evidence, not guesswork)

- [x] 2.1 Hash pair computed: LF literal vs CRLF disk bytes; manifest value matches
      CRLF (actual bytes) — production faithful
- [x] 2.2 Ruling: test stale / platform-brittle expectation (`write_text` newline
      translation vs hardcoded LF hash)
- [x] 2.3 Cross-check: roundtrip + tamper tests green on same tree (end-to-end
      consistency over actual bytes)

## 3. OpenSpec artifacts (SDD)

- [x] 3.1 proposal.md (reduced scope: 7/8 fixed by #685, this card = last red)
- [x] 3.2 design.md (D1-D6, incl. RED-under-test-stale bookkeeping)
- [x] 3.3 specs/workspace-export-manifest/spec.md
- [x] 3.4 tasks.md

## 4. GREEN — test fix (test-side only)

- [x] 4.1 Fixture pinned via `write_bytes` (LF + CRLF params); expectation derived
      from the same single literal; in-code ruling note referencing #687
- [x] 4.2 Full file green (32/32 after +1 CRLF param; was 30+1 on dev)
- [x] 4.3 No production change to `scripts/kunglao_export.py`

## 5. Gates & bookkeeping

- [x] 5.1 `uv run python devkit/quality_gates.py` — no new failures outside the
      known ledger (workspace_export-sha256 leaves the ledger)
- [x] 5.2 Issue comment: full 8-red triage table (7 fixed by #685 + this ruling),
      pre-#685 enumeration for the 8-vs-9 reconciliation
- [x] 5.3 PR `fix(#687): ...` → base dev, body with triage/RED/GREEN/gates; Closes #687
