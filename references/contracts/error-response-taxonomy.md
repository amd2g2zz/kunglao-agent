# Error Response Taxonomy — issue #448

> Single-source-of-truth: the forced-response classification for action errors (stop / retry-once / ask / escalate).
> Links with the three-state charter (references/contracts/agent-three-state-charter.md); priority declaration below.
> The mechanical classification table lives in `scripts/error_response.py`; the LLM backstops recall misses
> (same doctrine as #447: mechanical first, LLM covers enumeration blind spots, judgments land back as
> structured declarations).

## Why

2026-08-17 measured four consecutive bypass incidents (issue #448 evidence 2): each "route around it" looked
reasonable in isolation, chained together they are authorization overreach — T1 init exit 4 (HARD REFUSE), then
scanned the subnet anyway; T2 VPMC power-on failed, edited the .vmx directly (and edited the wrong VM); T3 lock
conflict, deleted the lock directly; T4 channel hang, swapped scripts to bypass. Error response levels were chosen
improvised, with no record anywhere of "why this response was chosen".

## Classification table (THE SINGLE SOURCE)

| Error class | Mechanical signal (enumerable) | Forced response | Corresponding charter state |
|---|---|---|---|
| **HUMAN-EVENT-REFUSE** | kunglao-init exit 3/4 (#304 human event); review-gate BLOCKED | **STOP** — stop that path, hand over to a human, no agent-side repair | must-stop |
| **CONFIG-CHANGE-REQUIRED** | vmrun "operation was canceled/canceled" (VPMC power-on failure); any error requiring a .vmx / VM config change to continue | **ASK** — identity ambiguity + config change, double must-ask | must-ask |
| **IDENTITY-AMBIGUITY** | Multiple VM / toolchain matches; "which VM" wording | **ASK** | must-ask |
| **TRANSIENT-LOCK** | "file is in use / locked / lock conflict" | **RETRY-ONCE** — same-method retry once only; failing again → ASK | allowed→ask |
| **TRANSIENT-TIMEOUT** | network timeout / connection reset | **RETRY-ONCE** — as above | allowed→ask |
| **CHANNEL-FAILURE** | guest channel hang (runProgramInGuest hang / no response); MCP bridge disconnect | **ESCALATE** — report a channel-level fault; swapping methods to bypass is forbidden | must-ask |
| **PENDING-DECISIONS** | kunglao-init exit 8 (RC_PENDING_DECISIONS) | **ASK** — pending decisions are themselves a must-ask surface | must-ask |
| **TOOL-INSTALL-HARD-FAIL** | toolchain_install degrade_report HARD item | **STOP** — that item stays FAIL, human installs (#408 semantics) | must-stop |
| **Unclassified (recall miss)** | mechanical table misses | **ASK** (safest default — silent continue / silent bypass forbidden) | must-ask |

## Response definitions

| Response | Allowed actions | Forbidden actions |
|---|---|---|
| **STOP** | Stop the current path + hand over to a human + record the original error | Any agent-side repair; any "route around it"; continuing execution |
| **RETRY-ONCE** | Same-method retry once (reason recorded) | Swap methods; change config; a second retry |
| **ASK** | Ask the user via the must-ask channel (charter Type D) | Decide yourself; change config yourself; silent downgrade |
| **ESCALATE** | Report the fault's layer + stop work that depends on that channel | Swap tools/scripts to bypass; pretend the channel is fine |

**Bypass anti-pattern**: an error response is always one of the four classes above, never "reach the same goal
with a different method" (that was incident T4). Swapping methods = new action = new authorization judgment, not an
error response.

## Priority declaration (rule-conflict adjudication)

**The human-event gate > the analysis-loop no-back-asking rule.**

When a HARD human-event gate fires (kunglao-init exit 4, review-gate BLOCKED), the charter's hard prohibition #1
("default allowed, decide yourself and continue") does **not apply** — that error class forces STOP + hand-over;
continuing execution is a violation. The two texts (#304 amendment vs hard prohibition #1) declare their priority
here: the former wins.

## Executors

| Face | Executor |
|---|---|
| Mechanical classification | `scripts/error_response.py` (CLI + library; error code / stderr signature matching, enumerable grammar) |
| Tool-install path | `toolchain_install.py` degrade_report (HARD items = STOP, already wired) |
| VM operations path | `error_response.py` vmrun signature table; full runtime wiring = follow-up |
| init path | the exit code itself is the classification (init 3/4 → STOP, init 8 → ASK) |
| LLM backstop | the orchestrator reads this document (docs are prompt); judgments land back as structured declarations |

## Acceptance cross-check

- [x] Classification table documented + ≥3 key paths gated (tool install / VM operation signatures / init exit code)
- [x] Rule text carries the priority declaration section (this doc + rules/kunglao-convergence-loop.md)
- [x] Conflict-scenario regression test (tests/test_error_response.py: init exit 4 → STOP with empty allowed_actions)
