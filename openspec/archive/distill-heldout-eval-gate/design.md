# Design — gate memory distillation behind held-out evaluation and rollback (#82)

## Design Decisions

### D1. Candidate-first: distill.py's durable output is an immutable candidate record

Current pipeline: `synthesize_longterm_body` (stub) → `write_longterm` → verify → clear staging
(distill.py L83-L148). New default path:

```
staging/ (N ≥ threshold) → snapshot → generate → candidate record (CANDIDATE) → verify hash → clear staging
```

- The candidate record `memory/candidates/<id>.md` is written once at generation. Frontmatter
  carries `status: CANDIDATE`, `source_staging` (entry names), `source_hashes` (per-entry sha256
  of snapshot bytes), `generator {name, version}`, `candidate_version`, `snapshot_ref`. Body = the
  synthesized rule + examples. The stub template remains the generator until LLM wiring — the
  point of this issue is that even template output must be a candidate, never a production rule.
- Content-addressed id: `cand-<12 hex of sha256(sorted source_hashes + generator version +
  synthesis input digest)>`. Deterministic: re-running distill over the same staging set yields
  the same id, so duplicates are detectable without opening files (D7).
- Immutability: the record is never rewritten after creation; lifecycle state lives in the
  journal, not the file. At promotion the gate recomputes the content hash and refuses to promote
  on mismatch (tampered or mutated candidate).
- Staging clear stays inside the same verified transaction shape as today (snapshot → write →
  verify → clear), but the target of "write + verify" is the candidate record and the clear
  condition additionally requires a completed receipt (D8).
- No direct longterm path: the `write_longterm` call moves behind the promotion gate (D4/D5).

### D2. Lifecycle as an append-only journal; status derived from the ledger

`memory/lifecycle-journal.jsonl` — append-only, one JSON row per event, same idiom as
`.convergence_ledger.jsonl`:

```
{"ts", "action", "candidate_id", "reason", "digests", "receipt_ref"}
action ∈ {generated, evaluated, promoted, rejected, expired, retired, rolled_back, duplicate, failed}
```

- Effective status of a candidate = last journal row for its id. `status: CANDIDATE` in the file
  is the initial state only; no code rewrites the record file.
- Promotion requires journal rows `generated` → `evaluated` in order for the id; a missing
  `evaluated` row is a blocked promotion (acceptance a — a receipt-less candidate stays
  CANDIDATE).

### D3. Candidate lab: evaluator-owned scoring, hidden fixtures, hash-pinned invariants

The lab (`evaluate.py`) is the ONLY place a candidate receives scores. It follows the #81
evaluator-ownership model (executable-l2-evaluation design D5 / spec "Evaluator-controlled
oracle with hidden scorer inputs"):

- Public inputs handed to the evaluator: candidate body, case ids, and a writable outdir
  (`memory/candidates/receipts/`). Hidden `oracle-*.json` files and scorer inputs are never
  opened by candidate code; the candidate never writes into `memory/candidates/corpus/` or
  `eval/fixtures/`.
- Corpus layout: `memory/candidates/corpus/{held-in,held-out}/case-*.json` (public) +
  `oracle-*.json` (hidden). `manifest.json` pins sha256 of every file plus the policy-invariant
  list — a candidate cannot swap, edit, or redefine fixtures or invariants without breaking the
  manifest digest.
- held-in = cases derived from the same staging cohort (the observations being distilled);
  held-out = unseen cases disjoint from staging, never shown to generation.
- Baseline: the current production rule set (no-rule policy) is evaluated on the SAME held-out
  cases; the baseline receipt is stored alongside the candidate so gain is measurable (D4).
- Safety invariants are named checks the evaluator applies to the episode: overclaim = 0 on
  adversarial cases, invalid_work = 0, no evidence-deletion instruction, no
  direct-production-write instruction. The invariant list is part of the pinned manifest; the
  candidate cannot alter what "safe" means.
- The evaluator records its own version + code digest in the receipt, per the #81 receipt
  contract (`digests {case, oracle, code, env}`, `oracle {overall, dimensions}`,
  `receipt_digest` over stable fields). Receipts land in `memory/candidates/receipts/`.

### D4. Promotion gate: five mandatory conditions

`promote.py promote <id> --reason <...>` promotes ONLY if ALL five hold; otherwise the
candidate is `REJECTED` (terminal) with the failing reason:

1. **Complete evaluator receipt** — ≥1 receipt exists for the candidate; schema valid;
   `receipt_digest` recomputes over the stable fields; oracle dimensions contain no
   non-evidence value (`NOT-RUN` / `UNKNOWN` / `INCONCLUSIVE` / failed injection — the #81
   non-evidence rule carried over). No receipt → candidate stays CANDIDATE (acceptance a).
2. **Held-out gain** — held_out.correctness − baseline.correctness ≥ `HELD_OUT_GAIN_MIN`
   (0.10, constant) on the pinned held-out set. No gain → `REJECTED` reason `overfit`
   (acceptance b, c).
3. **Safety no-regression** — every pinned safety invariant passes with the candidate, and no
   invariant that passed on baseline fails with it. Any failure → `REJECTED` reason `harmful`;
   production rules unchanged (acceptance c).
4. **Lineage** — `source_hashes` in the record match the snapshot bytes; if staging entries
   still exist they must hash-match the snapshot. A staging entry changed since generation
   breaks lineage → `REJECTED` reason `stale` (acceptance b: lineage to source hashes).
5. **Independent score** — scores used in 1–3 are read ONLY from evaluator receipts
   (evaluator version + code digest pinned in the receipt). A candidate-supplied score, or a
   receipt failing provenance (D6), → `REJECTED` reason `forged-receipt` (acceptance b:
   independently produced score).

All rejection reasons are journaled (`rejected` row with reason + digests). A rejected
candidate is terminal: re-promotion requires a NEW candidate (new generation).

### D5. Rule-set registry, backup, and rollback

`memory/rules-registry.json`:

```
{"current":    {"id", "rule_set_digest", "entries": {name: sha256}, "promoted_at", "receipt_ref"},
 "snapshots":  {"<rule-set-id>": {"entries": {name: sha256}, "rule_set_digest",
                                  "backup_dir", "promoted_at"}},
 "history":    [...]}
```

Promotion sequence (D4 pass):

1. Byte-copy every current longterm entry into `memory/rules-backup/<rule-set-id>/` (the
   last-known-good before this promotion).
2. Compute `rule_set_digest` = sha256 over the canonical `{name: sha256}` map.
3. Append the new rule file (`longterm/<date>-rule-<slug>.md`) + INDEX.md line.
4. Registry `current` → new rule set; journal `promoted` row with receipt_ref + digests.

On failure of any step, an already-written rule file is removed and the registry is untouched
(same rollback-of-write discipline distill.py already applies today).

Rollback (`promote.py rollback --to <rule-set-id> --reason ...`):

1. Resolve the target snapshot from the registry.
2. For every longterm entry whose current digest differs from the target snapshot's digest,
   restore bytes from `memory/rules-backup/<rule-set-id>/`.
3. Verify the resulting `{name: sha256}` map equals the target snapshot EXACTLY (byte-for-byte
   prior rule set — acceptance d).
4. Registry `current` → target; journal `rolled_back` row with `to`, `reason`,
   `restored {name: {before, after, ok}}`, and digests.

The drill (acceptance d) = a promotion followed by a rollback executed against a scratch
registry/backup; the assertion is exact restoration and both journal rows present.

### D6. Forged-success receipts

A receipt is forged or untrustworthy when ANY holds:

- (a) `receipt_digest` recomputation over the stable fields ≠ claimed digest;
- (b) `digests.code` ≠ sha256 of the evaluator module bytes actually used by the lab (or absent);
- (c) oracle dimensions claim PASS while carrying non-evidence values
  (`NOT-RUN` / `UNKNOWN` / `INCONCLUSIVE` / failed injection);
- (d) the receipt file is not inside the lab outdir (bad provenance).

Any → `REJECTED` reason `forged-receipt`, journal row, registry unchanged. The gate never
executes candidate-supplied scoring code — scoring is a function of the evaluator module only
(acceptance e: forged-success receipts covered by tests).

### D7. Duplicates, expiry, retirement

- **Duplicate**: generation whose content-addressed id already exists → `duplicate` journal
  row; no new record, no re-evaluation, no receipt. (Acceptance e: duplicate candidates tested.)
- **Expiry**: candidates without a `promoted` row within `CANDIDATE_EXPIRY_DAYS` (30, constant)
  are marked `expired` by the next `evaluate.py --status` scan; EXPIRED is never promotable;
  records move to `memory/candidates/.expired/` (archive, never deleted — mirrors forget.py's
  archive discipline). (Acceptance e: stale/expired candidates tested.)
- **Retirement**: a promoted rule can be retired (`promote.py retire <name> --reason ...`) →
  `retired` journal row + archived copy + registry entries updated. Retirement is explicit,
  reason-required, digest-recorded — distinct from forget.py's automatic decay/prune.

### D8. Failure semantics: staging cleared only on verified candidate + completed receipt

- **Generation failure** (exception / generator error): failure receipt
  `{stage: generation, status: FAIL, reason, generator_version, input_digests, error_taxonomy,
  exit_code}`; NO candidate record; staging untouched (acceptance e: source-evidence retention).
- **Candidate write or hash-verify failure**: staging untouched.
- **Evaluation failure** (evaluator crash / lab error / no receipt produced): failure receipt
  `{stage: evaluation, status: FAIL | INCONCLUSIVE, ...}`; staging is KEPT — the candidate
  record may exist, but the clear condition is false.
- **Clear condition**: staging is cleared ONLY when the candidate record is written AND
  content-hash verified AND a completed receipt (success or failure) exists for it. Raw
  evidence additionally stays recoverable via the staging snapshot (snapshot dirs are never
  deleted — the retention mechanism the acceptance criterion requires).
- Failure receipts are reproducible: same inputs → same `receipt_digest` (timestamps excluded),
  mirroring the #81 receipt replay rule.

### D9. CLI surface

```
python memory/scripts/distill.py                                  # default: generate candidate
python memory/scripts/distill.py --threshold 5 --force --dry-run  # thresholds/overrides kept
python memory/scripts/evaluate.py <candidate-id>                  # run the lab, write receipts
python memory/scripts/evaluate.py --status                        # scan: expire stale candidates
python memory/scripts/promote.py promote <id> --reason "..."      # gate + promote
python memory/scripts/promote.py rollback --to <rule-set-id> --reason "..."
python memory/scripts/promote.py retire <name> --reason "..."
python memory/scripts/promote.py registry                         # print current + history
```

All lifecycle commands are append-only journal writes; dry-run flags preview without writing.

## Rejected Alternatives

### R1. Keep writing longterm directly; add evaluation as a post-hoc audit

Rejected: the issue's core demand is that a production rule NEVER exists before evaluation
(acceptance a). A post-hoc audit leaves a window where a bad rule is live and already injected
into prompts before anyone notices.

### R2. Store lifecycle state by rewriting the candidate file's frontmatter

Rejected: violates the "immutable candidate record" requirement and creates a tamper surface.
The journal-as-ledger keeps the file content-addressed and the state derivable from append-only
rows — the repo's established ledger idiom.

### R3. Score candidates inside the distill pipeline (self-evaluation)

Rejected: conflicts with #81's evaluator ownership (hidden oracle, separate scorer) and with
the project's maker-checker discipline. The gate must consume independently produced receipts,
never a score computed in the same process that generated the candidate.

### R4. Reuse staging/ as the candidate store

Rejected: staging is raw, mutable, claim-bound input; candidates are immutable, cross-project
artifacts with their own lifecycle. Mixing them breaks the existing threshold/snapshot
accounting and the immutability guarantee.

### R5. Rollback = re-promote the previous candidate

Rejected: re-promotion re-runs the gate and can be blocked by the gate itself (e.g. the
previous candidate expired). Rollback must restore the exact prior byte-level rule set from the
registry backup, independent of any gate.
