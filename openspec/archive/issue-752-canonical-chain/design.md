# Design — hook teleport chain (#752)

Context: issue #752. Proposal: `../proposal.md`.

## User ruling recorded

> "dev 安装是长期共存安装不是 worktree" — the dev co-install
> (`~/.claude/skills/kunglao-agent-dev`) is a LONG-LIVED DURABLE INSTALL,
> not a worktree. (2026-08-27)

The #269 two-state model (canonical vs worktree) under-classified reality.
Three states now:

| state | location class | teleport target |
|---|---|---|
| production | `~/.claude/skills/<any-name>/` | itself |
| dev co-install | `~/.claude/skills/<any-name>/` | itself |
| ephemeral | everything else (repo checkout, `.wt-*`, …) | `~/.claude/skills/kunglao-agent/` |

A single predicate separates them: `here.parent.parent ==
Path.home()/".claude"/"skills"`.

## D4 — `_canonical_hooks_dir` durable-install branch

```python
here = Path(__file__).resolve().parent.parent / "hooks"
skills_root = (Path.home() / ".claude" / "skills").resolve()
if here.parent.parent.resolve() == skills_root:
    return here                                  # durable: any skills/<name>
return skills_root / "kunglao-agent" / "hooks"   # ephemeral fallback (#269)
```

Both sides resolved so macOS `/var → /private/var` symlinks compare equal.
`Path.home()` (not expanduser/env) keeps the existing fake-home monkeypatch
seam working unchanged. Worktrees keep falling back — the #228 silent-death
class stays closed; the only behavior change is durable-installs-resolve-to-
themselves.

## D4+ — selfcheck shape leg derives independently

Before: `selfcheck_registration(..., hook_dir=...)` used the caller's value;
`register_hooks` passed the very variable it had just written with — the
self-certifying loop of issue #752. After:

- the shape expectation is recomputed inside the checker via
  `_canonical_hooks_dir()` (module location + HOME only);
- the `hook_dir` parameter remains ACCEPTED (external callers: none left in
  scripts after this change passes the writer's dir nowhere; kunglao-init's
  report shape keeps passing it historically) but is documented as ignored
  for the verdict;
- `register_hooks` no longer forwards its `hook_dir`;
- `kunglao-init.deploy_hooks` resolves BOTH its write path and its check
  path from `_canonical_hooks_dir()` — previously it stamped its own module
  location into entries AND validated against that same stamp (same disease,
  upstream of the register path).

Failure direction: a checker fed a lying `hook_dir` today returns PASS; the
fixture suite pins it returning FAIL with shape mismatches naming the true
executing install.

## D5 — residual scavenger

New pure library `scripts/install_reference.py` (no CLI entry point — the
consumers are hook_activation, kunglao_upgrade and the test face):

- `SKILL_REF_RE` — single pattern matching both prefix classes
  (`~/…` and absolute posix `…`) of `/.claude/skills/<name>/`;
- `find_refs(text)` / `ref_count(text, name)` — read-only scanning;
- `scan_workspace(ws, active_root)` — stale-reference inventory over the
  two carriers (`.claude/settings.json`, `CLAUDE.md`);
- `rewire_workspace(ws, active_root)` — TEXTUAL in-place repair preserving
  each reference's prefix style (`~` stays `~`), JSON-parse validation on
  settings.json before+after, byte-conservative otherwise (format/order of
  unrelated keys untouched).

Plus `hook_activation.verify_install_references(workspace)` — the D5
verifier (`ok` + per-carrier stale lists) used by tests and available to
operators.

Rejected alternative: rewriting settings.json by `json.dumps` round-trip —
normalizes formatting and risks churn beyond the stale refs; textual
replacement scoped to matched spans does not.

## D6 — upgrade end-step sweep

In `kunglao_upgrade.upgrade()`:

1. dry-run branch: prints the `install_reference_scan` plan item, writes
   nothing (existing `test_dry_run_writes_nothing` byte-invariance must
   keep holding);
2. migration success tail (after `ensure_git_snapshot`): applies the sweep;
3. already-current fast path: applies the sweep too — the affected real
   population (v0.1.3-stamped workspaces wired by a pre-fix dev install)
   would otherwism skip through the early return forever.

Sweep = stderr report naming each stale carrier/reference + automatic
rewire + `install_reference_scan` event via kunglao_log. Exit code NEVER
affected (WARN-only, same posture as #739 git snapshot). Iron-rule safe:
sweep touches only framework carriers, never the seven user-data dirs.

Active-root source: `hook_activation._canonical_hooks_dir().parent` — the
upgrade sweep inherits D4's durability ruling verbatim.

## Event taxonomy

`EMIT_ACTIONS += "install_reference_scan"` (additive; mirrors the #739
`git_snapshot_skipped` precedent).

## Rejected alternatives

- Hardcoding the dev-install name list (`kunglao-agent-dev` et al.) —
  name-enumeration decays; the parent-is-skills predicate has no members
  to maintain.
- Making the fallback `kunglao-agent` disappear entirely — breaks #269
  worktree semantics that remain correct.
- Sweeping arbitrary files (task specs, notes/) — user-data iron rule +
  blast radius; the two framework carriers are the complete reference
  surface init/wire-up writes.
