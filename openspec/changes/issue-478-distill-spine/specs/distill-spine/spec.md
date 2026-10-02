# distill-spine

## ADDED Requirements

### Requirement: four-product-schemas
The spine SHALL validate playbook/1 and decision-entry/1 documents (usage cards ride harvest manifests; lessons stay in rollup), rejecting malformed products at the T-pass inlet.

#### Scenario: malformed playbook rejected
- **WHEN** a playbook missing steps[].tool_ref enters the T-pass
- **THEN** it is rejected with a named violation and never lands

### Requirement: fixed-order-tpass
The T-pass SHALL run de_case -> promote_form -> tag -> verify -> dedup in fixed order; a product skipping a stage is a contract violation.

#### Scenario: unverified product never lands
- **WHEN** verify fails for a playbook (fixture replay misses milestones)
- **THEN** the product is archived (not landed) with the failure evidence

### Requirement: source-trust-gate
A source whose falsified products accumulate (default >=2) SHALL be batch-demoted (its landed products' trust drops) and blacklisted from future mining; rejection of WRONG sources is wholesale, dissimilar-but-sound sources are never rejected for dissimilarity.

#### Scenario: falsification batch-demotes
- **WHEN** a second product from source S is falsified
- **THEN** all landed products with source S carry demoted trust and S is blacklisted

### Requirement: adaptive-retention
Retention detail SHALL be a function of the four signals (corroboration, source trust, verification strength, reconstruction telemetry) — first-of-kind products retain rich detail; multi-corroborated compress to skeleton.

#### Scenario: corroboration compresses
- **WHEN** a second corroborating source merges into an existing product
- **THEN** its retention may drop to skeleton and the merge is recorded

#### Scenario: first-of-kind stays rich (PR2)
- **WHEN** a first-of-kind product (corroboration 1) is retained with any signal combination
- **THEN** its detail level stays rich unless runtime re-derive telemetry proves reconstruction

#### Scenario: weak verification never compresses (PR2)
- **WHEN** a corroborated product's verification strength is weak (not byte-exact), or its source has no earned trust entry, or it was never retrieved nor re-derived
- **THEN** retention stays rich (safety signals override the corroboration baseline)

### Requirement: analogy-transfer (PR2)
An analogy transfer SHALL split a source product layer-wise (case-surface dropped, technique-family kept only when features align by Jaccard similarity, methodology always kept); mismatched dimensions SHALL become explicit holes.

#### Scenario: mismatch dims become holes
- **WHEN** a source product with signature dims [arm64, ollvm] is transferred against target features naming only arm64
- **THEN** the technique-family layer is dropped (similarity below the align floor) and "ollvm" is returned as an explicit hole

#### Scenario: aligned features keep the technique family
- **WHEN** the target features cover every source signature dim
- **THEN** both methodology and technique-family layers are kept and no holes are raised

### Requirement: transfer-hypothesis-plan (PR2)
An analogy transfer SHALL deploy as a run-local HYPOTHESIS plan — a playbook/1 whose steps carry the mismatch holes marked unverified — for the runtime worker to adjudicate; a transfer without feature adjudication SHALL be rejected loudly.

#### Scenario: hypothesis plan is run-local and unverified
- **WHEN** transfer_hypothesis writes the plan for a transfer with holes
- **THEN** the plan lands under runs/ (never the product store), is a valid playbook/1, and its steps carry the holes with unverified: true

#### Scenario: transfer without adjudication raises
- **WHEN** transfer_hypothesis is called with no feature_match and no pre-adjudicated analogy block
- **THEN** a SpineOrderError is raised (a skipped stage, never a silent full-confidence plan)

### Requirement: single-landing-path (PR2)
Spine products SHALL land through the existing #474 tier-1 landing API (online_distill) with its shared budget ledger; the spine SHALL NOT open a second landing path, and the source-trust gate SHALL refuse landing for blacklisted sources.

#### Scenario: landing goes through the #474 API
- **WHEN** a code-form playbook product lands
- **THEN** its tool lands via online_distill.land_candidate into tools-local/ with a distill-manifest/1 provenance manifest, the shared ledger's landed counter increments through #474's own face, and the product is recorded in the product store with its source's trust incremented

#### Scenario: corrupt ledger or blacklisted source refuses
- **WHEN** the shared budget ledger is unreadable or the product's source is blacklisted
- **THEN** landing is refused with the named reason and nothing is written to tools-local/

### Requirement: landed-tool-discoverable (PR2)
A tool landed through the spine (or the #474 engine) SHALL be discoverable by the next worker face: tool-search --find SHALL scan the run-local shelf manifests (<ws>/tools-local/*.manifest.json) as a fourth source, and the landed manifest SHALL carry usage metadata (invocation pattern + verified behavior).

#### Scenario: the next worker discovers the landed tool
- **WHEN** a spine-landed code-form product sits in <ws>/tools-local/ with its manifest
- **THEN** tool-search --find <keyword> --ws <ws> surfaces it (kind run-local, capability tag, usage invoke line) and the worker's `tool-search: <kw> -> <hit>` citation row parses

#### Scenario: no workspace, no run-local hits
- **WHEN** --find runs with no resolvable workspace (or an empty one)
- **THEN** no run-local hits are fabricated (absence stays silent)
