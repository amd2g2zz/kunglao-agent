## ADDED Requirements

### Requirement: Distillation SHALL produce an immutable CANDIDATE record by default, never a production rule

`memory/scripts/distill.py` SHALL, on a successful generation, write an immutable candidate record `memory/candidates/<id>.md` with frontmatter `status: CANDIDATE` plus lineage fields (`source_staging`, `source_hashes` per-entry sha256 of the snapshot bytes, `generator {name, version}`, `candidate_version`, `snapshot_ref`) and the synthesized rule body. `longterm/` SHALL NOT receive any new entry from the distill path (no direct longterm write; `write_longterm` moves behind the promotion gate). The candidate id SHALL be content-addressed: `cand-<12 hex of sha256(sorted source_hashes + generator version + synthesis input digest)>`, so re-running generation over identical inputs produces the same id. Candidate record files SHALL never be rewritten after creation; lifecycle state SHALL be recorded in `memory/lifecycle-journal.jsonl` only.

#### Scenario: default run writes a candidate and leaves production untouched

- **WHEN** `distill.py` runs with ≥ threshold staging entries and generation succeeds
- **THEN** exactly one `memory/candidates/cand-<hash>.md` exists with `status: CANDIDATE`, `source_hashes` matching the staging snapshot bytes, and `longterm/` contains no new file

#### Scenario: re-running over identical staging yields the same content-addressed id

- **WHEN** generation runs twice against the same sorted staging content with the same generator version
- **THEN** both runs produce the identical candidate id and the second run records a `duplicate` journal row instead of a second record

#### Scenario: a mutated candidate can never promote

- **WHEN** a candidate record's bytes on disk differ from the content hash recorded at creation (journal `generated` row)
- **THEN** the promotion gate refuses it with reason `tampered` and no production change occurs

### Requirement: Candidate records SHALL carry full lineage and evaluation fields

A candidate record SHALL record, at a minimum: source content hashes (per staging entry, from the snapshot bytes), candidate version, generator name + version, snapshot reference, and — once evaluated — evaluator name + version, held-in and held-out scores, safety-invariant results, and a reference to the full evaluation receipt(s) in `memory/candidates/receipts/`. Evaluation fields SHALL be added to the journal and receipt, not by rewriting the record file.

#### Scenario: evaluated candidate carries scores and receipt reference

- **WHEN** `evaluate.py <candidate-id>` completes with a receipt
- **THEN** the journal `evaluated` row for the id carries held-in and held-out score references, evaluator version, safety-invariant results, and the receipt path, and the candidate record file is byte-identical to its creation state

### Requirement: Candidates SHALL be evaluated only in the isolated candidate lab by the evaluator

Evaluation SHALL run only in the candidate lab (`memory/scripts/evaluate.py`): the evaluator receives the candidate body, case ids, and a writable outdir (`memory/candidates/receipts/`) and nothing else. Hidden `oracle-*.json` files and scorer inputs SHALL NOT be readable or writable by the candidate; candidate code SHALL NOT write into `memory/candidates/corpus/` or `eval/fixtures/`. `memory/candidates/corpus/manifest.json` SHALL pin sha256 of every case/oracle file and the policy-invariant list; any manifest digest mismatch SHALL fail the evaluation with `INCONCLUSIVE`. held-in cases SHALL derive from the staging cohort; held-out cases SHALL be disjoint from staging and unseen at generation time. The evaluator SHALL record its own version and code digest in every receipt, per the #81 receipt contract (`digests {case, oracle, code, env}`, `oracle {overall, dimensions}`, `receipt_digest` over stable fields).

#### Scenario: candidate cannot write or swap fixtures

- **WHEN** a candidate attempt writes into `memory/candidates/corpus/` or `eval/fixtures/`, or any corpus file digest no longer matches `manifest.json`
- **THEN** the lab fails the attempt with `INCONCLUSIVE` and a failure receipt, and no score is produced

#### Scenario: oracle answers are never exposed to the candidate

- **WHEN** the lab runs evaluation for a candidate
- **THEN** the candidate receives only public `case-*.json` content and the writable outdir; oracle paths are never provided to candidate code

#### Scenario: held-out cases are disjoint from staging

- **WHEN** the corpus is built for a candidate whose staging entries are known
- **THEN** no held-out case content appears in the staging snapshot of that candidate, and the manifest records the split

### Requirement: Promotion SHALL require a complete evaluator receipt, held-out gain, safety no-regression, source-hash lineage, and an independent score

`promote.py promote <id>` SHALL promote a candidate only when ALL of the following hold: (1) a complete evaluator receipt exists — schema valid, `receipt_digest` recomputes over the stable fields, and oracle dimensions contain no non-evidence value (`NOT-RUN` / `UNKNOWN` / `INCONCLUSIVE` / failed injection); (2) held-out correctness gain over the baseline receipt ≥ `HELD_OUT_GAIN_MIN` (0.10); (3) every pinned safety invariant passes with the candidate and none that passed on baseline regresses; (4) lineage holds — `source_hashes` match the snapshot bytes and any surviving staging entries hash-match the snapshot; (5) the scores are read only from evaluator receipts with a pinned evaluator version and code digest. A candidate missing any condition SHALL NOT be promoted: no receipt → stays `CANDIDATE`; failure of (2)–(5) → `REJECTED` with reason `overfit` / `harmful` / `stale` / `forged-receipt`, a journal row, and no production change. Rejected candidates are terminal: re-promotion requires a new generation.

#### Scenario: receipt-less candidate stays CANDIDATE

- **WHEN** `promote.py promote <id>` runs for a candidate whose journal has `generated` but no `evaluated` row, or whose receipt is incomplete
- **THEN** the candidate remains `CANDIDATE`, no journal `promoted` row is written, and `longterm/` is unchanged

#### Scenario: no held-out gain is rejected as overfit

- **WHEN** a candidate's held-out correctness gain over baseline is below `HELD_OUT_GAIN_MIN`
- **THEN** the candidate is `REJECTED` with reason `overfit` and the registry's current rule set is unchanged

#### Scenario: safety-case regression is rejected as harmful

- **WHEN** a candidate passes held-out gain but fails a pinned safety invariant, or regresses an invariant that passed on baseline
- **THEN** the candidate is `REJECTED` with reason `harmful`, production rules unchanged, and the journal records which invariant failed

#### Scenario: broken source lineage is rejected as stale

- **WHEN** a staging entry referenced in `source_hashes` has changed since the snapshot (current bytes hash differently), or the snapshot bytes no longer match the recorded hashes
- **THEN** the candidate is `REJECTED` with reason `stale` and no production change occurs

#### Scenario: forged-success receipt is rejected

- **WHEN** a candidate attempts promotion with a receipt whose `receipt_digest` does not recompute, or whose `digests.code` does not match the evaluator module bytes, or whose oracle dimensions claim PASS while containing `NOT-RUN`/`UNKNOWN`/`INCONCLUSIVE`, or whose file is outside the lab outdir
- **THEN** the candidate is `REJECTED` with reason `forged-receipt`, a journal row is written with the failing check, and the registry's current rule set is unchanged

#### Scenario: all five conditions pass and the candidate promotes

- **WHEN** a candidate has a complete receipt, held-out gain ≥ 0.10, all safety invariants passing with no baseline regression, intact lineage, and independently scored dimensions
- **THEN** the promotion sequence runs (backup current rule set, append the rule to `longterm/` + INDEX.md, registry `current` updated, `promoted` journal row with receipt_ref and digests)

### Requirement: A deliberately harmful or overfit candidate SHALL be rejected automatically with production rules unchanged

The promotion gate SHALL detect and reject without human intervention any candidate whose evaluation shows overclaim on adversarial cases, invalid/redundant work, evidence-deletion instructions, or direct-production-write instructions (the pinned safety invariants), or whose held-out gain is below threshold. Rejection SHALL leave the active rule set byte-identical (registry `current` and all `longterm/` files unchanged) and SHALL write a `rejected` journal row with reason and digests.

#### Scenario: adversarial candidate is rejected and production is untouched

- **WHEN** a candidate's receipts show an overclaim on the adversarial held-out case and `promote.py promote <id>` is attempted
- **THEN** the candidate is `REJECTED` with reason `harmful`, `memory/rules-registry.json` `current` is unchanged, no new `longterm/` file exists, and the `rejected` journal row records the invariant violation

### Requirement: Promotion and rollback SHALL restore the exact prior rule set and record action, reason, and digests

Before a promotion writes a new rule, the current rule set SHALL be snapshotted: byte copies of every `longterm/` entry in `memory/rules-backup/<rule-set-id>/` plus a `rule_set_digest` (sha256 over the canonical `{name: sha256}` map) in `memory/rules-registry.json`. `promote.py rollback --to <rule-set-id> --reason ...` SHALL restore every entry whose current digest differs from the target snapshot, then SHALL verify the resulting `{name: sha256}` map equals the target snapshot exactly (byte-for-byte), update registry `current` to the target, and append a `rolled_back` journal row with `to`, `reason`, per-file `restored {name: {before, after, ok}}`, and digests. A failed verification SHALL leave the registry and journal consistent (the rollback is not recorded as successful). A promotion-and-rollback drill SHALL be runnable against a scratch registry and SHALL restore the exact prior rule set.

#### Scenario: rollback restores the exact prior rule set

- **WHEN** a rule set was promoted from snapshot S (backup `memory/rules-backup/S/`) and `rollback --to S --reason "regression"` runs
- **THEN** every `longterm/` file's bytes match the S backup, the recomputed `rule_set_digest` equals S's, registry `current` points at S, and the `rolled_back` journal row contains `to: S`, the reason, per-file before/after digests, and the new rule-set digest

#### Scenario: promotion and rollback drill records both actions

- **WHEN** the drill runs promote → rollback on a scratch registry with a fixture rule set
- **THEN** the journal contains one `promoted` row and one `rolled_back` row for the same candidate id, and the restored rule set's digests match the pre-promotion snapshot exactly

### Requirement: Expired, stale, and duplicate candidates SHALL never promote; retirement SHALL be explicit and recorded

A candidate without a `promoted` row within `CANDIDATE_EXPIRY_DAYS` (30) SHALL be marked `expired` by the next `evaluate.py --status` scan, moved to `memory/candidates/.expired/` (archived, never deleted), and SHALL be refused by the promotion gate. A duplicate generation (content-addressed id already exists) SHALL write a `duplicate` journal row and no new record. A retired rule (`promote.py retire <name> --reason ...`) SHALL append a `retired` journal row with reason and digests, archive the rule, and update the registry; retirement is distinct from forget.py's automatic decay/prune.

#### Scenario: expired candidate cannot promote

- **WHEN** `promote.py promote <id>` runs for a candidate whose `generated` row is older than 30 days with no `promoted` row
- **THEN** the candidate is refused with reason `expired`, no `longterm/` change occurs, and the record sits in `memory/candidates/.expired/`

#### Scenario: duplicate generation is recorded without re-evaluation

- **WHEN** generation produces an id that already exists in `memory/candidates/`
- **THEN** a `duplicate` journal row is appended, no second record or receipt is created, and no production change occurs

#### Scenario: retirement records reason and digests

- **WHEN** `promote.py retire <name> --reason "superseded by newer rule"` runs for a promoted rule
- **THEN** a `retired` journal row with the reason and the rule's content digest is appended, the rule is archived, and the registry no longer lists it in `current`

### Requirement: Generation and evaluation failures SHALL retain raw staging evidence and SHALL produce a reproducible failure receipt

A generation failure SHALL produce a failure receipt (`{stage: generation, status: FAIL, reason, generator_version, input_digests, error_taxonomy, exit_code}`), create no candidate record, and leave staging untouched. A candidate write or hash-verify failure SHALL leave staging untouched. An evaluation failure (evaluator crash, lab error, or no receipt produced) SHALL produce a failure receipt (`{stage: evaluation, status: FAIL | INCONCLUSIVE, ...}`) and SHALL keep staging entries in place. Staging SHALL be cleared ONLY when the candidate record is written, its content hash is verified, AND a completed receipt (success or failure) exists for it. Staging snapshot directories SHALL never be deleted. Failure receipts SHALL be reproducible: identical inputs SHALL yield identical `receipt_digest` (timestamps excluded).

#### Scenario: generation failure keeps staging and writes a failure receipt

- **WHEN** generation raises (generator error) with staging at ≥ threshold
- **THEN** no candidate record exists, all staging files remain, and a failure receipt with `stage: generation` and a reproducible `receipt_digest` is written

#### Scenario: evaluation failure keeps staging

- **WHEN** the evaluator crashes or produces no receipt for a candidate
- **THEN** a failure receipt with `stage: evaluation` and `status: FAIL` or `INCONCLUSIVE` is written and the staging entries remain in `memory/staging/`

#### Scenario: staging clears only after verified candidate and completed receipt

- **WHEN** a candidate record is written, its content hash verifies, and a completed receipt exists
- **THEN** staging entries are cleared and the staging snapshot remains in place for audit; if any of the three conditions is false, staging entries are NOT cleared

#### Scenario: failed distillation leaves raw evidence recoverable

- **WHEN** generation or evaluation fails for a candidate whose staging cohort contained observation `2026-08-01-X.md`
- **THEN** `2026-08-01-X.md` still exists in `memory/staging/` (or in the retained snapshot) with byte-identical content, and the failure receipt references its content hash
