# Proposal — LICENSE + AGENTS.md for skill-repo compliance (#116)

## Why

The repository has no `LICENSE` file and no `AGENTS.md`. The skill-repo manual
requires both for distributable skill repos: LICENSE for legal clarity and
AGENTS.md for collaborator/onboarding guidance. Although the repo is currently
private (`amd2g2zz/kunglao-agent`), the README badge already declares MIT and
the project is designed as a cloneable Claude Code skill — adding both files
now is harmless on a private repo and enables future open-sourcing without
retroactive license gaps.

## What Changes

- **`LICENSE`** (new): MIT License, copyright 2026, holder = repo owner. Matches
  the README badge already in place.

- **`AGENTS.md`** (new): Minimal collaborator guidance covering: repo overview
  (one paragraph), development workflow (SDD+TDD, one-issue/PR/branch/worktree),
  review gate (3-reviewer all-PASS via `scripts/review_gate.py`), and key
  constraints (VM-only for samples, no secrets, merge to dev not master).

## Non-goals

- Does NOT change any existing code, tests, or configuration.
- Does NOT modify the README or release-manifest.yaml.
- Does NOT add CI checks for LICENSE/AGENTS.md existence (separate issue if desired).
- Does NOT switch the repo from private to public.

## Capabilities

### Added Capabilities

- `license-file`: MIT LICENSE file present at repo root, enabling legal clarity
  and future distribution without retroactive gaps.
- `agents-guide`: AGENTS.md present at repo root with collaborator onboarding
  guidance (workflow, review gates, constraints).

## Impact

- `LICENSE`: new, ~21 lines (standard MIT text).
- `AGENTS.md`: new, ~60 lines (4 sections).
- Suite impact: 0 new tests (documentation-only change); 0 existing tests modified;
  no regressions.
- Related: #115 (references INDEX), #114 (gitignore audit) — no overlap.
