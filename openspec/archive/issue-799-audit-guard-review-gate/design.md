# Design — #799 audit guard `.review` prefix-family exclusion

## Ruling

The exclusion rule covers the **`.review` prefix family**: any single path
component that starts with `.review` (`any(part.startswith(".review") for
part in p.parts)`). Covered members: `.review` (the retired #455/#472
process dir, still gitignored at `.gitignore:80`), `.review-gate` (the live
review-gate evidence surface, `.gitignore:38`), and any future `.review-*`
sibling. Semantics of the family: **local review evidence surface, not repo
content** — audit scans that assert properties of repo content must never
read inside it.

## Why prefix match, not exact component

- The #799 failure is literally an exact-match miss: `".review" in p.parts`
  was written for the old `.review/` dir; the gate's evidence dir turned out
  to be `.review-gate/`. Enumerating exact names re-creates the same bug on
  the next rename (`.review-gate-v2`, a per-branch dir, etc.).
- `git ls-files | grep -E '(^|/)\.review'` is empty on dev 225005d — no
  tracked path has a component starting with `.review`, so the prefix rule
  cannot hide repo content from the audit today.
- Precedent inside this repo: `tests/test_worker_liveness_protocol.py:138`
  already excludes with `rel.startswith((".git", ".review", "openspec/",
  ".worktrees"))` — prefix-on-string semantics that already covers
  `.review-gate/...`. The audit scanners are brought to the same semantics.

## Why both scanners change

`grep -rn '.review' tests/ --include='*.py'` (GUARD_TEST_SWEEP) finds the
predicate mirrored in `test_dedup_319.py:97` as
`".review-gate" in p.parts` — the complementary half of the same bug: it
excludes `.review-gate` exactly but NOT `.review`. A dev machine retaining
the retired `.review/*.md` process files (#455/#472 lineage) containing the
legacy pre-commit hook path string false-reds that scanner the same
way #799 false-reds the v0.1.2 one. One family, one rule, both pinned.

## Why the pin drives the real scanners (not a copy of the predicate)

The pins monkeypatch each scanner module's module-level `ROOT` to a tmp
layout and call the real `test_no_legacy_precommit_reference` /
`test_no_reference_to_legacy_precommit_path` functions. A pin that
re-implemented the predicate would pass while the production scanner
drifted — the exact failure mode this issue documents. Driving the real
functions makes the RED state observable under the current exact-match
predicates and the GREEN state durable against future edits.
Precedent for sibling test-module import:
`tests/test_decide_state_machine.py:33`.

## Non-goals (out of #799 scope, flagged for a later ruling)

- `.subagent-review/` (`.gitignore:44`) and `.claude/reviews/`
  (`.gitignore:39`) are also local review surfaces and the v0.1.2 scanner
  would false-red on legacy strings inside them. Widening the family to
  those names is a product/semantics ruling beyond #799's stated scope
  (`.review` prefix family) — left undecided here.
- `".git" in p.parts` stays exact-match: the git dir component is fixed by
  git itself (`.git` files in worktrees still contribute the literal part
  `.git`), and no `.git-*` family exists in-tree.
