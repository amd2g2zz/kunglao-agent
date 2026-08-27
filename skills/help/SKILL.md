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
| `/kunglao-agent:init` | `<workspace> [--type windows\|linux\|android]` | initialize a workspace (scaffold + CLAUDE.md + sample mount + task_spec) | `/kunglao-agent:init ~/cases/synth-dropper --type windows` |
| `/kunglao-agent:analysis` | `<workspace>` | enter the convergence loop on an initialized workspace | `/kunglao-agent:analysis ~/cases/synth-dropper` |
| `/kunglao-agent:resume` | `<workspace>` | crash/reboot recovery: read-only breakpoint brief + re-arm advice | `/kunglao-agent:resume ~/cases/synth-dropper` |
| `/kunglao-agent:upgrade` | `<workspace> [--dry-run]` | forward-only workspace framework-scaffold migration — hooks rewire + template refresh, user data read-only; use when a stale-gate refusal points here | `/kunglao-agent:upgrade ~/cases/synth-dropper` |
| `/kunglao-agent:help` | none | print this usage list | `/kunglao-agent:help` |

## Exit codes

Refusal exit codes carry their own remediation — surface them to the operator
verbatim:

| rc | Commands | Meaning | Remediation |
|---|---|---|---|
| 0 | all | success — `check-stale`: status=current; `upgrade`: migrated / already-current / dry-run plan printed | none |
| 3 | `upgrade` | workspace has no version stamp | run `/kunglao-agent:init <workspace>` |
| 4 | `upgrade` | iron-rule violation — the seven user-data dirs drifted byte-wise; pre-upgrade snapshot left on disk | inspect the snapshot, restore externally, re-run |
| 5 | `analysis`, `resume`, `check-stale` | stale workspace — version stamp trails the skill package (or unparseable) | run `/kunglao-agent:upgrade <workspace>` first |
| 6 | `analysis` (entry gate), `upgrade` (dirty owned repo) | `analysis`: heartbeat verify failed; `upgrade`: owned repo dirty | `analysis`: run `/kunglao-agent:resume` for re-arm; `upgrade`: commit/stash then re-run |
| 7 | `upgrade` | incomplete — migration applied but finish sequence aborted | re-run `/kunglao-agent:upgrade <workspace>` |

## Examples

- `/kunglao-agent help` — print the usage list.
- `/kunglao-agent:help` — print the usage list (namespaced form).
