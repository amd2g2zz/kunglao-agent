## ADDED Requirements

### Requirement: The wake branch consults the recorded decision seat

On a gate verdict of wake (rc 3 with the `WAKE:` marker), the wrapper
SHALL draw the wake action through the decision seat
(`intelligent_scheduling.decide`) BEFORE any injection: one recorded
scheduling decision per wake pass, carrying the drawn action, its exact
propensity, and its `probability_source`. The seat's own recording
(`runs/.scheduling-decision.json` + one `kind=scheduling` signal row) is
the decision's ledger; the wrapper's receipt SHALL additionally carry a
`decision` block summarizing the draw (action, propensity, source, k,
probability_source). The decision seat is the wake-decision seat only —
it SHALL NOT be registered as a proposal-class mechanism (no
`channel: tick` entry; the scheduler never dispatches it).

#### Scenario: A wake pass records exactly one decision

- **WHEN** the gate returns rc 3 with the `WAKE:` marker
- **THEN** exactly one `kind=scheduling` row lands on the signal stream
  with the drawn action, its exact propensity and its
  `probability_source`, the persisted decision record agrees with the
  row, and the wrapper's receipt carries the same decision block

#### Scenario: The registration faces stay untouched

- **WHEN** the wrapper's registration lines are emitted
- **THEN** they name the wrapper and `--wake-gate` exactly as before —
  the decision layer adds no registration surface

### Requirement: A drawn none injects nothing

When the decision seat's draw is the null action (`none`), the wrapper
SHALL inject nothing: no prompt bytes staged, no session started. This
is the legal zero-cost outcome of the two-layer semantics — the gate
said there is work to look at, the action layer said no wake is owed —
and it SHALL NOT be reported as a fault. The pass SHALL exit with the
gate's verdict rc (3), the receipt SHALL record `injected: false` with
the decision block, and the decision row SHALL still land (the veto is
a recorded decision, not a skipped one).

#### Scenario: None draw on a wake verdict

- **WHEN** the gate returns rc 3 and the seat's draw is `none`
- **THEN** no prompt file is staged, no delivery happens, the exit code
  is 3, and the receipt records the none decision with
  `injected: false`

### Requirement: Only a true wake verdict consults the seat

The decision seat SHALL run only on a true wake verdict. A QUIET verdict
SHALL NOT draw (zero sampling on the quiet path — the gate already
judged no wake, drawing again is pure overhead). A STOP verdict (the
idle circuit breaker) SHALL NOT draw (a mandated stop is the breaker's
decision, not a scheduling action). A gate FAULT SHALL NOT draw and
SHALL inject unconditionally (fail toward waking): a seat that could
veto a fault-wake would recreate the never-wakes failure the wrapper
refuses.

#### Scenario: Quiet pass draws nothing

- **WHEN** the gate returns rc 0 with the `QUIET:` marker
- **THEN** no decision row lands, no decision record is persisted, and
  no receipt is written (the quiet contract is unchanged)

#### Scenario: Stop and fault passes draw nothing

- **WHEN** the gate returns rc 2, or any fault shape (crash, timeout,
  unexpected rc, marker mismatch)
- **THEN** no decision row lands and the pass behaves exactly as the
  pre-decision contract (stop: nothing injected, rc 2; fault: loud,
  inject, rc 1)

### Requirement: A broken decision seat fails toward waking

If the decision seat itself raises, the wrapper SHALL NOT sleep the
system on it: the failure SHALL be loud (stderr banner + ledger warn
row), the receipt SHALL carry a `decision.fault` naming the error, and
the injection SHALL proceed as if no veto existed. The pass keeps the
gate's verdict rc.

#### Scenario: Seat failure on a wake verdict

- **WHEN** the gate returns rc 3 and the seat call raises
- **THEN** the wrapper prints a stderr banner naming the failure,
  injects the loop prompt exactly once, and exits 3

### Requirement: probability_source uses the dispatch face's honest vocabulary

Every scheduling decision row SHALL carry a `probability_source` drawn
from the dispatch face's accepted selection-law vocabulary
(`rlvr.policy_compare.ACCEPTED_PROBABILITY_SOURCES`): a draw that ran
through the selection law reads `selection_law_exact` (the exact
Plackett-Luce propensity of the ordered draw on its own information
set — including a drawn `none`); a deterministic face (a declared
action, or the k=0 forced null) reads `unknown`, because no draw
receipt backs its 1.0. A trajectory marginal SHALL NEVER be logged as a
selection law.

#### Scenario: A drawn none versus a forced none

- **WHEN** the sampler draws `none` (k > 0)
- **THEN** the row carries the drawn exact propensity (1/5 under the
  flat priors at k=1) with `probability_source: selection_law_exact`
- **WHEN** the null action is forced by k = 0 (no slot room)
- **THEN** the row carries propensity 1.0 with
  `probability_source: unknown`
