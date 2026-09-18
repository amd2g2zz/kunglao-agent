# Spec Delta — issue-256-fingerprint-wiring

## ADDED Requirements

### Requirement: Worker completions feed the zero-output fingerprint circuit

The worker_budget PostToolUse face (`post_check`) SHALL record every tool
that a completed dispatched worker actually invoked
(`scan_actual_tools` over the transcript) against its
`(tool, claim_id)` fingerprint via
`scripts/zero_output_fingerprint.record_action`, so repeated identical
no-progress actions accumulate streaks in
`runs/zero-output-fingerprint.json`. Only dispatched workers carrying a
`claim_id` in `[active_workers]` SHALL record; Agent completions without
a worker entry SHALL NOT touch the state. When a streak reaches
`ZERO_OUTPUT_N`, the existing `zero_output_break` telemetry event SHALL
fire from the real trigger path.

#### Scenario: two identical no-progress completions record a streak

- WHEN a dispatched worker for C-001 completes twice with identical
  no-progress transcripts (unchanged belief carriers) and
  `mcp__ghidra__decompile` in the transcript
- THEN the state file records streak 2 for the
  (tool, C-001) fingerprint
- AND `post_check` still returns 0 both times

#### Scenario: the break fires from the real trigger path

- WHEN the same fingerprint reaches `ZERO_OUTPUT_N` through
  `post_check` completions
- THEN exactly one `zero_output_break` row is emitted with actor
  `zero_output_fingerprint`, the tool attributed, and the streak in the
  detail payload

#### Scenario: merely-mentioned tool names are not invocations

- WHEN a completion transcript contains a tool name only inside another
  token (ripgrep, rev-frida2)
- THEN no fingerprint is recorded for that name; standalone
  KNOWN_TOOLS/mcp invocations still record

#### Scenario: orchestrator-side completions never record

- WHEN an Agent PostToolUse completion has no `[active_workers]` entry
  (or the entry lacks a claim_id)
- THEN no fingerprint state is written and no streak accrues

### Requirement: The zero-output gate runs in the production dispatch battery

`pre_check` SHALL include `check_zero_output_circuit` in its checks
battery (name `zerooutput`), carrying the dispatched claim and tool
list. The gate SHALL derive belief freshness ITSELF: a stored ledger
whose `belief_hash` differs from the current workspace belief hash is
stale (reset) and SHALL NOT reject. A tripped (claim, tool-family)
fingerprint SHALL reject only a dispatch that would REPEAT that
(claim, tool-family); other claims and other tool families SHALL pass.
A missing/unreadable state file SHALL fail open. The REJECT guidance
SHALL name `failure_analysis` and the state file
(`runs/zero-output-fingerprint.json`) as the manual escape hatch. The
registration SHALL be pinned structurally (exactly once in the battery).

#### Scenario: tripped circuit rejects only the repeating dispatch

- WHEN `runs/zero-output-fingerprint.json` carries a fresh
  (belief-hash matches) fingerprint for (grep, C-001) at streak >=
  `ZERO_OUTPUT_N`
- THEN a dispatch of C-001 with tool grep returns 2 with a stderr
  summary naming `zerooutput`, and the guidance names
  `failure_analysis` and the state file
- AND a dispatch of C-999 (same tool) returns 0
- AND a dispatch of C-001 with a different tool family returns 0

#### Scenario: belief move clears the block without a successful dispatch

- WHEN the circuit is tripped and the workspace belief subsequently
  moves (claim-register.yaml or facts/_INDEX.md content changes)
  without any `record_action` call in between
- THEN the would-repeat dispatch passes — the gate reads the stale
  ledger as reset, so clearing the block never requires the dispatch
  the block itself prevents

#### Scenario: fresh workspace fails open

- WHEN no circuit state exists
- THEN the `zerooutput` gate passes the dispatch (never deadlocks the
  loop)

### Requirement: Recorder faults are visible, never silent

A recorder fault SHALL NOT break `post_check` (liveness first: rc stays
0), but SHALL NOT be silently swallowed either: a crashing recorder AND
a no-op recorder (a `record_action` that returns without a dict carrying
`streak`) SHALL each land a stderr WARN naming the zero-output recorder.
The WARN SHALL be rate-limited to once per (workspace, reason) until the
reason changes, and a partial recording SHALL report what landed and
where counting stopped (never a blanket total-failure claim).

#### Scenario: crashed recorder stays visible

- WHEN `record_action` raises during a recording worker completion
- THEN `post_check` returns 0
- AND stderr carries a WARN naming the zero-output fingerprint recorder,
  with the landed/total tool count and the tool where counting stopped

#### Scenario: no-op recorder is detectable

- WHEN `record_action` is replaced by a callable that returns `None`
- THEN `post_check` returns 0
- AND stderr carries a WARN naming the no-op recorder — a broken
  recorder cannot masquerade as a healthy one

#### Scenario: a wedged recorder does not spam

- WHEN the same fault recurs on the next completion of the same
  workspace
- THEN no second WARN is printed until the reason changes
