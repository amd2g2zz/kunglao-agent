# convergence-stalled-remedy delta — issue-249-stalled-remedy

## ADDED Requirements

### Requirement: STALLED and SPINNING verdicts carry an invokable remedy reference (#249)

The convergence health detector SHALL attach a machine-readable `remedy`
object to every STALLED and every SPINNING verdict (operator `decompose`,
the stuck claim ids — the detector's stuck set, empty when no dispatched
claim is stuck — the remedy-declared dispatch marker, and the
target-ladder mint command), and SHALL print the same literals in the
human action string. HEALTHY and NO_DATA verdicts SHALL NOT gain the key
(prior output shapes preserved). SPINNING SHALL be entered only by an
open_count flatline of SPINNING_FLATLINE rounds over open work; fact
growth while open_count holds SHALL be reported under `churn` as
information only and SHALL NOT yield SPINNING.

#### Scenario: prose-only recovery is dead

- **WHEN** the detector assesses a flatlined ledger (5+ unchanged
  open_count snapshots or a dispatched claim stuck 3+ rounds)
- **THEN** the verdict JSON carries `remedy` with the stuck claims, the
  marker `remedy: decompose` and the mint command, and the action string
  carries the same marker and command

#### Scenario: other verdicts untouched

- **WHEN** the verdict is HEALTHY or NO_DATA
- **THEN** the result carries no `remedy` key

#### Scenario: SPINNING carries the same remedy

- **WHEN** open_count is flat for 8+ rounds over open work
- **THEN** the verdict is SPINNING (exit code 2), the verdict JSON
  carries the same `remedy` object as STALLED, and the action string
  names the remedy marker and keeps the reformulate / decompose / DEFER
  guidance

#### Scenario: fact growth alone is not SPINNING

- **WHEN** facts grow by 5+ while open_count holds and the flatline is
  below SPINNING_FLATLINE
- **THEN** the verdict is not SPINNING and the `churn` field still
  reports the fact growth

### Requirement: STALLED and SPINNING gate exempts only its own prescribed remedy (#249)

At the rc=1 STALLED face and the rc=2 SPINNING face of the dispatch gate
battery (same predicate, channels, depth cap and admit telemetry), a
dispatch SHALL pass the block when its prompt declares the remedy marker
(`remedy: decompose`) AND its target claim intersects detector state:
either the claim is in the STUCK set (dispatched but flat), or the claim
is absent from the flatlined trailing open set AND register-OPEN AND its
depends_on references a stuck claim (mint provenance; the issue-234
siblings and the issue-241 splits both satisfy the pin). Everything else
SHALL stay blocked. The exemption SHALL be fail-closed (no exemption) on:
missing claim id, hooks-lib outage, detector state unresolvable
(exception included), predicate error (exception included), a re-derived
verdict that is neither STALLED nor SPINNING, an unreadable register, or
an empty flatline state. With open claims but no stuck claim there is no
remedy target: nothing is admissible at either face. The predicate SHALL
be single-sourced in hooks/lib_kunglao; the remedy state SHALL come from
scripts/convergence_health (`stalled_state`, which names the verdict and
the detector's stuck set), never re-implemented at the gate face. Every admitted remedy dispatch SHALL append an operator-action
telemetry row to the convergence ledger; after 2+ consecutive admitted
cycles on the same stuck episode the follow-through channel SHALL close
(channel A stays open, bounded by the rest of the battery), at the
STALLED and the SPINNING face alike. The rc=4
fail-open crash semantics SHALL be untouched; callers without dispatch context
SHALL keep the exact prior block behavior; every other gate in the
battery SHALL still apply to an admitted remedy dispatch.

#### Scenario: remedy-declared dispatch of a stuck claim passes

- **WHEN** the detector verdict is STALLED with stuck claim C-001 and a
  dispatch for C-001 carries the `remedy: decompose` marker
- **THEN** the rc=1 face admits the dispatch (with an observed note) and
  the remaining gate battery still applies

#### Scenario: ordinary dispatch stays blocked

- **WHEN** the verdict is STALLED and a dispatch for the stuck claim
  carries no remedy marker
- **THEN** the rc=1 face blocks with the prior message

#### Scenario: minted sub-claim follow-through passes

- **WHEN** the verdict is STALLED and a marked dispatch targets a claim
  that is register-OPEN, absent from the flatlined trailing open set,
  and its depends_on references the stuck parent (a real issue-234
  sibling)
- **THEN** the rc=1 face admits the dispatch

#### Scenario: fresh unrelated OPEN claim is refused (round-2 pin)

- **WHEN** the verdict is STALLED and a marked dispatch targets a
  register-OPEN claim with NO depends_on edge to a stuck claim (the
  round-1 review exploit shape: self-appended mid-STALLED, marker
  quoted from the rejection prose)
- **THEN** the rc=1 face blocks

#### Scenario: marker alone is not enough

- **WHEN** a marked dispatch targets a claim that sits in the flatlined
  open set without stuck evidence (queued frontier, not the remedy)
- **THEN** the rc=1 face blocks

#### Scenario: SPINNING face admits the same remedy

- **WHEN** the verdict is SPINNING with stuck claim C-001 and a marked
  dispatch targets C-001 (or a register-OPEN sub-claim whose depends_on
  names C-001), and an unmarked dispatch targets the same claim
- **THEN** the rc=2 face admits the marked dispatch (appending the admit
  telemetry row) and blocks the unmarked one

#### Scenario: open claims without a stuck claim are not admissible

- **WHEN** the verdict is STALLED or SPINNING, no dispatched claim is
  stuck, and a marked dispatch targets an open claim, or an OPEN claim
  whose depends_on names an open (not stuck) claim
- **THEN** the face blocks the dispatch

#### Scenario: remedy-depth escalation closes follow-through

- **WHEN** 2+ consecutive admitted remedy cycles have run on the same
  stuck episode (admit telemetry rows in the ledger) and a marked
  dispatch targets a minted sub-claim, at the STALLED or the SPINNING
  face
- **THEN** the follow-through channel is closed for that dispatch while
  channel A remains open

#### Scenario: unresolvable inputs fail closed

- **WHEN** the hooks lib is unavailable, the detector state cannot be
  re-derived (exception included), the predicate raises (exception
  included), or the claim register is unreadable
- **THEN** no exemption fires and the legacy STALLED block applies

#### Scenario: crash face untouched

- **WHEN** the detector exits rc=4 (crashed)
- **THEN** the gate fails open exactly as before, remedy marker or not

### Requirement: decomposition mints break the STALLED flatline mechanically (#249)

The prescribed remedy SHALL be executable through the merged issue-234
fan-out: walking the claim's target ladder and inventory, then
`mint_sibling_claims`, SHALL register OPEN sub-claims (real depends_on
edges), so the next ledger snapshot changes open_count and the flatline
breaks; after the stuck parent retires terminal (SUPERSEDED by its
alternatives) the verdict SHALL flip HEALTHY and ordinary dispatch SHALL
resume. The full cycle SHALL be pinned end-to-end through the real
detector CLI, the real dispatch gate battery and the real mint.

#### Scenario: the pinned full cycle

- **WHEN** a healthy workspace flatlines into STALLED, the stuck claim's
  remedy dispatch executes, the ladder is walked, siblings are minted,
  and the parent retires SUPERSEDED
- **THEN** the next ledger entry breaks the flatline, the detector
  returns HEALTHY, and a plain dispatch of a minted sub-claim is admitted
  — the deadlock is closed by construction
