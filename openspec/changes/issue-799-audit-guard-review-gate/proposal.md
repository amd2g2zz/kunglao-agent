# Audit guard scan excludes the `.review` prefix family (#799)

## Why

`tests/test_v012_milestone_audit.py::test_no_legacy_precommit_reference`
(#445: no residual references to the retired legacy pre-commit hook path
under `.claude/hooks/` in repo content)
false-reds on any dev machine that holds local review-gate evidence:

```
AssertionError: legacy pre-commit refs: ['.review-gate/evidence-ci-fix.md']
```

CI pure checkouts are green because `.review-gate/` is gitignored
(`.gitignore:38`) — the files never appear as repo content there. The
divergence is a predicate mismatch: the scanner excludes paths whose parts
contain the exact component name `.review`, but the evidence directory the
review gate actually writes is `.review-gate/` (`scripts/review_gate.py`
mints `.review-gate/<branch>.json`; reviewers drop `evidence-*.md` next to
it). `.review-gate != .review` as a `PurePath.parts` component, so local
evidence files are scanned as if they were repo content.

This is the same family as #794: audit suites sensitive to the local dev
environment. CI green ≠ local green; must be zeroed before the v0.1.3
release.

## What Changes

- **Prefix-family exclusion**: both legacy-ref audit scanners
  (`test_v012_milestone_audit.py::test_no_legacy_precommit_reference` and
  its mirror `test_dedup_319.py::test_no_reference_to_legacy_precommit_path`)
  switch from exact component match to a `.review` prefix-family match —
  any path component starting with `.review` (`.review`, `.review-gate`,
  any future `.review-*` evidence surface) is treated as local review
  evidence, not repo content. `test_worker_liveness_protocol.py:138`
  already uses prefix semantics (`.review` as a `str.startswith` tuple
  member) and needs no change.
- **Pin tests (RED→GREEN)**: new
  `tests/test_audit_guard_reviewgate_799.py` drives both real scanners
  against a tmp layout containing `.review-gate/evidence-*.md` (and
  `.review/*.md` for the dedup mirror) with a legacy string, asserting they
  are NOT counted as offenders — plus positive controls proving the
  scanners still flag a legacy string in a plain repo-content path (the
  fix must not make the audit vacuous).
- **Semantics unchanged elsewhere**: `.git` component exclusion,
  `.worktrees`/`.devfleet-worktrees` scratch-dir exclusion,
  `docs/superpowers` exclusion, suffix filter, and self-reference
  allow-lists all keep their existing behavior.

## Impact

- `tests/test_v012_milestone_audit.py` (one predicate line + comment).
- `tests/test_dedup_319.py` (mirror predicate line + comment).
- New `tests/test_audit_guard_reviewgate_799.py` (6 pins).
- New `openspec/changes/issue-799-audit-guard-review-gate/` (this spec).
- No production code changes; no manifest digest changes.
