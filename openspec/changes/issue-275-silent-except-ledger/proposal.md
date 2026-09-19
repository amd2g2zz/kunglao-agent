# Proposal — issue-275-silent-except-ledger (batch 1)

## Why

Issue 275 quantified the silent-fail-open surface (2026-09-18 sweep):
1139 `except` clauses across scripts/ + hooks/, of which ~170 are exact
`except…: pass` swallows. Fail-open is the correct liveness posture — but
fail-open without a trace is telemetry by omission: the failure is
invisible, so the observability contract lies. Three in-repo precedents
define the honest pattern (kunglao_log null_reasons, annotated-skip
fail-open, rate-limited WARN); none is mechanical, so growth continued
unpoliced.

## What changes

Batch 1 = measurement + gate only. ZERO behavior changes to existing
handlers.

- `scripts/silent_except_lint.py` — AST-based detector counting
  "silent swallow" handlers per file: an except handler whose body is
  entirely no-op statements (`pass`, `...`, bare-string constant
  expression) with no raise and no trace call (Python `ast` only, no
  regex; counting unit = one handler, mirroring
  comment_hygiene_lint's one-unit convention).
- `scripts/silent_except_baseline.yaml` — shrink-only per-file ledger
  seeded via the tool's own `--emit-baseline` from the current tree:
  199 silent handlers across 83 files (the honest inventory;
  calibrated against the issue's per-file evidence — convergence_check
  10, heartbeat_tick 9, backtrack_loop 9, statusline_snapshot 10).
- Lint/audit CLI mirroring comment_hygiene_lint's shape: check mode
  (fail on growth, fail on stale/loose/unbaselined entries),
  `--emit-baseline`, `--json`, `--root`, `--baseline`.
- CI: one new step in the existing `lint-hygiene` job of
  `.github/workflows/release-check.yml` (no new CI leg).
- Deploy surface: the script rides the auto-included `scripts/*.py`
  scaffold set (deploy-manifest regenerated, 399 entries); the ledger
  YAML stays repo-side like `hygiene_baseline.yaml`.
- Tests: `tests/test_silent_except_lint.py` — 32 tests covering the
  detector rule on synthetic shapes, ratchet semantics, CLI contract,
  and the real-tree self-scan gate.

## Non-goals

- No site cleanup: converting the 199 inventoried handlers to
  emit/annotate/WARN is batches 2-3 (top-4 offender files first), on
  the owner milestone decision.
- No change to any existing handler's runtime behavior, no new emit
  surfaces, no hook changes.
- No quality-gates registry entry: extending the existing lint-hygiene
  job is the smallest surface; a new gate number would ripple into
  every gate-count doc-sync claim (Gate 7 scans numeric gate-count
  wording on devkit/ + .github/workflows/).
- Control-flow no-op bodies (`continue`/`break`), default-assignment
  (`x = None`) and default-return bodies are OUT of the detector's
  shape set: the ledger freezes the issue's quantified `except: pass`
  surface, not the wider fail-open family. Widening is a deliberate
  later-batch act that re-seeds the ledger.
