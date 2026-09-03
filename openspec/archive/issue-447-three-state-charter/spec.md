# Spec — Agent 行为三态宪法 (issue #447)

## Requirement: the charter SHALL be the single source

`docs/agent_3state_charter.md` SHALL be the only document defining when
the agent asks the user. No other file MAY state "ask the user" /
"don't ask the user" as an unconditional rule — they MUST reference the
charter.

## Requirement: three states

The charter SHALL define exactly three states plus one negative:

| State | Meaning | Enforcement |
|---|---|---|
| allowed | proceed autonomously, record reasoning | default |
| must-ask | HARD_PAUSE until user confirms | rc=2 |
| must-stop | HARD_PAUSE + block irreversible action | rc=2 |
| NEGATIVE | ask-back violation (Type A/B) | rc=1 reject |

## Requirement: four event categories SHALL each have an executor

| Category | Executor | Test file |
|---|---|---|
| identity ambiguity | `scripts/ask_for_direction_gate.py` TYPE_D | test_ask_for_direction_charter.py |
| authorization boundary | `scripts/ask_for_direction_gate.py` TYPE_D | test_ask_for_direction_charter.py |
| scope change | `scripts/ask_for_direction_gate.py` TYPE_D | test_ask_for_direction_charter.py |
| irreversible action | `scripts/ask_for_direction_gate.py` TYPE_S **and** `hooks/dispatch_gate.py` must-stop hook | both test files |

## Requirement: Type S precedence

In `ask_for_direction_gate.check()`, Type S MUST be evaluated before
Type D, which MUST be evaluated before Type A/B. A Type C convergence
signal MUST NOT bypass Type S or Type D.

## Requirement: dispatch-time must-stop MUST fire before claim-health check

In `hooks/dispatch_gate.py` main(), the must-stop check MUST run after
protocol parsing but BEFORE the failure-blocked lookup — an irreversible
action in a healthy claim's dispatch is just as irreversible. On match,
exit code MUST be 2 with a stderr `HARD_PAUSE Type S` line and a
`hookSpecificOutput.additionalContext` JSON payload.

## Requirement: init references the charter

`scripts/kunglao-init.py` SHALL carry a comment at the ask-then-install
site referencing `docs/agent_3state_charter.md` and stating that pending
decisions + RC_PENDING_DECISIONS=8 are the must-ask enforcement surface
at intake.

## Requirement: global rule references the charter

`rules/kunglao-convergence-loop.md` hard prohibition #1 SHALL defer to
the charter (allowed/must-ask/must-stop) instead of stating an
unconditional ban.

## Requirement: patterns are English-only

All TYPE_*_PATTERNS lists SHALL contain English patterns only. Mixing
languages in regex patterns is prohibited (brittle matching). This is
stated in the module docstring as policy.

## Requirement: legacy HARD_PAUSE ladder retained

The pre-#447 behaviour — 3+ self-redirects in the last hour → rc=2 —
MUST be preserved (Type A/B violations still count redirects).
