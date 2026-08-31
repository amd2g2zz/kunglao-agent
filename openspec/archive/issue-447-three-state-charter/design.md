# Design — Agent 行为三态宪法 (issue #447)

## Architecture

```
                 docs/agent_3state_charter.md  (SINGLE SOURCE)
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  ask_for_direction_gate   dispatch_gate.py        kunglao-init.py
  (orchestrator output)    (dispatch prompt)       (intake decisions)
        │                       │                       │
   Type A/B/C/D/S          Type S only              Type D (pending)
   rc=1 reject              rc=2 hard pause          rc=8 pending
   rc=2 hard pause          (BEFORE worker runs)     (zero scaffold)
```

## 检测时机 — why TWO executors for Type S

`ask_for_direction_gate` sees the orchestrator's **printed** output —
it catches the signal AFTER the orchestrator has decided. If the
irreversible action is inside a worker dispatch prompt, the gate only
fires if the orchestrator happens to print it first. Unreliable.

`hooks/dispatch_gate.py` (PreToolUse on Agent) sees the dispatch prompt
**itself** — catching irreversible actions BEFORE the worker runs. This is
the load-bearing enforcement; the text gate is defense-in-depth.

## Priority order in check()

```
def check(workspace, text):
    1. Type S   → HARD_PAUSE (rc=2)   # irreversible — always
    2. Type D   → HARD_PAUSE (rc=2)   # ambiguity — always
    3. Type A/B + Type C signal → OK (rc=0)  # convergence sign-off
    4. Type A/B violations → REJECT (rc=1)   # ask-back
    5. 3+ redirects → HARD_PAUSE (rc=2)      # legacy ladder
```

## In dispatch_gate.py main()

```
1. parse (v0/v1)         → unparseable: WARN (rc=0, visible)
2. must-stop check       → HARD_PAUSE (rc=2)  ← BEFORE blocked-claim check
3. blocked-claim check   → inject guidance (rc=0)
4. else                  → silent (rc=0)
```

Must-stop runs BEFORE the blocked-claim check: an irreversible action in a
healthy claim's dispatch is just as irreversible.

## Language policy

Patterns are English-only (user directive: mixing languages in regex is
brittle). Docstring states the policy; non-English triggers must be
translated by the prompt layer, not the gate.

## Files

| File | Change |
|---|---|
| `docs/agent_3state_charter.md` | NEW — the charter |
| `rules/kunglao-convergence-loop.md` | #1 rewritten to reference the charter |
| `scripts/ask_for_direction_gate.py` | + TYPE_D/TYPE_S patterns, find_must_ask/stop_signals, check() priority |
| `scripts/kunglao-init.py` | comment block references the charter (Type D at intake) |
| `hooks/dispatch_gate.py` | + _DISPATCH_MUST_STOP_PATTERNS, _must_stop_dispatch, _warn_must_stop |
| `tests/test_ask_for_direction_charter.py` | NEW — 18 tests (A/B/C/D/S + precedence + legacy) |
| `tests/test_dispatch_protocol.py` | + TestDispatchMustStop (3 tests) |

## Risks

- Regex-based detection is inherently incomplete (user's earlier note);
  the charter doc + gates are the *contract*, future work may add
  structured signals (e.g. v1 dispatch JSON gains a `reversible: false`
  field so detection is declared, not inferred)
- English-only patterns: a Chinese-language orchestrator output escapes
  Type D/S until the prompt layer translates — documented limitation
- must-stop patterns could false-positive on analysis descriptions of
  malware that *contains* `git push --force` strings — narrowed by
  requiring imperative-verb phrasing

## Future (not this PR)

- v1 dispatch protocol `reversible` field (declared vs inferred detection)
- workspace-level identity-ambiguity check (count VMs at dispatch time)
