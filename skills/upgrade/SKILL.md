---
name: kunglao-agent:upgrade
description: >-
  Migrate a legacy workspace's framework scaffold forward to the current
  kunglao-agent release. Hooks rewire, template refresh, ALWAYS_ARMED hook
  state repair, toolchain manifest refresh, event vocabulary updates, and
  `.agent/` metadata seeding. **User data is never touched** — the
  seven user-data dirs (claims/ facts/ runs/ hypotheses/ notes/ evidence/
  oracle/) are sha256-normalized before/after; any byte difference aborts
  with `RC_IRON_RULE=4` and the pre-upgrade snapshot stays on disk for
  forensics. Use `--dry-run` to print the per-item plan without writing.
  Wraps `scripts/kunglao_upgrade.py` + the post-upgrade git
  snapshot path (, legacy no-git workspaces only). Use when an
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
| `6` | dirty owned-repo — migration needs a clean rollback anchor | "refused: commit or stash first (commands on stderr), then re-run" |
| `7` | incomplete — migration applied but the finish sequence aborted; re-run upgrade | "warning: re-run /kunglao-agent:upgrade to complete" |

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
whose framework stamp rides ON data files (comment form) have the stamp
line normalized away before hashing, so a sanctioned stamp refresh never
trips the rule.

## Out of scope

- Touching user data — abort + snapshot instead.
- Initializing an un-stamped workspace — refuse and direct to `/kunglao-agent:init`.
- Downgrading a workspace to an older stamp — `kunglao upgrade` is forward-only; downgrading is not in scope.

## Related

- Declarative convergence upgrade (CLI shape + migration registry).
- Post-upgrade git snapshot for legacy no-git workspaces + explicit banner.
- Single-source subcommand UX design D4 (this skill is a render surface of `skills/subcommands.yaml`).

## Deploy-surface items (#755, migration entry 0.1.4)

The `0.1.4` migration completes the deployment surface Wave-1 could not
touch. Every item is idempotent and WARN-only (a degraded item never flips
the exit code):

| Item | Behavior |
|------|----------|
| `agents_refresh` | ws `.claude/agents/*.md` re-copied byte-exact from the executing install when md5s differ (semantics) |
| `claudemd_merge` | collect-and-merge: frame rebuilt from the CURRENT template; task_spec constraint block + out-of-frame sections stay byte-exact; unplaceable legacy bodies are skipped untouched |
| `mcp_refresh` | missing `.mcp.json` -> init-parity scaffold; existing files are never clobbered |
| `env_manifest_refresh` | missing `env-manifest.yaml` ledger backfilled via channel resolution (defaulted-local WARNs); existing ledgers get only the `kunglao_version` bump |
| `toolchain_manifest` | code-reality face: `runs/.init-report.json skill_version` refreshed; absence reports toward re-init, never fabricates state |
| `uv_sync` | `uv sync --locked --project <install root>`, timeout-bounded; all failures are WARN faces |
| `skill_staleness` | detect-only install lag report (below) |

### Install staleness (`skill_install_staleness`)

Read-only comparison of the executing install's HEAD against its remote
ref (upstream when set, else `origin/<branch>` — no network fetch). The
stderr trail carries the verdict:

```
[event] name=skill_install_staleness status=warn install=... behind=N
[event] name=skill_install_staleness status=ok   install=... behind=0
[event] name=skill_install_staleness status=skip (not a git clone)
```

`behind=N` means the running scaffold itself is older than upstream:
update the skill package (`git -C <install>` pull / plugin update) and
re-run `/kunglao-agent:upgrade` afterwards. Upgrade never self-updates.
