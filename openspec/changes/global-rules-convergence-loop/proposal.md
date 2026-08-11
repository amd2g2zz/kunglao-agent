## Why

Audit (2026-08-11): kunglao-agent's **#1 invariant — "every round's first tool = `convergence_check.py`"** — lives only in `SKILL.md`. SKILL.md loads only on explicit skill invocation and is lost after `/compact`. The convergence-loop rules (decision table / 5 behaviors / false-completion trap) never made it into the always-on channel.

- `~/.claude/rules/common/*.md` is the always-on global rules channel (injected every session, survives `/compact`) — `maker-checker.md` / `numeric-fidelity.md` already live there.
- SKILL.md itself states the intended pattern: "behavioral rules live in `~/.claude/rules/common/` so they apply even when this skill is not loaded" — but the convergence-loop rules were never actually moved there.
- Claude Code memory mechanics: CLAUDE.md walks **up** from cwd; the skill dir is not in any workspace's cwd ancestor chain → skill-dir CLAUDE.md does not load. `~/.claude/CLAUDE.md` (user-level) is 0 bytes/empty.

Consequence: any session running a kunglao workspace **without** invoking the skill (or after `/compact`) has no convergence-loop discipline — exactly the "空转 / 傻等 / 不收敛" failure family this skill exists to prevent.

## What Changes

- **`rules/kunglao-convergence-loop.md`** (CREATE): a distilled (<150 lines) always-on version of the convergence-loop invariants, in the style of the existing `~/.claude/rules/common/*.md` rules. Content per the 9-point outline: identity (orchestrator, not analyst) / #1 invariant (first tool of every round = convergence_check) / convergence decision table (DISPATCH / DISPATCH_VERIFIER / SATURATED / BLOCKED / CONVERGED) / 5 behaviors one line each / maker-checker split (worker=maker, orchestrator=checker, no self-stamp — pointer to the global maker-checker rule) / tool boundary (never call ghidra/x64dbg/frida directly → delegate workers) / hard prohibitions (no mid-iteration 反问, no cascade abort, no declare-done with OPEN claims) / file map (claim-register.yaml, facts/_INDEX.md, .convergence_ledger.jsonl, scripts/ paths) / pointers to SKILL.md + references/ for the full contract.
- **`tests/test_convergence_rules_file.py`** (CREATE): TDD contract tests — file exists; <150 lines; required invariant markers present; no long verbatim blocks copied from `references/convergence-loop.md` (no 80+ char shared substring beyond defined vocabulary).
- **Unchanged**: `references/convergence-loop.md` (detailed on-demand reference stays), `SKILL.md` (still the full contract, loaded on invocation).
- **Not in scope**: deployment to `~/.claude/rules/common/` (separate setup-script issue); no change to any scripts/hooks.

## Capabilities

### Added Capabilities

- `convergence-loop-rules`: the distilled always-on convergence-loop rule file `rules/kunglao-convergence-loop.md` — the same invariants as SKILL.md's convergence section, in a <150-line form deployable to the global rules channel. Detailed behavior stays in `references/convergence-loop.md`; the distilled file points to it.

## Impact

- `rules/kunglao-convergence-loop.md`: +1 file (~110 lines).
- `tests/test_convergence_rules_file.py`: +1 test file (~11 tests).
- Behavior: sessions that never invoke the skill (or post-`/compact`) still carry the convergence-loop invariants once deployed; deployment itself is a later setup-script issue.
- No production code touched; no scripts/hooks modified.
- Related: precedes #44 (state_anchor hook) — if the always-on rule reliably re-grounds the orchestrator each round, #44 can shrink or defer.
