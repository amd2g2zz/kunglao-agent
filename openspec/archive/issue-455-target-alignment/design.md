# Design — target-alignment (#455)

## Design Decisions

### D1. Pending decisions = stdout JSON + RC_PENDING_DECISIONS=8, fail-closed

Every undecided intake item (workspace / target / target_object / type)
makes init print a `PendingDecisionList` JSON document to **stdout** (the
machine channel — stderr keeps human guidance) and exit
`RC_PENDING_DECISIONS=8`, before any scaffold write. Zero scaffold is
structural: the pending exits happen in `run()` before `scaffold(ws)` and
before the toolchain gate's ask branch.

The sniffed suggestion is NEVER accepted, not even on a TTY. The old
`except EOFError: pass  # Non-interactive: accept sniff` and the
`Confirm? [Y/n]` prompt are deleted (`sniff_type`/`prompt_type`/
`resolve_type` removed). Acceptance paths are exactly: explicit `--type` /
`--target`, a persisted `project_type=` in analysis_state.txt, or a
`--resolve` answers file. `suggested_type` (from the target's magic bytes)
appears only inside the pending decision's `context` — information for the
agent's question, never a default the script adopts.

RC numbering: `RC_PENDING_DECISIONS = 8` continues the documented ladder (7 was taken by #445 RC_HOOK_WIRING on dev)
(0-6 in use; #414's argparse normalization of usage errors to RC_ERROR=1
is untouched for genuinely malformed flags).

### D2. Target selection matrix (multi-file must ask; single file is unique)

`survey_bins(ws)` lists every file under bins/ (name, size, magic kind) —
it reads bins/ ONLY (never bin/, the #411 boundary is preserved). Then:

| Situation | Behavior |
|---|---|
| bins/ empty | existing RC_NO_SAMPLE=5 gate |
| >1 file, no explicit/answered target | pending `target` decision — options = all names, NO default (sort-order arbitrariness eliminated) |
| exactly 1 file, no target | target = the unique file (uniqueness is determinism, not arbitrariness; asking would be interaction for its own sake) |
| target given (flag or answer) but not in bins/ | RC_ERROR=1 (fail-closed, explicit message) |

`detect_sample(ws)` becomes `detect_sample(ws, target)`: C-001/C-003 seed
claims and the CLAUDE.md `sample_path` follow the **aligned** target, not
`sorted()[0]`.

### D3. Containers are detected, contents listed, type never guessed

`file_kind(path)` maps magic → `pe | elf | apk | zip | msi | unknown`:
PK\x03\x04 (+classes.dex in head → `apk`, else `zip`), `\x7fELF`, `MZ`,
`D0 CF 11 E0 A1 B1 1A E1` (CFBF → `msi`). `is_container(kind)` is true for
`apk | zip | msi`.

When the aligned target is a container, init emits a pending
`target_object` decision whose options are the container contents plus the
sentinel `__container__` (analyze the container as a whole):
- zip/apk: `zipfile.ZipFile.namelist()` (stdlib), truncated to a bounded
  list in the options (full list kept in `context.contents_full`).
- msi: minimal CFB directory-stream parsing (header sector size, first
  directory sector from the DIFAT, 128-byte entries, UTF-16LE names) —
  names-level listing only, no OLE stream payloads, no MSI table decode.

The container's `type` decision carries NO default and no auto-derived
value (checkbox: "不直接猜 type"). An embedded-objects summary (e.g.
`classes.dex`, `lib/*.so`) rides in `context` so the agent can ask an
informed question. The resolved `target_object` is persisted to
analysis_state.txt as `analysis_target_object=<name>` (container layering
survives the init run; container-level filename stays the sample identity).

### D4. Shared pending schema — `scripts/decision_pending.py` (#449/#451 foundation)

Pure stdlib dataclasses + JSON round-trip + answers loading, no kunglao-init
coupling:

```
PendingDecision(decision_id, question, kind: "choice"|"value",
                options, default, context: mapping)
PendingDecisionList(schema_version="1", flow, workspace, guidance,
                    decisions, resume)
    .to_json()          # deterministic, agent-parseable document
answers_from_json(text) # {decision_id: value}; ValueError on non-object
load_answers(path)      # file wrapper; ValueError on missing/unparseable
```

How #449 consumes it: the needs-first intake appends its own decisions
(`primary_questions`, `scope`, `depth`, ...) with `flow="kunglao-init"`,
same `--resolve` re-entry — #449's checklist then reads a uniform list.
How #451 consumes it: install-consent / menu items become
`kind="choice"` decisions (options yes/no or tool menu) replacing the
remaining headless-refuse paths; `RC_PENDING_DECISIONS` is reused verbatim.
kunglao-init consumes exactly four decision ids in #455 — `workspace`,
`target`, `target_object`, `type` — extra ids in an answers file are
ignored (forward compatibility, no rejections when #449 lands).

Precedence when answers and flags coexist: explicit flag > `--resolve`
answer > persisted state > pending (the pending list is the floor, never a
source of silent values).

### D5. android ≠ VMware/VBox made explicit in toolchain.py

`CHECK_SETS: dict[str, frozenset[str]]` declares each type's check-item
names beside the existing per-type checker functions, plus
`NEVER_CHECKS = {"android": frozenset({"vm_reachable", "remote_debugger"})}`
— the code-level statement that the android contract never touches the
VMware/VBox channel (ports 9876/1337 to a VM host). `check()` keeps its
existing dict dispatch (no probe logic changes). Regression tests assert:
(1) an android report's item names ⊆ CHECK_SETS["android"] and disjoint
from NEVER_CHECKS["android"]; (2) `toolchain._tcp_connect` is called ZERO
times on the android path (monkeypatched counter — this is the mechanical
9876/1337 statement; android's frida/android_server probes go through
`adb forward` to the device, which is a different contract by design);
(3) windows/linux reports DO contain `vm_reachable` (the declaration does
not silently shrink other types). The deep env manifest remains #450.

### D6. CLAUDE.md renders task_spec constraints

`templates/CLAUDE.md.base.tmpl` gains one slot, `{{task_spec_section}}`,
immediately after `{{type_section}}`. `write_claudemd` reads
`ws/task_spec.yaml` via `yaml.safe_load`:

- file absent → section rendered as "" (init legitimately precedes the
  needs-first intake; #449 fills task_spec later and re-render is its
  concern) — the params dict ALWAYS carries the key, so
  `render_strict`'s leftover detection still guards the template;
- keys present → a `## Task constraints (task_spec)` block with
  vm_detonation, dynamic_re, scope exclusions (`scope.out`), depth;
- yaml.YAMLError → wrapped as TemplateRenderError → existing RC_ERROR
  cleanup path (fail-closed: a corrupt contract file never renders a
  silently-partial CLAUDE.md).

### D7. Zero-argument invocation = defined pending sequence

`workspace` becomes `nargs="?"`. Missing workspace + no resolved answer →
pending list whose FIRST decision is `workspace` (kind=value), with the
interaction order spelled out in `guidance`: **path → target → type →
requirements** (the last step points at #449's needs-first intake; #455
defines the slot, not #449's content). argparse usage errors for genuinely
malformed flags (bad `--type` value) keep the #414 normalization to
RC_ERROR=1.

### D8. input() sites zeroed (scripts/ scope)

- kunglao-init.py: `prompt_type` / `resolve_type` deleted (D1).
- toolchain_install.py: `prompt_yes_no` returns False unless
  `assume_yes` (never reads stdin); the IDA-MCP-URL branch drops its
  input() — non-assume-yes degrades with the manual
  `claude mcp add --transport http ida-pro-vm <url>` guidance (same
  outcome as the old empty-input path).
- kunglao-init.run's `sys.stdin.isatty()` ask-branch is removed — the
  headless semantics (refuse exit 4 with per-item fixes) become the only
  non-`--assume-yes` path. The consent MENU as an AskUserQuestion flow is
  #451's change; #455 only removes the fake-interaction channel.
- Mechanical gate: an AST-based test walks every `scripts/*.py` and fails
  on any `input(...)` / `builtins.input(...)` call — the pattern cannot
  return silently (D1 recurrence guard).

## Rejected Alternatives

- **R1: keep `input()` behind `isatty()` checks** — stdin is not a user
  channel in Claude Code and isatty is untrustworthy (issue evidence 4;
  #451's C3/C4). Rejected outright.
- **R2: non-interactive + no --type → bare exit 1** — fails checkbox 1
  (structured pending list required) and leaves the agent no machine-
  readable way to continue the flow.
- **R3: single-file workspaces also require an explicit target** — no
  ambiguity exists; asking would be interaction for its own sake. Uniqueness
  is deterministic (D2).
- **R4: write the pending list to a file in the workspace** — step 0 may
  not even have a workspace yet (zero-arg call); stdout JSON + exit code is
  the machine channel with no filesystem precondition.
- **R5: full container parsing (OLE payloads, MSI tables, DEX decode)** —
  exceeds "identify as container and list contents"; names-level listing
  is sufficient to align the target with the user. Deep unpacking belongs
  to the analysis phases.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/decision_pending.py` | NEW | shared pending schema (#449/#451 foundation) |
| `scripts/kunglao-init.py` | MOD | intake step 0, --target/--resolve, RC 7, task_spec render, input() removal |
| `scripts/toolchain.py` | MOD | CHECK_SETS + NEVER_CHECKS declaration (no probe change) |
| `scripts/toolchain_install.py` | MOD | input() removal (headless semantics preserved) |
| `templates/CLAUDE.md.base.tmpl` | MOD | `{{task_spec_section}}` slot |
| `skills/init/SKILL.md` | MOD | zero-arg order, pending/--resolve, android ≠ VMware/VBox |
| `skills/kunglao-agent/SKILL.md` | MOD | init-worker path paragraph |
| `agents/kunglao-init-worker.md` | MOD | type determination contract text |
| `tests/test_decision_pending.py` | NEW | schema round-trip + answers loading |
| `tests/test_target_alignment.py` | NEW | checkbox matrix: pending/resolve/multi-file/containers/android/zero-arg/AST gate/E2E chain |
| `tests/test_init_typeaware.py` | MOD | legacy sniff/confirm cases migrated to --resolve |
| `tests/test_init_exit_codes.py` | MOD | RC matrix grows RC_PENDING_DECISIONS=8 |

## Out of scope

- #449 needs-first intake content (primary_questions checklist, env
  contract derivation) — only the order slot + task_spec rendering land here.
- #451 negotiation menu / install-consent AskUserQuestion.
- #450 env manifest (CHECK_SETS is a declaration inside toolchain.py, not a
  manifest file).
- Container payload extraction; DEX/SO analysis.
