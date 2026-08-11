# Proposal — code-owned completion gate (Stop hook + task-oracle.yaml) (#55)

## Why

This is the structural fix for the premature-termination class of failure (#54
is the detector; #55 is the gate that makes the call). The 2026-08-11 session
(a2b5e25c, C-META-1/2) is the cleanest specimen — and the oracle for this
change's acceptance:

- Task verbatim: 「重检测当前分析是否存在矛盾、遗漏和gap。如果存在就需要继续全面分析」
- At close: **6 items still open** (G4, G5, G6, #10, #11, #12), **zero user
  sign-off**.
- The agent declared "Substantive task complete ... this run is done" by
  self-inventing a "备注级（记录即可）" tier for G4-G6 and marking #10-#12
  "deferred" — neither tier exists in the user's instruction.

Root cause (three independent sources agree, see issue #55): termination
judgment is pure LLM discretion. There is no CODE-OWNED gate that asks "did the
agent actually close what the user asked?" before allowing the session to end.
#54 detects the fingerprints AFTER the fact; #44 re-anchors state per turn;
neither BLOCKS the termination. The missing layer is a **declaration-time gate
that reads a pre-registered oracle of the user's actual goal + the open-items
ledger and refuses to let the session end until the oracle is satisfied.**

This mirrors the arXiv 2608.04066 property the issue cites: a pre-registered
prediction is admitted only when code matches it against observation. Here the
"prediction" is the task-oracle (registered at task start, verbatim user
instruction); the "observation" is the open-items ledger at close; the "match"
is the gate's exit code.

## What Changes

- **`scripts/completion_gate.py`** (new, pure stdlib + PyYAML): the gate logic.
  - `judge(oracle, declaration_text=None) -> (exit_code, reason)`: pure
    function. `oracle` is the parsed `task-oracle.yaml` dict (or None). Returns
    one of 4 exit codes (see below) + a human-readable reason naming the
    unclosed items / unsigned defers. Reads ONLY the oracle (+ optional
    declaration text for #54 integration); no workspace state, no network.
  - `main()` CLI: `python scripts/completion_gate.py <oracle-file>`
    `[--declaration-file <path>]` → prints `{exit_code, reason, ...}` JSON;
    process exit = the exit_code.
  - Exit codes (machine-readable for the Stop hook):
    - `0` = PASS (task_text present, all open_items resolved, every defer
      user-signed).
    - `1` = incomplete items remaining (open_items not closed and not
      user-deferred).
    - `2` = unsigned defer (a deferral record's `authorized_by` is not a
      recognized user — agent self-signing rejected; the #54 self-defer).
    - `3` = task_text missing (oracle is None, or task_text empty/missing —
      refuse self-produced anchor; the #54 F1 self-anchoring structural fix).
- **`hooks/completion_gate.py`** (new, thin Stop-hook shim): reads the Stop
  payload from stdin, resolves the workspace, applies strict activation
  (mirror `hooks/state_anchor.py`), finds `task-oracle.yaml`, calls
  `scripts/completion_gate.py::judge`, and emits a Claude Code Stop-hook
  `{"decision": "block", "reason": "..."}` when the gate fails. Pass-through
  (exit 0, empty stdout) when not activated OR no oracle file OR
  `stop_hook_active` (anti-loop).
- **`task-oracle.yaml` schema** (documented in design.md D2; a sibling artifact
  to `claim-register.yaml` / `task_spec.yaml`, NOT a replacement):
  - `task_text`: the user's instruction **verbatim** (the anchor — NO LLM
    summary; the direct fix for #54's self-anchoring).
  - `acceptance: []`: falsifiable 'done' criteria (documentary; the hard gate
    is open_items).
  - `open_items: [{id, desc, closed_by, closed_at}]`: the items that must be
    resolved. `closed_by` set ⇒ resolved by completion.
  - `deferrals: [{item, authorized_by, reason, at}]`: items the user explicitly
    dropped. `authorized_by` MUST be a user (agent self-authorization ⇒ exit 2).
- **`scripts/wire_up_settings.py`** (extend): add a `Stop` section registering
  `hooks/completion_gate.py` (idempotent, mirror the PostToolUse `_ensure`
  pattern; the real `~/.claude/settings.json` is NEVER touched by tests — they
  monkeypatch `Path.home`).
- **`scripts/hook_activation.py`** (extend): add `completion_gate` to
  `ALL_HOOKS` so strict activation recognizes it.
- **`tests/test_completion_gate.py`** (new, RED first): 4 exit-path tests
  (0/1/2/3); the 2026-08-11 replay regression (acceptance 2); all-closed PASS
  (acceptance 3); user-signed defer PASS + agent-signed exit 2 (acceptance 4);
  task_text-missing exit 3; the 全面/comprehensive extended-check behavior; the
  wire-up Stop registration + idempotence + ALL_HOOKS membership.

## Non-goals

- NOT a runtime / per-iteration check — that is convergence_check.py / #43.
  #55 fires at TERMINATION (Stop hook), once.
- NOT a detector of declaration text — that is #54. #55 CONSUMES #54's
  `detect()` as an OPTIONAL reason-enhancement when a declaration is supplied
  (design.md D4); the gate's core logic is oracle-driven and deterministic.
- NOT a state anchor — that is #44 (per-turn, injects context). #55 anchors the
  COMPLETION JUDGMENT (declaration-time, blocks).
- NOT semantic verification of `acceptance[]` criteria — the gate cannot
  mechanically verify a falsifiable criterion is met. It treats open_items as
  the mechanical proxy (each item closed or user-deferred). `acceptance` is
  documentary and echoed in the reason.

## Capabilities

### Added Capabilities

- `completion-gate`: declaration-time, code-owned completion judgment. Reads a
  pre-registered `task-oracle.yaml` and refuses session termination (Stop hook)
  until every open_item is resolved and every defer carries a user signature.

## Impact

- `scripts/completion_gate.py`: new, ~220 lines (judge + CLI + #54 integration).
- `hooks/completion_gate.py`: new, ~90 lines (Stop shim, mirrors state_anchor).
- `tests/test_completion_gate.py`: new, ~260 lines (~14 tests).
- `scripts/wire_up_settings.py`: +1 Stop section (~15 lines).
- `scripts/hook_activation.py`: +1 token in `ALL_HOOKS`.
- Suite impact (baseline at 4192703): `scripts/` 226 passed → 226 unchanged
  (gate logic is tests/-only; wire_up_settings has no scripts/ test); `tests/`
  309 passed + 1 skipped + 6 pre-existing failures → +N new passes, the 6
  pre-existing failures unchanged.
- Related: #54 (detector — consumed as optional reason-enhancement, D4),
  #44 (state_anchor — mirrored for activation + workspace resolve + FAIL_OPEN),
  #43 (runtime drift — cross-ref, not duplicate).
