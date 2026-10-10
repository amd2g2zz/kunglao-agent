---
name: kunglao-agent:help
description: >-
  Print the kunglao-agent subcommand usage list: the commands, their
  arguments, and an example invocation for each. Also shown automatically
  when /kunglao-agent runs with no arguments.
arguments: []
argument-hint: "[no args] — print the subcommand usage list"
---

# kunglao-agent:help — usage list

Prints the kunglao-agent subcommand menu. Every entry shows the command, its
arguments, and an example.

## No arguments

`help` takes no arguments — zero args is its only form: print the subcommand
usage list (the table below) and stop. There is no missing-argument case.

## Usage

| Subcommand | Arguments | Purpose | Example |
|---|---|---|---|
| `/kunglao-agent` | `init <ws>` / `analysis <ws>` / `resume <ws>` / `upgrade <ws>` / `help` | command menu — with no args prints this list and waits | `/kunglao-agent` |
| `/kunglao-agent:init` | `<workspace> [--type windows\|linux\|android\|web\|macos] [--lane malware\|algorithm\|protocol\|web\|data\|app]` | initialize a workspace (scaffold + CLAUDE.md + lane-material mount + task_spec) | `/kunglao-agent:init ~/cases/synth-dropper --type windows` · `/kunglao-agent:init ~/cases/codec --lane algorithm --type linux` |
| `/kunglao-agent:analysis` | `<workspace>` | enter the convergence loop on an initialized workspace | `/kunglao-agent:analysis ~/cases/synth-dropper` |
| `/kunglao-agent:resume` | `<workspace>` | crash/reboot recovery: read-only breakpoint brief + re-arm advice | `/kunglao-agent:resume ~/cases/synth-dropper` |
| `/kunglao-agent:upgrade` | `<workspace> [--dry-run]` | forward-only workspace framework-scaffold migration — hooks rewire + template refresh, user data read-only; use when a stale-gate refusal points here | `/kunglao-agent:upgrade ~/cases/synth-dropper` |
| `/kunglao-agent:help` | none | print this usage list | `/kunglao-agent:help` |

## CLI

The slash commands above are the operator face. The same router is also
registered as the `kunglao` console script — `uv sync` in the repo root, then
`kunglao --help`. Loop-internal subcommands drive an in-flight analysis
session:

| CLI | Purpose | Slash face |
|---|---|---|
| `kunglao decide <workspace> [--json]` | convergence decision (M1) | driven inside `/kunglao-agent:analysis` |
| `kunglao tick <workspace>` | heartbeat tick chain (M5) | driven inside `/kunglao-agent:analysis` |
| `kunglao verify <workspace> <fact_id> [--json]` | M3 VERIFY (L1 mechanical + L2 redteam) | driven inside `/kunglao-agent:analysis` |
| `kunglao record <workspace> --event '<json>'` | M4 RECORD (ledger idempotent append) | driven inside `/kunglao-agent:analysis` |
| `kunglao health <workspace>` | convergence health (M5) | driven inside `/kunglao-agent:analysis` |
| `kunglao resume <workspace> [--json]` | crash/reboot recovery brief (read-only) | `/kunglao-agent:resume` |
| `kunglao check-stale <workspace> [--resolve]` | stale-workspace gate (rc 0/5) — run before analysis/resume on a possibly-stale workspace | guards `/kunglao-agent:analysis` |
| `kunglao upgrade <workspace> [--dry-run]` | workspace framework-scaffold migration | `/kunglao-agent:upgrade` |
| `kunglao analysis <workspace>` | analysis entry gate (rc 0 clear / 5 stale / 6 heartbeat verify failed) | `/kunglao-agent:analysis` |

Dedicated console scripts (standalone face, no subcommand needed):
`kunglao-init`, `kunglao-verify`, `kunglao-upgrade`, `heartbeat-tick`,
`convergence-check`.

## Exit codes

Refusal exit codes carry their own remediation — surface them to the operator
verbatim:

| rc | Commands | Meaning | Remediation |
|---|---|---|---|
| 0 | all | success — `check-stale`: status=current; `upgrade`: migrated / already-current / dry-run plan printed | none |
| 3 | `upgrade` | workspace has no version stamp | run `/kunglao-agent:init <workspace>` |
| 4 | `upgrade` | iron-rule violation — the seven user-data dirs drifted byte-wise; pre-upgrade snapshot left on disk | inspect the snapshot, restore externally, re-run |
| 5 | `analysis`, `resume`, `check-stale` | stale workspace — version stamp trails the skill package (or unparseable), or deployed framework copies drifted from the deployment manifest (`status=deploy-drift`) | run `/kunglao-agent:upgrade <workspace>` first |
| 6 | `analysis` (entry gate), `upgrade` (dirty owned repo) | `analysis`: heartbeat verify failed; `upgrade`: owned repo dirty | `analysis`: run `/kunglao-agent:resume` for re-arm; `upgrade`: commit/stash then re-run |
| 7 | `upgrade` | incomplete — migration applied but finish sequence aborted | re-run `/kunglao-agent:upgrade <workspace>` |

## Examples

- `/kunglao-agent help` — print the usage list.
- `/kunglao-agent:help` — print the usage list (namespaced form).
