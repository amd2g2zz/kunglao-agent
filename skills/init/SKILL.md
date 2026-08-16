---
name: kunglao-agent:init
description: >-
  Initialize a kunglao-agent analysis workspace. Scaffolds the directory
  skeleton, writes the workspace CLAUDE.md, mounts the sample, intakes
  task_spec.yaml, probes the toolchain, and activates hooks. One fresh
  workspace per sample engagement.
arguments: [workspace]
argument-hint: <workspace> [--type windows|linux|android]
---

# kunglao-agent:init — workspace initialization

Initializes a fresh kunglao-agent analysis workspace. Run this before any
analysis; a workspace that is not initialized is refused work.

## Flow

1. **Scaffold** — create the workspace directory skeleton and state files:
   `runs/`, `facts/_INDEX.md`, `claim-register.yaml`, `analysis_state.txt`,
   `task_spec.yaml` (from `templates/state/`).
2. **Write CLAUDE.md** — render the type-appropriate workspace contract from
   `templates/CLAUDE.md.base.tmpl`.
3. **Mount the sample** — place the binary at `bins/<sha256>` and verify the
   hash matches `task_spec.yaml` / report.
4. **Task-spec intake** — confirm the primary questions / scope / constraints
   / depth / success_criteria. Ask the user HERE (before iteration 1), never
   later.
5. **Toolchain probe** — run per-project-type probes (Windows: Ghidra-or-IDA
   + VM; Linux: Ghidra-or-IDA + remote debugger; Android: ADB + rooted
   device + frida-server). Hard failures report root-cause guidance.
6. **Activate hooks** — register the hook set via
   `python <SKILL_DIR>/scripts/hook_activation.py <workspace> --wire-up`.

Repeat init on an existing workspace resumes idempotently from
`analysis_state.txt` + `claim-register.yaml` — never rebuild or overwrite.

The workspace path is the only positional argument. `--type` selects the
project type: `windows` (default) | `linux` | `android`.

## Examples

- `/kunglao-agent:init ~/cases/synth-dropper --type windows`
- `/kunglao-agent:init /cases/android-samples/xyz --type android`
