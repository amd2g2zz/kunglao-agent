# Proposal — state_anchor hook (per-turn mechanical re-anchor) (#44)

## Why

The convergence loop's reliability depends on the model **knowing the
current mechanical state** every turn: what it decided last, what is open,
what is partial, who is running, how many facts exist. v1.9 ships two layers
that touch this:

- **worker_pulse** (#38) injects a convergence pulse — but only after a
  dispatch-prefix Agent call (the `[T<N> tools=…] claim C-NN` prompt). It is
  an event-reactive nudge, not a per-turn belief anchor.
- **external_kicker** (#39 / #43) detects dead and alive-but-stuck sessions
  and RECOVERS with a fresh session that resumes from fired predicates
  (#45 `build_resume_prompt`).

Between "the loop forgot to check" and "the session died" lies the dominant
failure mode research flags: **context rot**. F5 (deterministic Executive
owns belief: know / change / commit / forget / recover) — a long-running
orchestrator absorbs itself in a worker report, or gets compacted, and
silently loses track of open claims / blockers / drift. There is no
per-turn mechanical backstop that re-anchors belief from logged state. F1
(72.5% of long-horizon failures are process-level, fixable in the harness)
confirms the height: a harness-level injection is the correct fix.

`state_anchor` is the missing **L1 PREVENT** layer: a PostToolUse(Agent)
hook that, on every worker completion, injects a compact state signature
(≤500 chars) built from the convergence ledger's last snapshot + the claim
register + the facts index + active workers — exactly the fired predicates
#45's resume prompt reads, but delivered *continuously* so the live session
never drifts, not only after a crash. When the ledger signature has been
frozen for `ROTATION_WINDOW` (#43's alive-but-stuck signal) and no worker is
progressing, the anchor appends a prominent `⚠ STATE FLAT` warning that
triggers a re-read of the claim register — the cure-first nudge that should
preempt #43's escalation-to-kick (the 3→6-row cure-first window from #43
design D4).

## Scope

- CREATE `hooks/state_anchor.py` — PostToolUse hook, matcher `Agent`:
  - `build_anchor(ws) -> str`: reads the ledger last SNAPSHOT row + OPEN /
    PARTIALLY-VERIFIED claim ids + `facts_total` + active workers, returns a
    ≤500-char summary. Truncates the open-ids list if longer; NEVER raises
    (any exception → `""`). Reads ONLY mechanical state — NEVER
    `progress.txt` / `analysis_state.txt` narrative (F4: an LLM saying done
    is not an event).
  - Drift warning: when `drift_detected(ws)` (#43 — `signature_rotation ≥
    ROTATION_WINDOW` AND no worker progressing), the anchor text appends a
    prominent `⚠ STATE FLAT: N identical turns, re-read claim-register`,
    where N = `signature_rotation(ws)`.
  - Entry guard: emit ONLY when `tool_name == "agent"` (case-insensitive —
    the harness lowercases tool names). Non-agent tools (Bash / Read / …)
    SKIP (empty output, rc 0).
  - FAIL_OPEN: any exception in `build_anchor` or the drift lookup → return
    empty string (never aborts the worker completion).
- REGISTER via `scripts/wire_up_settings.py::_ensure(post, "Agent",
  "state_anchor.py")` (mirror the existing worker_pulse line), and add
  `"state_anchor"` to `ALL_HOOKS` in `scripts/hook_activation.py`
  (consistency with worker_pulse which is already listed).
- TESTS `tests/test_state_anchor.py` (RED first).

## Non-goals

- NOT a gate — the anchor INJECTS context (`additionalContext`); it never
  rejects or aborts. The orchestrator still owns the decision.
- NOT a replacement for worker_pulse — worker_pulse fires only on
  dispatch-prefix Agent calls and carries the convergence decision + next-up
  claim; state_anchor fires on EVERY Agent completion and carries the raw
  state signature + drift warning. They are complementary.
- NOT the recovery layer — external_kicker (#43 `should_kick`) recovers a
  persistently drifted session; state_anchor is the cure that should heal
  drift inside the 3→6-row window so recovery is rarely needed.
