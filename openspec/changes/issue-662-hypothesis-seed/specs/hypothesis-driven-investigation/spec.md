## ADDED Requirements

### Requirement: Every primary_question has an open hypothesis scaffold before any C-NN dispatch

The hypothesis seeder SHALL, at every cold-start digest build (and on direct CLI invocation), ensure every `task_spec.yaml` `primary_questions[]` entry has at least one hypothesis in `hypotheses/` whose body carries the marker `pq:<qid>` and whose status is `open`. Scaffolds carry `candidates: []` and `claim_id: C-PENDING` — the seeder invents no analysis content.

#### Scenario: fresh workspace with two primary questions
- **WHEN** `task_spec.yaml` declares primary questions `q1`, `q2` and `hypotheses/` is empty
- **THEN** seeding creates two `H-NNN` files, each with body marker `pq:<qid>`, `status: open`, `competitor_group: pq-<qid>`, `candidates: []`, `claim_id: C-PENDING`

#### Scenario: idempotent re-run (and marker survives rewrites)
- **WHEN** the seeder runs a second time after the first scaffold has already been transitioned (status rewritten by `HypothesisStore._write`)
- **THEN** no new file is created (the `pq:<qid>` body marker survived the rewrite) and the run exits 0

#### Scenario: missing or malformed task_spec
- **WHEN** `task_spec.yaml` is absent or unparseable
- **THEN** the seeder returns an empty list without raising (fail-open; convergence's own INVALID path owns malformed-schema escalation)

### Requirement: Cold-start digest seeds before listing

`scripts/digest_build.py::build_digest` SHALL invoke the seeder immediately before building `sec_g`, wrapped fail-open — a seeding failure never blocks cold start.

#### Scenario: digest build on a workspace with unanswered PQs
- **WHEN** `build_digest` runs on a workspace whose task_spec has primary questions and no hypotheses yet
- **THEN** the seeder creates the scaffolds and `sec_g` lists them (open hypotheses, pointer-sized)

#### Scenario: seeder raises
- **WHEN** the seeder import or execution raises
- **THEN** `build_digest` still returns a digest (sec_g degrades per existing #528 fail-open)

### Requirement: Open hypotheses at close block convergence

When the DRAIN stage is reached and any hypothesis in `hypotheses/` has `status: open`, the convergence decision machine SHALL emit `OPEN_HYPOTHESIS_AT_CLOSE` (between `NOTE_LAYER_GAP` and `DISCOVERY_UNCONSUMED`) and return `BLOCKED` naming each open hypothesis id.

#### Scenario: loop done but hypothesis unadjudicated
- **WHEN** no open claims, no partials, but `hypotheses/H-001.md` has `status: open`
- **THEN** decide() returns `BLOCKED` with reason naming `H-001` and the adjudication paths (refute via `refuting_fact_id` / supersede via `superseded_by`)

#### Scenario: hypothesis adjudicated → DRAIN proceeds
- **WHEN** `H-001` has `status: refuted` (with `refuting_fact_id: F012`) or `status: superseded`
- **THEN** the gate does not fire; DRAIN proceeds to the next probe

#### Scenario: hypotheses layer unreadable
- **WHEN** `hypotheses/` is absent or `HypothesisStore` raises
- **THEN** the gate does not fire (fail-open on layer errors — NOT on genuinely-open hypotheses)

### Requirement: Backward compatibility

Pre-#662 workspaces (hypotheses/ empty or absent, or containing only adjudicated hypotheses) SHALL converge exactly as before; no existing DRAIN probe is removed or reordered, and the new probe slots between `NOTE_LAYER_GAP` and `DISCOVERY_UNCONSUMED`.

#### Scenario: legacy workspace with no hypotheses dir
- **WHEN** `hypotheses/` does not exist and task_spec has no primary questions
- **THEN** seeding is a no-op and the DRAIN gate does not fire
