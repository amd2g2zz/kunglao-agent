# AGENTS.md — kunglao-agent collaborator guide

## Overview

kunglao-agent is a convergence-driven reverse-engineering orchestrator built on
Claude Code (skills + agents + hooks). It autonomously takes a malware sample to
a byte-proven, independently-verified fact base with a non-lossy evidence chain.
The orchestrator never decompiles or emulates itself — it dispatches specialist
worker agents (ghidra-light, floss-filter, pefile-signature, go-symbols,
kunglao-worker) and an adversarial verifier (kunglao-redteam), enforcing
maker-checker separation at every claim.

## Development workflow

**SDD (OpenSpec) + TDD (pytest)**, one-issue-one-PR-one-branch-one-worktree:

```bash
git worktree add .worktrees/<name> -b <name> dev
cd .worktrees/<name>
npx openspec new change <name>            # scaffold proposal + design + tasks
# RED: write failing test
# GREEN: minimal implementation
# REFACTOR: clean up
python -m pytest -q                       # must pass (baseline in release receipt)
npx openspec validate <name>               # must exit 0
gh pr create --base dev                   # squash-merge to dev, delete branch
```

- Merge target is **`dev`**, never `master` (master = released revision).
- Every change has an OpenSpec proposal under `openspec/changes/<name>/`;
  delivered changes are archived to `openspec/archive/<name>/` (#355).
- The release manifest (`release-manifest.yaml`) is the source of truth for
  shipped assets; adding a file without declaring it fails CI.
- `uv sync --locked` restores the pinned environment (`pyproject.toml` +
  `uv.lock`).

## Review gate

Before merge, all PRs must pass the 1-reviewer gate enforced by
`scripts/review_gate.py`:

- **1 independent subagent reviewer** must produce a `PASS` file for the
  exact staged diff (was 3 reviewers before the 2026-08-14 user decision).
- Reviewer identities are restricted to known prefixes (t4-/t5-/t6-/kunglao-/
  r1-/r2-/r3-/reviewer-).
- The orchestrator mints a signed gate token after validating evidence
  (>=1 distinct reviewer, diff sha256 match).
- A pre-commit hook (`review_gate.py check`) blocks commits without a valid
  gate token for the branch. The single gate source is the tracked template
  `.claude/git-hooks/pre-commit`, installed by
  `python scripts/kunglao-init.py <workspace> --install-git-hooks` (stamps the
  installing user's key path into `.git/hooks/pre-commit` at install time —
  never copy the template by hand: an unstamped copy fail-closes every
  commit; the legacy 3-review-file gate under `.claude/hooks/` is retired).

## Key constraints

1. **VM-only for sample execution** — samples are never run on the host. Dynamic
   analysis (Frida, x64dbg) goes through the VM channel via `vmr-shell`. The
   `block_malware_exec` hook enforces this; violations are blocked.

2. **No secrets in the tree** — API keys, tokens, and credentials are excluded
   via `.gitignore`. `VT_API_KEY` and similar are environment-only.

3. **Merge to `dev`, not `master`** — `master` is the released revision (CI
   runs `release_receipt.py --check` + tests on every push). All feature work
   targets `dev` via PR.

4. **Maker-checker separation** — workers (makers) gather evidence and write
   facts; verifiers (checkers) forward-derive from raw evidence independently.
   A worker that self-stamps `PROVEN` is a defect. The orchestrator enforces
   different agent contexts for maker and checker.

5. **Ground truth hierarchy** — raw artifact > local tool > sandbox > CTI. CTI
   is a falsifiable claim, never truth (workspace CLAUDE.md V3).
