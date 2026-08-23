## ADDED Requirements

### Requirement: kunglao-init SHALL fail closed with a structured pending-decision list when the analysis target or type is undecided

When the analysis target (bins/ file) or the project type is not explicitly determined (via `--target` / `--type`, a `--resolve` answers file, or a persisted `project_type=` in analysis_state.txt), `scripts/kunglao-init.py` SHALL print a machine-parseable pending-decision JSON document to stdout and exit `RC_PENDING_DECISIONS=8` WITHOUT writing any scaffold file. A magic-byte sniff result SHALL appear only as a suggestion inside the pending decision's context and SHALL NEVER be adopted as the type, regardless of TTY presence. The old interactive confirm path (`input()`) SHALL NOT exist.

#### Scenario: sniffed type is never silently accepted
- **GIVEN** bins/ holds one PE file and init runs non-interactively without `--type` or `--resolve`
- **WHEN** init exits
- **THEN** the exit code is 7, stdout is a parseable pending JSON containing a `type` decision whose context mentions the suggested type, and analysis_state.txt / claim-register.yaml do not exist

#### Scenario: resolve re-entry completes init
- **GIVEN** the pending exit above produced an answers file `{"type": "windows"}`
- **WHEN** init re-runs with `--resolve <answers.json>`
- **THEN** init proceeds (with `--skip-toolchain`) to exit 0 and writes `project_type=windows`

### Requirement: kunglao-init SHALL require an explicit analysis target when bins/ holds more than one file

When bins/ contains more than one file and no target is provided, init SHALL emit a pending `target` decision listing every file (name, size, magic kind) as options with NO default, and SHALL NOT select a file by sort order. When bins/ holds exactly one file, that unique file SHALL be the target without asking. The aligned target SHALL drive the seed-claim sample identity and the CLAUDE.md sample path.

#### Scenario: multi-file ambiguity asks, never sorts
- **GIVEN** bins/ holds `z_first.exe` and `a_second.exe` and init runs without `--target`
- **WHEN** init exits
- **THEN** the exit code is 7 and the pending `target` decision's options contain both filenames with no default

#### Scenario: resolved target wins over sort order
- **GIVEN** bins/ as above and an answers file selecting `a_second.exe`
- **WHEN** init runs with `--resolve` (and a type decision answered, `--skip-toolchain`)
- **THEN** exit 0 and the C-001 seed claim / CLAUDE.md reference `a_second.exe`

### Requirement: kunglao-init SHALL detect MSI and APK as containers, list their contents, and never guess a container's type

A bins/ file with the CFBF magic (`D0 CF 11 E0`) SHALL be classified `msi`; PK-zip files SHALL be classified `apk` (classes.dex in head) or `zip`. When the aligned target is a container, init SHALL emit a pending `target_object` decision whose options are the container contents (zip namelist / CFB directory stream names) plus the `__container__` sentinel, and the `type` decision SHALL carry no auto-derived value. The resolved `target_object` SHALL be persisted to analysis_state.txt as `analysis_target_object=<name>`.

#### Scenario: MSI is a container with a listed inventory
- **GIVEN** bins/ holds one minimal CFB fixture with directory streams `Alpha` and `Beta`
- **WHEN** init runs with `--type windows` (type already decided)
- **THEN** exit 8, the pending list contains a `target_object` decision whose options include `Alpha`, `Beta`, and `__container__`, and the file's kind is reported as `msi`

#### Scenario: APK contents listed, type not guessed
- **GIVEN** bins/ holds one real zip APK fixture containing `classes.dex` and `lib/arm64-v8a/libx.so`
- **WHEN** init runs without type/target_object decisions
- **THEN** the pending list contains both a `target_object` decision (options include both entries and `__container__`) and a `type` decision with no default

### Requirement: the android environment contract SHALL never include VMware/VBox channel checks

`scripts/toolchain.py` SHALL declare per-type check-set names (`CHECK_SETS`) with an explicit negative declaration for android: the android check set SHALL NOT include `vm_reachable` or `remote_debugger` (the VMware/VBox VM channel, ports 9876/1337 to a VM host). An android toolchain report SHALL contain no such items and SHALL make zero `_tcp_connect` calls (device-side probes go through `adb forward`, a different contract). Windows and linux check sets SHALL still contain `vm_reachable`.

#### Scenario: android report contains no VM-channel items
- **GIVEN** a workspace with type android and the android probes stubbed
- **WHEN** `toolchain.check(ws, "android")` runs with `_tcp_connect` replaced by a counter
- **THEN** the report item names include neither `vm_reachable` nor `remote_debugger`, the counter is 0, and `CHECK_SETS["android"]` is disjoint from the declared NEVER set

### Requirement: zero-argument invocation SHALL follow the defined interaction order instead of a bare argparse error

`kunglao-init.py` invoked with no workspace argument SHALL exit 8 with a pending list whose first decision is `workspace`, and whose guidance states the intake order path → target → type → requirements (the requirements slot is #449's needs-first intake). Genuinely malformed flags (e.g. `--type banana`) SHALL keep exiting RC_ERROR=1.

#### Scenario: no arguments produces a pending workspace decision
- **GIVEN** `kunglao-init.py` runs with zero arguments
- **WHEN** it exits
- **THEN** the exit code is 7 (not argparse's 2, not RC_ERROR), and stdout's first pending decision has `decision_id == "workspace"`

### Requirement: scripts SHALL contain zero interactive input() call sites

No `scripts/*.py` module SHALL contain an `input(...)` or `builtins.input(...)` call. All user decisions flow through the pending-list + `--resolve` mechanism (agent collects via native AskUserQuestion and re-runs). `toolchain_install.py` consent prompts SHALL decline (never read stdin) unless `--assume-yes` is set.

#### Scenario: AST gate over scripts
- **GIVEN** every `.py` file under scripts/
- **WHEN** the AST is scanned for input call nodes
- **THEN** zero call sites are found

### Requirement: the rendered CLAUDE.md SHALL carry task_spec constraints

`templates/CLAUDE.md.base.tmpl` SHALL carry a `{{task_spec_section}}` slot, and init SHALL render it from `ws/task_spec.yaml` when present: at minimum the `vm_detonation` constraint and the `scope.out` exclusion entries appear in the generated workspace contract. An absent task_spec.yaml omits the section; an unparseable one fails closed with RC_ERROR via the existing cleanup path.

#### Scenario: constraints land in the contract
- **GIVEN** a workspace whose task_spec.yaml sets `constraints.vm_detonation: forbidden` and `scope.out: [bitcoin_clipper]`
- **WHEN** init completes (`--skip-toolchain`)
- **THEN** CLAUDE.md contains `vm_detonation: forbidden` and `bitcoin_clipper`

#### Scenario: corrupt task_spec fails closed
- **GIVEN** task_spec.yaml content is invalid YAML
- **WHEN** init runs
- **THEN** init exits RC_ERROR=1 with no `[initialized]` marker

### Requirement: the #449 intake chain slot SHALL be exercisable end-to-end through target alignment

A single chain SHALL complete: zero-arg pending (workspace) → resolve → target+type pending → resolve → init with a task_spec present → CLAUDE.md carrying task_spec constraints → android toolchain report with zero VM-channel checks. This is the rehearsal slot #449's needs-first intake plugs into (its primary_questions checklist content is out of scope here).

#### Scenario: full chain once
- **GIVEN** a fresh directory, an APK-in-zip fixture, and answer files for each pending round
- **WHEN** the chain above is executed
- **THEN** every round exits as specified and the final workspace carries the aligned target, task_spec constraints in CLAUDE.md, and an android report with zero vm_reachable items
