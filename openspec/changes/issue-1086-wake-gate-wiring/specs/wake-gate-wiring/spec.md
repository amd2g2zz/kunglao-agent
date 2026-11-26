## ADDED Requirements

### Requirement: The registered cron command is the gate wrapper, not the prompt

The operator-facing registration SHALL run the wake gate's OS-scheduler
wrapper (`heartbeat_wake_gate.py <ws> --wake-gate`) — never the loop-prompt
emitter's stdout as the cron payload. The wrapper SHALL run
`heartbeat_tick.py <ws> --origin cron --wake-gate` (the gate stays the only
verdict authority) and emit the registration lines as strings only, carrying
`--wake-gate`.

#### Scenario: The emitted registration

- **WHEN** the registration face runs for a workspace
- **THEN** the crontab line and the schtasks args both name the wrapper
  script and carry `--wake-gate`, and neither mentions the loop-prompt
  emitter

#### Scenario: A cadence at or beyond the activation TTL is refused

- **WHEN** an interval at or above the 30-minute activation TTL is requested
- **THEN** the registration builders raise, naming the TTL bound

### Requirement: A quiet verdict injects nothing

On a gate verdict of quiet (rc 0 with the `QUIET:` marker), the wrapper
SHALL inject nothing: no prompt bytes staged, no session started, no receipt
written, and the pass SHALL exit 0. The quiet-day token cost of the wake
chain SHALL be zero model turns.

#### Scenario: Quiet pass

- **WHEN** the gate returns rc 0 and prints `QUIET:`
- **THEN** no prompt file is staged, no delivery happens, and the wrapper
  exits 0

### Requirement: A wake verdict injects the loop prompt exactly once

On a gate verdict of wake (rc 3 with the `WAKE:` marker), the wrapper SHALL
first draw the wake action through the decision seat
(`intelligent_scheduling.decide`; the wake-decision-wiring delta owns that
contract), then — unless the draw is the null action `none` — deliver the
loop prompt exactly once per pass: the payload SHALL be the
emitter's own body (`heartbeat_loop_prompt.build_prompt`), staged at
`runs/.wake-gate-prompt.txt`; a session SHALL be started only when no live
session owns the wake (the #39 dead-session predicate), reusing the external
kicker's delivery command; when a session is alive the staged prompt IS the
delivery and no second orchestrator is started. The pass SHALL exit 3 in
both cases (a drawn `none` keeps the gate's verdict rc with nothing
injected — the recorded zero-cost veto).

#### Scenario: Wake with no live session

- **WHEN** the gate returns rc 3, no session is alive, and the drawn
  action is not `none`
- **THEN** the prompt is staged and delivered out-of-session exactly once,
  and the wrapper exits 3

#### Scenario: Wake with a live session

- **WHEN** the gate returns rc 3, a session is alive, and the drawn
  action is not `none`
- **THEN** the prompt is staged, no second session is started, and the
  receipt records the staged delivery

#### Scenario: Wake suppressed by a drawn none

- **WHEN** the gate returns rc 3 and the drawn action is `none`
- **THEN** nothing is staged or delivered, the receipt records the none
  decision with `injected: false`, and the wrapper exits 3

### Requirement: A wrapper fault is loud and never a quiet

A gate crash, timeout, unexpected rc, verdict-marker mismatch, or delivery
failure SHALL be reported loudly (stderr banner plus a ledger warn row) and
SHALL exit non-zero — never the quiet exit code. A gate fault SHALL still
inject the loop prompt (fail toward waking): a wrapper that silently treated
its own failure as quiet would make the system never wake.

#### Scenario: Gate fault

- **WHEN** the gate exits with any rc other than 0/2/3, crashes, times out,
  or returns an rc without its verdict marker
- **THEN** the wrapper prints a stderr banner, writes a ledger warn row,
  injects the loop prompt, and exits 1

#### Scenario: Marker mismatch on rc 0

- **WHEN** the gate exits 0 without the `QUIET:` marker (not in gate mode)
- **THEN** the wrapper treats the pass as a fault, not a quiet

### Requirement: The breaker stop stays mandatory

On gate rc 2 (the idle circuit breaker), the wrapper SHALL inject nothing
and SHALL exit 2, loudly. A breaker stop is a mandated stop; it is never a
wake and never a quiet.

#### Scenario: Breaker stop

- **WHEN** the gate returns rc 2
- **THEN** nothing is injected, the stop is announced on stderr, and the
  wrapper exits 2

### Requirement: Quiet is legal inaction in the tick contract

The operator contract SHALL scope the "no action in a tick = idle fault"
rule and the THINK-seat EMPTY-forbidden rule to a WAKEN tick. Under a QUIET
verdict the gate injected nothing and no model turn happened, so no action is
owed (`sleep`/`none` are cost-0 actions in the scheduling registry). The
WAKE-branch discipline SHALL remain unchanged.

#### Scenario: The tick binding text

- **WHEN** the skill contract's tick-binding section is read
- **THEN** the idle-fault rule appears scoped to a woken tick, the QUIET
  carve-out is stated in the same section, and the idle-fault wording itself
  is preserved verbatim

