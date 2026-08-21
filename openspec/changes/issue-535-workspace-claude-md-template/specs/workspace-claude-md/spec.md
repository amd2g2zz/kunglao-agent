# workspace-claude-md spec

## ADDED Requirements

### Requirement: core cold-start section MUST stay within the 50-line cap

The template's core cold-start section SHALL contain at most 50 lines
(every line above the State-files heading). Dynamic runtime state (worker
IDs, claim-status dumps, state hashes) SHALL NOT be inlined; sample
identity SHALL live in analysis_state.txt and the Sample-under-analysis
table, which SHALL sit at or below the State-files fold. The cap SHALL be
enforced by a pytest assertion in tests/test_workspace_claude_md_template_535.py.

#### Scenario: core within cap

- **WHEN** the template is measured from the top through the line before the State-files heading
- **THEN** the section SHALL be at most 50 lines
- **AND** SHALL contain pointers only, no dynamic-state tokens

### Requirement: cold-start pointer table MUST carry nine resolvable pointers

The template SHALL include a Workspace-at-a-glance table naming each of:
analysis_state.txt, global_plan.txt, task_spec.yaml, claim-register.yaml,
claim_deps.yaml, facts/_INDEX.md, blockers/, runs/, runs/.env-check.json.
Every pointer SHALL resolve in a workspace that completed init; the two
on-demand pointers (task_spec.yaml, written by needs-first intake;
runs/.env-check.json, written by env_check.py) SHALL carry their creator
in the pointer row so a cold-start worker can act on absence instead of
trusting it.

#### Scenario: pointers resolve after real init

- **WHEN** init runs to exit 0 on a fresh workspace
- **THEN** the rendered CLAUDE.md SHALL name all nine pointers verbatim
- **AND** the seven eager pointers SHALL exist on disk
- **AND** task-oracle.yaml SHALL exist (init skeleton)

### Requirement: loop-enforcement block MUST survive compact as the persistent channel

The template SHALL contain a Loop-enforcement (persistent channel)
section naming all four mandatory per-round rules: run convergence_check
before claiming progress (decision-table action mandatory); heartbeat TTL
re-anchor when runs/.heartbeat.json is stale (35 minutes, matching
scripts/heartbeat.py STALE_MINUTES); task-oracle verdict is terminal until
a blocker is filed; post-compact re-entry re-reads analysis_state.txt,
claim-register.yaml, and global_plan.txt before the first tool call.

#### Scenario: post-compact re-entry

- **WHEN** a worker's context is compacted mid-round
- **THEN** the loop-enforcement rules SHALL remain in the persistent CLAUDE.md channel the worker re-reads on re-entry
- **AND** convergence_check SHALL run again before any further tool call

### Requirement: six-carrier memory contract MUST govern note writes

The template SHALL contain a Memory-carriers (write/recall contract)
table with one row per carrier — claim-register.yaml, facts/_INDEX.md
(plus facts/F<NNN>.md), blockers/, global_plan.txt, analysis_state.txt,
task-oracle.yaml — each row specifying write-what, who-writes-when,
when-to-recall, and correction semantics. Carriers SHALL match what init
actually scaffolds; recall triggers SHALL be reachable from
convergence_check.py (per-round, mechanical).

#### Scenario: per-carrier rules are the authority

- **WHEN** a worker decides whether to write a note
- **THEN** the per-carrier contract row SHALL be the deciding rule
- **AND** the information SHALL have exactly one owning carrier

### Requirement: write criteria MUST include the replacement test as a hard default

The template SHALL enumerate five write criteria, where criterion 4 is
the replacement test (HARD default): a freshly spawned worker with zero
conversation history and workspace read access alone can locate the
information through the recall trigger. A no-write list SHALL enumerate
the specific skip cases; recall wording SHALL align with
kunglao-convergence-loop semantics (per-round convergence_check, disk is
truth).

#### Scenario: replacement test applies

- **WHEN** information fails the replacement test
- **THEN** it SHALL NOT be written to the candidate carrier
- **AND** the worker SHALL pick a carrier that fits the recall graph or skip the write

### Requirement: blanket write-disable directives MUST NOT appear

The template SHALL NOT contain blanket write-disable phrases (no writes,
do not write, writing disabled, notes disabled,
write-instructions=0). Note-write rules SHALL live exclusively in the
per-carrier contract.

#### Scenario: C-2 anti-pattern absent

- **WHEN** the template is searched case-folded for the forbidden phrases
- **THEN** none SHALL appear

### Requirement: BLIND verifier contract MUST be preserved

The template SHALL retain the BLIND verifier contract in the
hard-constraints section: verifier agents receive only the raw evidence
path and the questions, never producer context.

#### Scenario: BLIND wording intact

- **WHEN** the rendered CLAUDE.md is searched
- **THEN** the BLIND verifier wording SHALL be present
