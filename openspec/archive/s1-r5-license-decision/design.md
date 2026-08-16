# Design — LICENSE + AGENTS.md (#116)

## Decision: MIT License + Minimal AGENTS.md

### Rationale

1. **Repo is private but designed for distribution** — README instructs `git clone`
   into `~/.claude/skills/`. The badge already says MIT. Adding the actual file
   eliminates the inconsistency.

2. **MIT is the safe default** — permissive, widely understood, no copyleft
   complications for a tool that wraps other tools (Claude Code, Ghidra, pefile,
   capstone). Matches the existing README badge.

3. **AGENTS.md is required by skill-repo manual** — provides collaborator guidance
   without cluttering README with internal dev process details.

4. **No downsides on private repo** — both files are inert on a private repo and
   become immediately useful if the repo is ever made public.

## File Specifications

### LICENSE

- Standard MIT License text (Expat variant, as used by OSI).
- Copyright year: 2026.
- Copyright holder: repo owner (amd2g2zz).

### AGENTS.md

Four sections, ~60 lines total:

1. **Overview** — 1-paragraph summary from README (convergence-driven RE orchestrator).
2. **Development workflow** — SDD (OpenSpec) + TDD (pytest), one issue / PR / branch /
   worktree, merge to `dev`, release to `master`.
3. **Review gate** — `scripts/review_gate.py` runs 3 reviewers (style, security,
   correctness); all must PASS for merge eligibility.
4. **Key constraints** — VM-only for sample execution, no secrets in tree, merge to
   `dev` not `master`, maker-checker separation (worker != verifier).

## Non-goals (reiterated)

- No code changes.
- No CI changes.
- No README changes.
- No release-manifest changes (LICENSE and AGENTS.md are not shipped agent assets).
