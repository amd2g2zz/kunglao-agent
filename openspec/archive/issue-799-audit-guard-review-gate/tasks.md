# Tasks — #799 audit guard `.review` prefix-family exclusion

## T1 — SDD spec (this directory)

- [x] `proposal.md` — symptom, root cause (exact component match vs
      `.review-gate/`), scope (both mirrored scanners).
- [x] `design.md` — ruling: `.review` prefix family = local review evidence
      surface; prefix-over-exact rationale; GUARD_TEST_SWEEP finding
      (`test_dedup_319.py:97` mirror); non-goals flagged
      (`.subagent-review/`, `.claude/reviews/`).

## T2 — RED pin (`tests/test_audit_guard_reviewgate_799.py`)

- [x] Pin driver runs the REAL scanners (module ROOT monkeypatched to a tmp
      layout) — no predicate re-implementation.
- [x] v0.1.2 scanner: `.review-gate/evidence-ci-fix.md` with legacy string
      → not an offender (RED under current `".review" in p.parts`).
- [x] dedup-319 scanner: `.review/evidence-x.md` with legacy string → not an
      offender (RED under current `".review-gate" in p.parts`).
- [x] Positive controls: legacy string in a plain repo-content path IS still
      flagged by both scanners (fix must not make the audit vacuous).

## T3 — GREEN implementation

- [x] `tests/test_v012_milestone_audit.py:54` — predicate →
      `any(part.startswith(".review") for part in p.parts)`; semantics of
      `.git` / `.worktrees` / `docs/superpowers` / suffix filter unchanged.
- [x] `tests/test_dedup_319.py:97` — same prefix-family form; scratch-dir
      and self-reference exclusions unchanged.
- [x] `tests/test_worker_liveness_protocol.py:138` — already prefix
      semantics, verified, untouched.

## T4 — Regression + quality gates

- [x] `env -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS uv run python -m pytest
      tests/test_v012_milestone_audit.py tests/test_dedup_319.py
      tests/test_audit_guard_reviewgate_799.py -q --no-cov` — all green.
- [x] Full suite in the worktree (no local `.review-gate` residue):
      `env -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS uv run python -m pytest
      tests/ -q --no-cov`.
- [x] `uv run python devkit/quality_gates.py` all gates green.
- [x] `uv run python scripts/release_receipt.py --check` exit 0.
- [x] `uv run ruff check .` (E9,F63,F7,F82) zero warnings.

## T5 — Land

- [x] PR `fix/799-audit-guard-reviewgate` → dev, Closes #799, auto-squash.
