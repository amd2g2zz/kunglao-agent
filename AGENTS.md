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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **kunglao-agent** (26762 symbols, 54105 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "master"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/kunglao-agent/context` | Codebase overview, check index freshness |
| `gitnexus://repo/kunglao-agent/clusters` | All functional areas |
| `gitnexus://repo/kunglao-agent/processes` | All execution flows |
| `gitnexus://repo/kunglao-agent/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
