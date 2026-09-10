---
name: kunglao-agent:init
description: >-
  Initialize a kunglao-agent analysis workspace. Intakes task_spec.yaml
  FIRST (needs-first: the environment derives from the task), aligns the
  analysis target and project type, scaffolds the directory skeleton,
  writes the workspace CLAUDE.md, mounts the sample, probes the toolchain,
  and deploys hooks. One fresh workspace per sample engagement.
arguments: [workspace]
argument-hint: <workspace> [--type windows|linux|android|web|macos] — no args → guided setup
---

# kunglao-agent:init — workspace initialization

Initializes a fresh kunglao-agent analysis workspace. Run this before any
analysis; a workspace that is not initialized is refused work.

## Flow

0. **Task-spec intake (needs-first)** — confirm the primary
   questions / scope / constraints / depth / success_criteria BEFORE any
   environment or scaffold decision: the environment is a function of the
   task (env = f(task_spec)), never of the project-type template alone.
   Ask the user HERE (before iteration 1), never later — the same
   native-question round may also carry the workspace/target/type
   answers. The answers land in `<workspace>/task_spec.yaml` (from
   `templates/state/`) ahead of the step-5 toolchain probe, which derives
   its requirement tiers from it: `constraints.dynamic_re: forbidden`
   (static-only) downgrades the windows/linux VM checks from HARD to
   WARN; every field the task_spec does not answer stays HARD
   (conservative default — an absent task_spec is byte-identical to a
   VM-required workspace).

   **Oracle anchors (REQUIRED — asked by the script)** — init itself
   asks the three answers that steer the whole loop through the
   structured pending-decision channel: while any anchor is blank in
   `task_spec.yaml`, the init run prints a pending document (stdout,
   exit 8) with decision ids `goal_verbatim` / `success_criterion` /
   `verification_method` (the last is a choice over
   `reproduction | replay-evidence | static | manual`). Collect the
   answers via the native question channel (AskUserQuestion — never
   script stdin), write `{decision_id: value}` JSON, and re-run with
   `--resolve <answers.json>`: the re-entry fills only the missing
   fields and pre-fills `task-oracle.yaml` `task_text` from the
   verbatim goal. Init never completes with blank anchors — there is no
   exit-0-with-blank-anchors run to repair later. Your asking role is
   to RELAY the machine's questions well, not to decide whether to ask:
   1. `goal_verbatim` — the user's goal, restated VERBATIM (never
      paraphrased; the verbatim form is what the completion oracle
      judges).
   2. `success_criterion` — what counts as done, stated as a checkable
      end-state (the completion anchor).
   3. `verification_method` — how the result is verified, one of:
      `reproduction` / `replay-evidence` (either arms the
      controlled-comparison oracle: byte-matched pairs become admission
      and verdict requirements for every primary question) / `static` /
      `manual`.
   While any anchor is blank the analysis entry also refuses
   (`kunglao analysis` exit 7) — the second line of defense; never
   guess or default an anchor. For help turning a folk ask ("我要纯算")
   into these answers, point the user at the README section **"How to
   state the task"** (`README.md`, anchor `#how-to-state-the-task`).
1. **Target alignment ** — run
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
   `task_spec.yaml` (from `templates/state/`; already filled by step 0 —
   scaffold never clobbers it), `goal-operationalization.yaml` (from
   `templates/state/`; the Phase-0 goal operationalization skeleton — the
   orchestrator pre-registers it mechanically before the first dispatch;
   the verbatim task itself stays in `task-oracle.yaml`, #128).
3. **Write CLAUDE.md** — render the type-appropriate workspace contract from
   `templates/CLAUDE.md.base.tmpl`; the task_spec constraints (vm_detonation,
   scope exclusions, depth) are rendered INTO the contract.
4. **Mount the sample** — place the binary at `bins/<sha256>` and verify the
   hash matches `task_spec.yaml` / report.
5. **Toolchain probe** — run per-project-type probes (Windows: Ghidra-or-IDA
   + VM; Linux: Ghidra-or-IDA + remote debugger; Android: ADB + rooted
   device + frida-server — Android NEVER probes VMware/VBox or the 9876/1337
   VM channel). The probe consumes `task_spec.yaml` when present (:
   static-only → the VM checks are WARN, not HARD); missing/unreadable
   fields stay HARD. Hard failures report root-cause guidance; the
   ask-then-install flow runs only under `--assume-yes` (stdin is not a user
   channel).
6. **Deploy the engineering environment** — init itself deploys
   hooks (creates `<ws>/.claude/settings.json` when absent, then registers
   + self-checks; `--no-hooks` is the only skip), copies the core 3
   subagents to `<ws>/.claude/agents/`, records the MCP supply state in
   `env-manifest.yaml` (missing registrations become MANUAL entries with
   their register command — init never runs `claude mcp add` itself), and
   writes the deployment ledger. Deployment is WORKSPACE-SCOPED (#25 D4):
   the hooks live in `<ws>/.claude/settings.json` and fire only for
   sessions opened inside `<ws>` — a Claude session started elsewhere
   (another project, the repo checkout, home) loads none of them, so
   kunglao's gates are silently absent there; `hooks/session_start.py`
   prints an explicit NOT-active notice when it runs without a kunglao
   workspace. `--builtin-skills a,b` opts into auxiliary skill
   deployment (kunglao's BUILT-IN bundled skills only — globally-installed
   skills are a different, future surface). Activation (which hooks FIRE)
   stays a separate orchestrator act:
   `python <SKILL_DIR>/scripts/hook_activation.py <workspace> --wire-up`
   remains the canonical re-registration/repair entry .

Repeat init on an existing workspace resumes idempotently from
`analysis_state.txt` + `claim-register.yaml` — never rebuild or overwrite.

The workspace path is a positional argument (omitted -> pending decision).
`--type` selects the project type: `windows` | `linux` | `android` | `web` (no
default — an undecided type pends, exit 8). `--target NAME` names the
analysis target under `bins/`; containers additionally resolve
`target_object`. `--no-hooks` skips hook deployment (the only legal skip);
`--builtin-skills a,b` deploys named built-in auxiliary skills (opt-in,
default none; kunglao-bundled names only, #25 D2).

## No arguments

An empty `$ARGUMENTS` never starts scaffolding and never guesses the cwd:
print the guided prompt below and WAIT — one prompt, enumerated choices,
never guess, no bare argparse-style error dump.

- State that `<workspace>` is required and show the canonical invocation:
  `/kunglao-agent:init <workspace> [--type windows|linux|android|web|macos]`.
- If the cwd already looks initialized (`claim-register.yaml` present), say
  so: point to `/kunglao-agent:analysis` for the loop, or note that re-run
  init resumes idempotently (never rebuild or overwrite).

## Missing `--type`

With a workspace but no `--type`, never silently default to `windows`:
route into the intake type-alignment sequence — a magic-number sniff is
only a suggestion, the operator confirms the type before scaffolding, and
an unresolved ambiguity is surfaced as a decision_pending item
(schema; not implemented here).

## Examples

- `/kunglao-agent:init ~/cases/synth-dropper --type windows`
- `/kunglao-agent:init /cases/android-samples/xyz --type android`
