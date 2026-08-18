---
name: kunglao-agent:init
description: >-
  Initialize a kunglao-agent analysis workspace. Scaffolds the directory
  skeleton, writes the workspace CLAUDE.md, mounts the sample, intakes
  task_spec.yaml, probes the toolchain, and activates hooks. One fresh
  workspace per sample engagement.
arguments: [workspace]
argument-hint: <workspace> [--type windows|linux|android] — no args → guided setup
---

# kunglao-agent:init — workspace initialization

Initializes a fresh kunglao-agent analysis workspace. Run this before any
analysis; a workspace that is not initialized is refused work.

## Flow

1. **Target alignment (intake step 0)** — run
   `python <SKILL_DIR>/scripts/kunglao-init.py <workspace>` FIRST; undecided
   intake items (workspace path -> analysis target -> project type) exit 8
   with a structured pending list on stdout (JSON). Collect the answers via
   the native question channel (AskUserQuestion), write
   `{decision_id: value}` JSON, re-run with `--resolve <answers.json>`.
   No silent defaults: multi-file `bins/` requires an explicit target,
   MSI/APK/ZIP containers list their contents and never get a guessed type
   (a magic-byte hint rides in the pending context only).
2. **Scaffold** — create the workspace directory skeleton and state files:
   `runs/`, `facts/_INDEX.md`, `claim-register.yaml`, `analysis_state.txt`,
   `task_spec.yaml` (from `templates/state/`).
3. **Write CLAUDE.md** — render the type-appropriate workspace contract from
   `templates/CLAUDE.md.base.tmpl`; the task_spec constraints (vm_detonation,
   scope exclusions, depth) are rendered INTO the contract.
4. **Mount the sample** — place the binary at `bins/<sha256>` and verify the
   hash matches `task_spec.yaml` / report.
5. **Task-spec intake** — confirm the primary questions / scope / constraints
   / depth / success_criteria. Ask the user HERE (before iteration 1), never
   later (the needs-first intake consumes the same pending/--resolve
   channel).
6. **Toolchain probe** — run per-project-type probes (Windows: Ghidra-or-IDA
   + VM; Linux: Ghidra-or-IDA + remote debugger; Android: ADB + rooted
   device + frida-server — Android NEVER probes VMware/VBox or the 9876/1337
   VM channel). Hard failures report root-cause guidance; the
   ask-then-install flow runs only under `--assume-yes` (stdin is not a user
   channel).
7. **Activate hooks** — register the hook set via
   `python <SKILL_DIR>/scripts/hook_activation.py <workspace> --wire-up`.

Repeat init on an existing workspace resumes idempotently from
`analysis_state.txt` + `claim-register.yaml` — never rebuild or overwrite.

The workspace path is a positional argument (omitted -> pending decision).
`--type` selects the project type: `windows` | `linux` | `android` (no
default — an undecided type pends, exit 8). `--target NAME` names the
analysis target under `bins/`; containers additionally resolve
`target_object`.

## No arguments

An empty `$ARGUMENTS` never starts scaffolding and never guesses the cwd:
print the guided prompt below and WAIT — one prompt, enumerated choices,
never guess, no bare argparse-style error dump.

- State that `<workspace>` is required and show the canonical invocation:
  `/kunglao-agent:init <workspace> [--type windows|linux|android]`.
- If the cwd already looks initialized (`claim-register.yaml` present), say
  so: point to `/kunglao-agent:analysis` for the loop, or note that re-run
  init resumes idempotently (never rebuild or overwrite).

## Missing `--type`

With a workspace but no `--type`, never silently default to `windows`:
route into the #455 intake type-alignment sequence — a magic-number sniff is
only a suggestion, the operator confirms the type before scaffolding, and
an unresolved ambiguity is surfaced as a decision_pending item (#455's
schema; not implemented here).

## Examples

- `/kunglao-agent:init ~/cases/synth-dropper --type windows`
- `/kunglao-agent:init /cases/android-samples/xyz --type android`
