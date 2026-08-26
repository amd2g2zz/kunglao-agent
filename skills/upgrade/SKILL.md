---
name: kunglao-agent:upgrade
description: >-
  Migrate a legacy workspace's framework scaffold forward to the current
  kunglao-agent release. Hooks rewire, template refresh, ALWAYS_ARMED hook
  state repair, toolchain manifest refresh, event vocabulary updates, and
  `#720` `.agent/` metadata seeding. **User data is never touched** — the
  seven user-data dirs (claims/ facts/ runs/ hypotheses/ notes/ evidence/
  oracle/) are sha256-normalized before/after; any byte difference aborts
  with `RC_IRON_RULE=4` and the pre-upgrade snapshot stays on disk for
  forensics. Use `--dry-run` to print the per-item plan without writing.
  Wraps `scripts/kunglao_upgrade.py` (#726) + the post-upgrade git
  snapshot path (#739, legacy no-git workspaces only). Use when an
  initialized workspace's version stamp trails the skill package and you
  want it brought current without losing analysis data.
arguments: [workspace]
argument-hint: <workspace> [--dry-run] — no args → guided workspace prompt
---

# kunglao-agent:upgrade — workspace framework-scaffold migration

Promotes a legacy workspace forward through the migration registry until its
stamp matches the current skill package. The seven user-data directories are
hashed (stamp-line-normalized) before/after; any byte difference aborts and
keeps the pre-upgrade snapshot on disk for forensics.

## No arguments

Print a guided workspace prompt — `cwd` is a candidate only with explicit
confirm, never guess, never a bare argparse error. The user must point at the
workspace to migrate. A workspace with no version stamp (`RC_UNKNOWN_ORIGIN=3`)
must be initialized first with `/kunglao-agent:init`.

## Exit-code contract (for skill UX mapping)

| RC | Meaning | Skill UX |
|---|---|---|
| `0` | migrated / already at target / dry-run plan printed | "done" |
| `3` | workspace has no version stamp | "refused, run init first" |
| `4` | iron-rule violation — user data drifted | "user-data drift detected, snapshot at `<workspace>/.kunglao-upgrade-pre-snapshot/` kept on disk; restore from snapshot" |
| `6` | dirty owned-repo (#753) — migration needs a clean rollback anchor | "refused: commit or stash first (commands on stderr), then re-run" |
| `7` | incomplete (#753) — migration applied but the finish sequence aborted; re-run upgrade | "warning: re-run /kunglao-agent:upgrade to complete" |

## CLI

```bash
uv run --project . kunglao upgrade <workspace>            # migrate
uv run --project . kunglao upgrade <workspace> --dry-run  # print plan only
```

JSON envelope (when `--json` lands in a future commit):

```json
{
  "status": "ok" | "dry-run" | "already-current" | "refused"
          | "refused-dirty" | "iron-rule-violation" | "incomplete",
  "rc": 0 | 3 | 4 | 6 | 7,
  "items": [{"name": "hooks_rewire", "action": "applied" | "noop" | "skipped", "detail": "..."}],
  "iron_rule_hash": {"pre": "...", "post": "..."},
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601"
}
```

## Iron rule

The seven user-data directories (`claims/`, `facts/`, `runs/`, `hypotheses/`,
`notes/`, `evidence/`, `oracle/`) are read-only during the migration. Carriers
whose framework stamp rides ON data files (`#536` comment form) have the stamp
line normalized away before hashing, so a sanctioned stamp refresh never
trips the rule.

## Out of scope

- Touching user data — abort + snapshot instead.
- Initializing an un-stamped workspace — refuse and direct to `/kunglao-agent:init`.
- Downgrading a workspace to an older stamp — `kunglao upgrade` is forward-only; downgrading is not in scope of #726.

## Related

- `#726` — declarative convergence upgrade (CLI shape + migration registry).
- `#739` — post-upgrade git snapshot for legacy no-git workspaces + explicit banner.
- `#456` — single-source subcommand UX design D4 (this skill is a render surface of `skills/subcommands.yaml`).