# convergence-stalled-remedy delta — issue-249-stalled-remedy

## ADDED Requirements

### Requirement: STALLED verdict carries an invokable remedy reference (#249)

The convergence health detector SHALL attach a machine-readable `remedy`
object to every STALLED verdict (operator `decompose`, the stuck claim
ids, the remedy-declared dispatch marker, and the target-ladder mint
command), and SHALL print the same literals in the human action string.
HEALTHY, NO_DATA and SPINNING verdicts SHALL NOT gain the key (prior
output shapes preserved). SPINNING harder-stop semantics SHALL NOT change.

#### Scenario: prose-only recovery is dead

- **WHEN** the detector assesses a flatlined ledger (5+ unchanged
  open_count snapshots or a dispatched claim stuck 3+ rounds)
- **THEN** the verdict JSON carries `remedy` with the stuck claims, the
  marker `remedy: decompose` and the mint command, and the action string
  carries the same marker and command

#### Scenario: other verdicts untouched

- **WHEN** the verdict is HEALTHY, NO_DATA or SPINNING
- **THEN** the result carries no `remedy` key and the SPINNING exit-code
  semantics are unchanged

### Requirement: STALLED gate exempts only its own prescribed remedy (#249)

At the rc=1 STALLED face of the dispatch gate battery, a dispatch SHALL
pass the STALLED block when its prompt declares the remedy marker
(`remedy: decompose`) AND its target claim intersects detector state:
either the claim is in the STUCK set (dispatched but flat), or the claim
is absent from the flatlined trailing open set AND register-OPEN AND its
depends_on references a stuck claim (mint provenance; the issue-234
siblings and the issue-241 splits both satisfy the pin). Everything else
SHALL stay blocked. The exemption SHALL be fail-closed (no exemption) on:
missing claim id, hooks-lib outage, detector state unresolvable
(exception included), predicate error (exception included), a re-derived
verdict that is not STALLED, an unreadable register, or an empty flatline
state. The predicate SHALL be single-sourced in
hooks/lib_kunglao; the STALLED state SHALL come from
scripts/convergence_health (`stalled_state`), never re-implemented at the
gate face. Every admitted remedy dispatch SHALL append an operator-action
telemetry row to the convergence ledger; after 2+ consecutive admitted
cycles on the same stuck episode the follow-through channel SHALL close
(channel A stays open, bounded by the rest of the battery). SPINNING
(rc=2) SHALL never be exempt; the rc=4 fail-open
crash semantics SHALL be untouched; callers without dispatch context
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

#### Scenario: remedy-depth escalation closes follow-through

- **WHEN** 2+ consecutive admitted remedy cycles have run on the same
  stuck episode (admit telemetry rows in the ledger) and a marked
  dispatch targets a minted sub-claim
- **THEN** the follow-through channel is closed for that dispatch while
  channel A remains open

#### Scenario: unresolvable inputs fail closed

- **WHEN** the hooks lib is unavailable, the detector state cannot be
  re-derived (exception included), the predicate raises (exception
  included), or the claim register is unreadable
- **THEN** no exemption fires and the legacy STALLED block applies

#### Scenario: SPINNING and crash faces untouched

- **WHEN** the detector exits rc=2 (SPINNING) or rc=4 (crashed)
- **THEN** rc=2 blocks every dispatch regardless of any remedy marker,
  and rc=4 fails open exactly as before

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
