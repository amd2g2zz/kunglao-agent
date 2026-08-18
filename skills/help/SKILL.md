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
| `/kunglao-agent` | `init <ws>` / `analysis <ws>` / `help` | command menu — with no args prints this list and waits | `/kunglao-agent` |
| `/kunglao-agent:init` | `<workspace> [--type windows\|linux\|android]` | initialize a workspace (scaffold + CLAUDE.md + sample mount + task_spec) | `/kunglao-agent:init ~/cases/synth-dropper --type windows` |
| `/kunglao-agent:analysis` | `<workspace>` | enter the convergence loop on an initialized workspace | `/kunglao-agent:analysis ~/cases/synth-dropper` |
| `/kunglao-agent:help` | none | print this usage list | `/kunglao-agent:help` |

## Examples

- `/kunglao-agent help` — print the usage list.
- `/kunglao-agent:help` — print the usage list (namespaced form).
