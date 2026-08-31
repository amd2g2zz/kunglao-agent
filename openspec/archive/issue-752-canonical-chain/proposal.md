# Hook teleport chain — durable-install canonical resolution + independent selfcheck + residual scavenger (#752)

## Why

Issue #752 (D-class field finding, 2026-08-27): the #269 canonical ruling
distinguished only two states — canonical install vs worktree — and never
modeled a LONG-LIVED CO-INSTALLED dev install. `hook_activation.
_canonical_hooks_dir` (scripts/hook_activation.py:474) resolves to
`~/.claude/skills/kunglao-agent/hooks` whenever the executing module is not
itself at that exact path. Consequences:

1. **Mis-routed wire-up (the teleport).** The long-term dev co-install
   `~/.claude/skills/kunglao-agent-dev` runs `--wire-up`; all 12 hook
   commands (`--project <root>` + script path) are written pointing back at
   the STALE 0.1.2 production install — the workspace silently executes
   old hook code while the operator believes the dev build is live.
2. **Self-certifying selfcheck.** `register_hooks` computes `hook_dir`
   once and hands the SAME variable to `selfcheck_registration` for the
   shape leg; "write whatever, verify whatever" always PASSes. A resolution
   bug is invisible to the only post-write check that exists.

## What Changes

- **D4 `_canonical_hooks_dir` grows a durable-install test**: any directory
  whose skill root's parent IS `~/.claude/skills/` is a durable install;
  when this module executes from one, THAT install's hooks dir wins. Only
  non-skills locations (repo checkouts, `.wt-*` worktrees — anything else)
  fall back to the canonical production install (`kunglao-agent`), keeping
  #269/#228 worktree semantics intact.
- **D4+ selfcheck shape-leg independence**: `selfcheck_registration` derives
  the expected hooks dir ITSELF via `_canonical_hooks_dir()` instead of
  trusting the caller-supplied `hook_dir`. The parameter stays accepted for
  API compatibility but no longer feeds the verdict. Mismatch fixtures now
  FAIL even when the caller claims the wrong dir matches. `register_hooks`
  stops passing its own variable through (writer and checker separated).
  `kunglao-init deploy_hooks` likewise resolves its write target from the
  same derivation (previously it hand-rolled its module location into both
  sides of the equation).
- **D5 residual-scavenger verifier**: new library
  `scripts/install_reference.py` (scanner/rewriter for
  `~/.claude/skills/<name>/` references across the two workspace carriers:
  `.claude/settings.json`, `CLAUDE.md`) + `hook_activation.
  verify_install_references()`. Mixed-state fixtures (commands where
  `--project` names the OLD install root and the script path the NEW one)
  prove: after re-wire, all 12 commands point at the executing install root
  and the old-install reference count is zero.
- **D6 upgrade end-step sweep**: `kunglao_upgrade.upgrade()` gains an
  install-reference scan AFTER `ensure_git_snapshot()` — every
  `~/.claude/skills/<name>/` reference in the workspace's settings.json and
  CLAUDE.md naming an install OTHER than the executing one is reported on
  stderr AND auto-repaired (rewire). The already-current fast path sweeps
  too (a mis-wired v0.1.3-stamped workspace is exactly the affected
  population and must not be skipped); dry-run prints the plan line and
  writes nothing. WARN-only posture, mirroring #739's snapshot face: the
  scan must never flip a migration exit code.

## Capabilities

###modify
- hook-wiring-canonical-resolution (new capability spec coverage under tests/test_canonical_chain_752.py)
