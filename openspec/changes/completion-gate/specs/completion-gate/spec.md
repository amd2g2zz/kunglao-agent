## ADDED Requirements

### Requirement: judge SHALL return one of 4 exit codes from the task-oracle

`scripts/completion_gate.py` SHALL expose `judge(oracle: dict | None,
declaration_text: str | None = None) -> tuple[int, str]`. The returned int
SHALL be exactly one of `0` (PASS: task_text present, zero unresolved
open_items, zero unsigned defers), `1` (incomplete items remaining), `2`
(unsigned defer — a deferral's `authorized_by` is not a recognized user), or
`3` (task_text missing — oracle is None or `task_text` is empty/missing). The
returned string SHALL be a human-readable reason naming the failing items (for
exit 1), the unsigned defer records (for exit 2), or the missing-anchor
condition (for exit 3); for exit 0 it SHALL be a PASS summary. `judge` SHALL
read ONLY the `oracle` dict (+ the optional `declaration_text` for fingerprint
folding); it SHALL NOT read workspace state and SHALL NOT touch the network.

The oracle dict schema SHALL be: `task_text` (str, the user instruction
verbatim), `acceptance` (list of str, optional, documentary), `open_items`
(list of `{id, desc, closed_by?, closed_at?}`), `deferrals` (list of
`{item, authorized_by, reason?, at?, source?}`). An `open_item` is RESOLVED
iff its `closed_by` is a non-empty string OR its `id` appears in `deferrals`
with a user-authorized `authorized_by`.

#### Scenario: PASS — all items closed
- **GIVEN** an oracle with `task_text: "fix the 3 bugs"`, `open_items: [{id: "A", closed_by: "commit 1"}, {id: "B", closed_by: "commit 2"}, {id: "C", closed_by: "commit 3"}]`, `deferrals: []`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `0` and the reason contains `PASS`

#### Scenario: exit 1 — incomplete items remaining (the 2026-08-11 replay)
- **GIVEN** an oracle with `task_text: "重检测当前分析是否存在矛盾、遗漏和gap。如果存在就需要继续全面分析"` and `open_items` = the 6 items `G4, G5, G6, #10, #11, #12` each with empty `closed_by`, and `deferrals: []`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `1` and the reason names all 6 unresolved item ids (`G4`, `G5`, `G6`, `#10`, `#11`, `#12`)

#### Scenario: exit 2 — agent self-signed defer rejected
- **GIVEN** an oracle with `task_text: "do X"`, one `open_item: {id: "A"}` (empty `closed_by`), and `deferrals: [{item: "A", authorized_by: "agent", reason: "out of scope"}]`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `2` and the reason names the unsigned defer for item `A`

#### Scenario: exit 3 — task_text missing refuses self-anchor
- **GIVEN** an oracle dict `{}` (no `task_text` key)
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `3` and the reason states the anchor is missing

#### Scenario: exit 3 — None oracle refuses self-anchor
- **GIVEN** `oracle` is `None`
- **WHEN** `judge(None)` is called
- **THEN** the exit code is `3`

### Requirement: user-vs-agent signature SHALL be decided by a mechanical deny-list, not LLM judgment

A deferral SHALL be user-authorized iff (a) `authorized_by` is present and
non-empty after `strip()`, AND (b) `authorized_by.casefold()` is NOT in the
`AGENT_IDENTIFIERS` deny-list (`agent`, `claude`, `ai`, `self`, `assistant`,
`llm`, `kong`, `kunglao`, `worker`, `verifier`, `orchestrator`, `auto`,
`system`, `bot`, `me`), AND (c) if a `source` field is present it equals
exactly `"user"`. Any deferral failing this SHALL trigger exit 2. The literal
CJK user marker `用户` SHALL be accepted (it is not in the deny-list).

#### Scenario: user-signed defer resolves the item (PASS)
- **GIVEN** an oracle with `task_text: "do X"`, `open_items: [{id: "A"}]` (empty `closed_by`), `deferrals: [{item: "A", authorized_by: "用户", reason: "user said A 不用查"}]`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `0` (item A is resolved by the user-signed defer)

#### Scenario: agent self-signed defer triggers exit 2
- **GIVEN** the same oracle but `authorized_by: "agent"`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `2`

#### Scenario: empty authorized_by triggers exit 2
- **GIVEN** the same oracle but `authorized_by: ""`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `2`

#### Scenario: source: agent overrides a user-like authorized_by
- **GIVEN** a defer `{item: "A", authorized_by: "hr", source: "agent"}`
- **WHEN** `judge(oracle_with_that_defer)` is called
- **THEN** the exit code is `2`

### Requirement: judge SHALL prefer exit 3, then exit 2, then exit 1, then exit 0

`judge` SHALL evaluate in precedence order and return on the first hit: (1)
None oracle or empty `task_text` ⇒ exit 3; (2) any unsigned defer ⇒ exit 2;
(3) any unresolved open_item ⇒ exit 1; (4) otherwise exit 0. When BOTH an
unsigned defer and unresolved items exist, exit 2 SHALL win (the unsigned defer
is the more diagnostic signal).

#### Scenario: unsigned defer wins over unresolved items
- **GIVEN** an oracle with `task_text: "do X"`, two open_items `A` (unsigned defer) and `B` (no defer, no close), where A's defer has `authorized_by: "claude"`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `2` (the unsigned defer for A is reported, not the unresolved B)

#### Scenario: valid task_text with all resolved passes despite many items
- **GIVEN** an oracle with `task_text: "do X"`, 6 open_items all with non-empty `closed_by`, no deferrals
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `0`

### Requirement: judge SHALL apply a zero-tolerance policy and a reason clause when task_text carries a comprehensiveness keyword

`judge` SHALL detect a comprehensiveness keyword in `task_text` (any of
`全面`, `comprehensive`, `all`, `every`, `所有`, `逐项`, `exhaustive`, matched
case-insensitively for ascii). When the keyword is present AND exit 1 fires,
the reason SHALL contain a clause naming the comprehensiveness mandate (the
literal `全面` or `comprehensive`). When the keyword is present, a defer whose
`reason` contains a self-invented tier term (`备注级`, `记录即可`, `deferred`,
`low-priority`, `nice-to-have`, `out-of-scope`) SHALL be treated as
self-invented and trigger exit 2 even if `authorized_by` is user-like. A
genuine user defer whose reason contains NO tier term (e.g. `不用查`) SHALL
still pass.

#### Scenario: 2026-08-11 replay reason carries the comprehensiveness clause
- **GIVEN** the 2026-08-11 regression oracle (task_text contains `全面分析`, 6 unsigned open_items)
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `1` AND the reason contains `全面` or `comprehensive`

#### Scenario: comprehensiveness keyword rejects a tier-language defer
- **GIVEN** an oracle with `task_text: "全面分析 everything"`, `open_items: [{id: "G4"}]`, `deferrals: [{item: "G4", authorized_by: "用户", reason: "G4 备注级"}]`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `2` (the 备注级 tier term marks the defer self-invented despite the user-like authorized_by)

#### Scenario: comprehensiveness keyword does not reject a genuine user defer
- **GIVEN** an oracle with `task_text: "全面分析"`, `open_items: [{id: "G5"}]`, `deferrals: [{item: "G5", authorized_by: "用户", reason: "G5 不用查"}]`
- **WHEN** `judge(oracle)` is called
- **THEN** the exit code is `0` (不用查 is a user decision, not a tier term)

### Requirement: the CLI SHALL read an oracle YAML and emit a JSON verdict with the exit code

`scripts/completion_gate.py::main()` SHALL accept a positional `<oracle-file>`
(a UTF-8 YAML `task-oracle.yaml`) and optional `--declaration-file <path>`
(UTF-8 text of the closing declaration for #54 fingerprint folding), parse the
oracle with `yaml.safe_load`, call `judge`, and print a JSON object
(`ensure_ascii=False`, `indent=2`) carrying at least `exit_code` and `reason`
(plus the resolved-item counts). The process exit code SHALL equal `exit_code`.

#### Scenario: CLI regression oracle exits 1
- **GIVEN** a UTF-8 YAML file containing the 2026-08-11 regression oracle
- **WHEN** `python scripts/completion_gate.py <oracle-file>` runs
- **THEN** stdout is valid JSON with `exit_code` equal to `1` and the process exit code is `1`

#### Scenario: CLI all-closed oracle exits 0
- **GIVEN** a UTF-8 YAML file where all open_items have non-empty `closed_by`
- **WHEN** `python scripts/completion_gate.py <oracle-file>` runs
- **THEN** `exit_code` is `0` and the process exit code is `0`

#### Scenario: CLI missing oracle file exits 3
- **GIVEN** a path that does not exist
- **WHEN** `python scripts/completion_gate.py <missing>` runs
- **THEN** `exit_code` is `3` and a clear message goes to stderr

### Requirement: the Stop hook shim SHALL activation-gate, FAIL_OPEN, and emit a block decision

`hooks/completion_gate.py` SHALL read a JSON payload from stdin (the Claude
Code Stop event), resolve the workspace (first candidate with a
`task-oracle.yaml`), check strict activation (`completion_gate` in active_hooks
via `hook_activation.is_active_strict`, not expired), find the oracle, call
`judge`, and when `judge` returns non-zero emit
`{"decision": "block", "reason": "<judge reason>"}` on stdout. It SHALL
pass-through (exit 0, empty stdout) when ANY of: kunglao not activated, no
oracle file in the workspace, `stop_hook_active` is true in the payload, or any
exception (FAIL_OPEN). It SHALL NEVER touch the network and NEVER write state.

#### Scenario: not-activated session passes through
- **GIVEN** a Stop payload with `cwd` pointing at a workspace with no `.hook_state.json`
- **WHEN** the shim runs
- **THEN** stdout is empty and the exit code is `0`

#### Scenario: activated + unsatisfied oracle blocks termination
- **GIVEN** a Stop payload with `cwd` at an activated workspace whose `task-oracle.yaml` judges exit 1, and `stop_hook_active: false`
- **WHEN** the shim runs
- **THEN** stdout is JSON with `"decision": "block"` and a `reason` naming the unclosed items, and the exit code is non-zero

#### Scenario: stop_hook_active passes through (anti-loop)
- **GIVEN** the same workspace but `stop_hook_active: true` in the payload
- **WHEN** the shim runs
- **THEN** stdout is empty and the exit code is `0`

#### Scenario: malformed oracle (empty task_text) blocks with exit 3
- **GIVEN** an activated workspace whose `task-oracle.yaml` has empty `task_text`, `stop_hook_active: false`
- **WHEN** the shim runs
- **THEN** stdout is JSON with `"decision": "block"` and a reason about the missing anchor

### Requirement: wire_up_settings SHALL register the Stop hook idempotently and completion_gate SHALL be in ALL_HOOKS

`scripts/wire_up_settings.py::wire_up_settings()` SHALL register
`hooks/completion_gate.py` under a `Stop` key in the settings.json `hooks`
object (Stop hooks carry no matcher; dedupe by command basename). Registration
SHALL be idempotent (re-running produces a fixed point, one entry). The
`~/.claude/settings.json` file SHALL be touched ONLY through `Path.home()`,
which tests monkeypatch to a temp dir — the real user settings are never
modified by tests. `scripts/hook_activation.py::ALL_HOOKS` SHALL contain the
token `completion_gate`.

#### Scenario: wire_up registers completion_gate under Stop
- **GIVEN** `Path.home()` monkeypatched to a temp dir
- **WHEN** `wire_up_settings()` runs
- **THEN** the written `settings.json` has a `hooks.Stop` list whose command basename is `completion_gate.py`

#### Scenario: wire_up Stop registration is idempotent
- **GIVEN** `Path.home()` monkeypatched to a temp dir
- **WHEN** `wire_up_settings()` runs twice
- **THEN** `hooks.Stop` contains exactly one entry whose command basename is `completion_gate.py`

#### Scenario: ALL_HOOKS contains completion_gate
- **WHEN** `hook_activation.ALL_HOOKS` is read
- **THEN** the set contains `completion_gate`

### Requirement: the module SHALL cross-reference #44, #54, and #43 as complementary layers

The module docstring of `scripts/completion_gate.py` SHALL name `#44`
(per-turn state re-anchor — mirrored for activation + workspace resolve),
`#54` (declaration detector — consumed as optional reason-enhancement), and
`#43` (runtime drift — cross-ref), and state that #55 is the GATE that BLOCKS
termination, complementary to all three.

#### Scenario: module docstring names #43, #44, #54
- **WHEN** the module docstring of `completion_gate` is read
- **THEN** it contains the literal `#43`, the literal `#44`, and the literal `#54`
