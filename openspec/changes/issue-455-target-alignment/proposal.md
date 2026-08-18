# Analysis-target alignment — intake step 0 (#455)

## Why

The init chain builds every layer as a deterministic function of the layer
above it — env from type, scaffold constraints from type — but the top of the
chain (WHAT is the analysis target) is never aligned with the user. Issue
#455 evidence:

1. `sniff_type()` guesses the type from the **first file in bins/ by sort
   order** (target = filesystem order side effect; multi-file ambiguity has
   no detection — an APK+PE mix is decided by alphabetical accident).
2. type is the **environment-contract selector**: windows/linux probe the
   VMware/VBox channel (9876/1337), android probes adb/frida/android_server.
   A mis-derived type (Android task sniffed as windows) probes the wrong
   channel set entirely and poisons scaffold constraints.
3. Containers are unmodeled: MSI (CFBF, `D0 CF 11 E0`) and APK (zip) are
   containers whose real analysis targets are **embedded objects**; MSI is
   not even in the sniff table.
4. Non-interactive runs silently accept the sniff (`except EOFError: pass`)
   — the same fake-interaction pattern #451 fixes elsewhere, in a second
   independent copy (D1 duplication).
5. Zero-argument invocation is undefined: bare argparse `error: the following
   arguments are required: workspace` (exit 2), no guidance, no next step.
6. CLAUDE.md consumes only type: `vm_detonation` / scope exclusions from
   task_spec never reach the workspace contract, so later sessions cannot
   read the user's original constraints.

## What Changes

- **New capability `target-alignment`**: init step 0 aligns the target/form/
  type triad with the user BEFORE any toolchain check or scaffold.
- **New shared module `scripts/decision_pending.py`** (#449/#451
  foundation): `PendingDecision` / `PendingDecisionList` dataclasses +
  JSON (de)serialization + answers-file loading. Any undecided intake item
  becomes a machine-readable pending list on stdout + exit
  `RC_PENDING_DECISIONS=8` (fail-closed, zero scaffold). The agent layer
  collects answers via Claude Code native AskUserQuestion and re-runs with
  `--resolve <answers.json>`.
- **`scripts/kunglao-init.py`**:
  - `workspace` becomes optional (`nargs="?"`); missing → pending
    `workspace` decision with the defined interaction order
    (path → target → type → requirements), no more bare argparse error.
  - New `--target <name>` (explicit analysis target) and
    `--resolve <answers.json>` (pending answers re-entry).
  - `sniff_type()` / `prompt_type()` / `resolve_type()` DELETED — the
    sniffed suggestion lives only in pending context, never auto-accepted;
    the two `input()` sites are gone.
  - Multi-file bins/ without an explicit target → pending `target`
    decision (sort-order arbitrariness eliminated). Single file → target is
    the unique file (no ambiguity to ask about).
  - Containers (MSI via CFBF magic, APK/zip via PK magic) are detected,
    their contents listed (zip namelist / minimal CFB directory-stream
    names), and a pending `target_object` decision is emitted — the
    container's type is NEVER guessed.
  - `write_claudemd()` renders a new `{{task_spec_section}}` from
    `ws/task_spec.yaml`: `vm_detonation`, `dynamic_re`, scope exclusions,
    depth land in the workspace contract. Absent file → section omitted;
    unparseable YAML → RC_ERROR (fail-closed, existing cleanup path).
- **`scripts/toolchain.py`**: explicit `CHECK_SETS` table (type → check-set
  names) with the android negative declaration — android NEVER runs
  `vm_reachable` / `remote_debugger` (the VMware/VBox 9876/1337 channel).
- **`scripts/toolchain_install.py`**: both `input()` sites removed
  (`prompt_yes_no` → non-interactive decline unless `--assume-yes`; IDA URL
  prompt → degrade + manual-registration guidance). The negotiation menu
  itself stays #451 scope.
- **Docs synced**: `skills/init/SKILL.md` (zero-arg interaction order,
  pending/--resolve mechanism, android ≠ VMware/VBox statement),
  `skills/kunglao-agent/SKILL.md` init-worker path,
  `agents/kunglao-init-worker.md` (type determination no longer "the ONLY
  human step" — user alignment is agent-mediated, native question channel).

## Capabilities

### New Capabilities

- `target-alignment`: intake step 0 — bins/ survey (magic/size per file),
  explicit target selection, container detection + contents listing,
  structured pending decisions, `--resolve` re-entry, fail-closed on any
  undecided item; CLAUDE.md task_spec rendering; android VM-channel
  negative declaration in toolchain.

## Impact

- `scripts/decision_pending.py`: NEW (~120 lines, stdlib only).
- `scripts/kunglao-init.py`: MODIFIED (intake step 0, CLI surface, RC 7,
  CLAUDE.md task_spec section; `input()` sites removed).
- `scripts/toolchain.py`: MODIFIED (CHECK_SETS declaration only — no probe
  logic change).
- `scripts/toolchain_install.py`: MODIFIED (input() removal only).
- `templates/CLAUDE.md.base.tmpl`: MODIFIED (one new `{{task_spec_section}}`
  slot after `{{type_section}}`).
- `skills/init/SKILL.md`, `skills/kunglao-agent/SKILL.md`,
  `agents/kunglao-init-worker.md`: MODIFIED (contract text).
- Tests: NEW `tests/test_decision_pending.py`,
  `tests/test_target_alignment.py`; MODIFIED legacy cases in
  `tests/test_init_typeaware.py` (sniff/confirm → pending/--resolve) and
  `tests/test_init_exit_codes.py` (RC matrix grows 7; argparse-usage case
  becomes the defined pending path).
- Behavior change (intended, per #455): non-interactive + no `--type` no
  longer silently accepts a sniff (exit 8 + pending list); zero-arg
  invocation no longer bare-argparse-fails (exit 8 + pending list); TTY
  runs no longer prompt on stdin at all.

## Non-goals

- #449's needs-first intake (primary_questions checklist) — #455 only
  defines the interaction ORDER slot and renders an existing task_spec.yaml.
- #451's negotiation menu / install-consent AskUserQuestion flow — #455
  only zeroes the `input()` sites and keeps the existing headless semantics.
- Container extraction/unpacking (MSI tables, APK DEX decode) — contents
  listing is names-level, sufficient to align the target.
- #450's env manifest — #455 adds the CHECK_SETS declaration in
  toolchain.py; the manifest itself is #450.
