# issue-477-script-harvest — spec delta: script-harvest

## ADDED Requirements

### Requirement: The harvest sweep is post-run, scoped, and mechanically discriminated

The system SHALL provide exactly one harvest entry point — the
`script-harvest` engine module (`scripts/script_harvest.py`) — whose
sweep collects Python scripts written during the run: files under
`<ws>/scripts/` (recursive, EXCLUDING the declared one-off dir
`scripts/sample_specific/`) and files matching `<ws>/evidence/*.py`,
each with mtime at or after the RUN-START timestamp the host supplies
(the e2e host passes the pipeline's own run-start; the CLI face takes
an explicit `--since`). The #474 ledger's `run_started_ts` SHALL NOT
scope the sweep (it is engine-minted and only persisted by the first
ledger-writing event — a mid-run distill act). Ledger interaction: a
MISSING ledger is the cold-workspace normal (fresh defaults, landing
allowed under fresh counters); a CORRUPT ledger reads exhausted —
classification may run, landing may not (fail-closed). A script SHALL
be classified a CANDIDATE when at least one of:

(a) a fact file `facts/F*.md` whose frontmatter `status` matches the
exact set `PROVEN`/`VERIFIED` (set membership, never substring —
worker-declared `VERIFIED-BY-*` forms and workflow states do not
qualify this arm) cites the script's workspace-relative path (a
`provenance` entry `path`, the `reproduce` line, or the body text);

(b) a LATER act reused it, outcome-bearing: a
`runs/worker-status-*.md` whose mtime is at or after the script's AND
whose final `status:` line is `done` with the path in its `artifacts:`
deliverable list, OR the path referenced by at least TWO independent
later documents (mtime at or after the script's) from
`runs/worker-status-*.md` and `facts/F*.md`. A bare mention — a single
passing reference, including failure-protocol `what_I_tried` notes —
SHALL fire nothing.

Every other swept script SHALL be classified a one-off: counted in the
sweep summary, never landed, never mutated. The sweep SHALL be
idempotent: a script whose `source_path` already appears in an existing
`harvest-manifest/1` manifest under `tools-local/` SHALL NOT re-land in
a second sweep of the same workspace.

#### Scenario: PROVEN-fact citation classifies a candidate

- **WHEN** `<ws>/scripts/so_disasm.py` exists, its mtime is at or after
  the host-supplied run-start, and `facts/F007-x.md` with frontmatter
  `status: PROVEN` carries a provenance entry whose `path` is
  `scripts/so_disasm.py`
- **THEN** the sweep classifies it a candidate with the
  verified-outcome signal and provenance rows `[{id: F007-x,
  claim_id: <the fact's claim_id>, status: PROVEN}]`

#### Scenario: deliverable-line reuse classifies a candidate

- **WHEN** a worker status file whose mtime is at or after the script's
  ends with a final `status: done` line whose `artifacts:` list
  contains `scripts/foo.py`
- **THEN** the sweep classifies the script a candidate with the reuse
  signal, carrying the referencing path

#### Scenario: bare mention fires nothing

- **WHEN** a single worker status (mtime at or after the script's)
  references `scripts/foo.py` in prose or a `what_I_tried` step, with
  no done-line deliverable reference and no second referencing document
- **THEN** the script is skipped as a one-off and counted in the sweep
  summary

#### Scenario: worker-declared verified form does not arm (a)

- **WHEN** a citing fact's frontmatter `status` is
  `VERIFIED-BY-W3-static_re`
- **THEN** the verified-outcome arm does not fire for it (exact-set
  matching); the fact still counts as a referencing document for the
  reuse arm

#### Scenario: no citing document means one-off

- **WHEN** a swept script is referenced by no fact and no qualifying
  later worker status
- **THEN** it is skipped as a one-off, and the sweep summary counts it

#### Scenario: declared one-off dir never sweeps

- **WHEN** a script sits under `scripts/sample_specific/`
- **THEN** it is excluded from the sweep entirely, whatever cites it

#### Scenario: stale script is out of scope

- **WHEN** a script's mtime predates the host-supplied run-start
- **THEN** the sweep skips it

#### Scenario: missing ledger is cold-workspace normal, corrupt is fail-closed

- **WHEN** `runs/distill-budget.json` does not exist
- **THEN** the sweep runs with fresh default counters and landing is
  allowed; **WHEN** the ledger exists but is unreadable/type-garbage
  **THEN** classification may run but landing is refused (harvest
  reads exhausted, fail-closed)

### Requirement: Fixture verification is a staged double-run byte-exact pin on the anchored sample

A candidate SHALL be verified before any landing, STAGE-FIRST: the
engine copies the script into the run-local shelf
(`tools-local/<name>.py`, the D4 name rule) and verifies the LANDED
copy, so the verified artifact IS the landed artifact. The pinned input
is the anchored sample resolved from `<ws>/bins/` (the single file
there; no resolvable anchor → verification impossible → no landing;
fail-closed, no invented input). The engine then runs
`[sys.executable, <landed path>, <sample>]` as a bounded subprocess
with cwd = the workspace, twice, fresh subprocess each time.
Verification SHALL pass only when BOTH runs exit rc 0, both produce
non-empty stdout, and both runs' stdout sha256 digests are IDENTICAL
(the byte-exact pin). On any failure (missing script or sample, rc != 0,
empty stdout, timeout, digest mismatch) BOTH staged files SHALL be
removed, an archive record under `runs/harvest-archive/<name>.json`
SHALL carry the script path and the reason (observed rc + stderr tail;
`argv-contract` when rc == 2), and nothing SHALL land; the worker's
script file itself SHALL NOT be moved or mutated.

#### Scenario: deterministic script verifies and pins

- **WHEN** the landed candidate prints the same non-empty bytes on two
  runs against the single anchored sample with rc 0
- **THEN** verification passes and the agreed digest is pinned as
  `fixture: {input, input_sha256, stdout_sha256, runs: 2, cwd}` in the
  landing manifest

#### Scenario: nondeterministic script is archived, not landed

- **WHEN** the candidate's two runs produce different stdout digests
  (e.g. an embedded timestamp)
- **THEN** the staged files are removed, no landing occurs,
  `runs/harvest-archive/<name>.json` records the digest-mismatch
  reason, and the worker's script file is unchanged

#### Scenario: failed run is archived with the observed reason

- **WHEN** the landed candidate exits rc != 0 against the anchored
  sample (rc 2 with usage output = the argv-contract class)
- **THEN** nothing lands, the archive record carries the rc and stderr
  tail (`argv-contract` for rc 2), and the worker's script file is
  unchanged

#### Scenario: no anchored sample means no landing

- **WHEN** `<ws>/bins/` is absent or holds no resolvable single sample
- **THEN** the candidate is not verified and not landed (fail-closed)

### Requirement: Landing rides the #474 spine with harvest-owned budget counters

A verified candidate SHALL land in the run-local shelf exactly as the
online-distillation spine does — `tools-local/<name>.py` (0755) plus
`tools-local/<name>.manifest.json` — where the manifest (schema
`harvest-manifest/1`) carries `name`, `source_path`, `description`,
`capability`, `served_in`, `signals` (which D1 arm fired), `facts`
(`[{id, claim_id, status}]`), `fixture` (the D3 pin + the env-version
stamp `{"python", "platform"}`), and `landed_ts`. The shelf name SHALL
be the script's stem normalized to the distill name vocabulary
(lowercase, underscores → hyphens, validated against
`[a-z0-9][a-z0-9-]{1,63}`; unnormalizable → archived, reason
`bad-name`). Landing SHALL be refused — archived, reason
`name-collision` — when `tools-local/<name>.py` already exists under a
manifest whose schema is not `harvest-manifest/1` (a distilled tool is
never overwritten) or when the same name maps a different
`source_path`. Landing SHALL debit harvest-owned counters in the SAME
budget ledger document `runs/distill-budget.json`: `harvest_budget`
(default 2, per-run cap — module constants are the ceiling, stored
values above clamp down, below are honored), `harvest_used`, and
`global.harvest_landed`, under the same flock-guarded critical
section; harvest SHALL type-check its OWN counter fields and read
exhausted on type-garbage (fail-closed, never a crash, never a reset).
The distill act/hop/landed counters SHALL NOT be consumed. There SHALL
be NO global-shelf write face: nothing under `tools/` or `references/`
is ever written at harvest time.

#### Scenario: verified candidate lands run-local with provenance

- **WHEN** the candidate passes fixture verification with budget
  remaining
- **THEN** `tools-local/<name>.py` + `<name>.manifest.json` exist, the
  manifest's `facts` rows name the citing facts and their claims, and
  the audit stream carries one `harvest_landed` row with the tool path

#### Scenario: exhausted harvest budget refuses without landing

- **WHEN** `harvest_used` already equals `harvest_budget` (or the
  ledger reads exhausted, or the harvest counters are type-garbage)
- **THEN** no landing occurs for further candidates and each refusal
  is recorded (archived record + the sweep summary), never silent

#### Scenario: name collision with a distilled tool refuses

- **WHEN** `tools-local/<name>.py` exists under a `distill-manifest/1`
  manifest and a harvested script normalizes to the same name
- **THEN** landing is refused, the harvest candidate is archived with
  reason `name-collision`, and the distilled tool is untouched

#### Scenario: no global shelf write

- **WHEN** any number of candidates land
- **THEN** the repo `tools/` and `references/` trees are unchanged
  (static pin)

### Requirement: The successful chain exports as a playbook candidate record

When at least one candidate lands, the engine SHALL write
`<ws>/runs/harvest-playbook.json` (schema `harvest-playbook/1`) whose
`chains[]` records, per landed candidate: the `script` (source path),
`capability_input` (the anchored input path + sha256), `evidence[]`
(the evidence artifacts the citing facts carry — their provenance paths
excluding the script itself), `outcome` (`{fact, claim_id, status}` —
the strongest citing fact), and `landed_as` (the tools-local path). The
record SHALL be written with the ledger write discipline (atomic
whole-document replace) and SHALL be absent when no chain exists.

#### Scenario: chain record captures script-evidence-outcome

- **WHEN** a candidate citing `facts/F007-x.md` (provenance paths
  `scripts/so_disasm.py`, `evidence/dump.txt`) lands
- **THEN** `harvest-playbook.json` carries one chain: script
  `scripts/so_disasm.py`, evidence containing `evidence/dump.txt`,
  outcome `{fact: F007-x, claim_id: ..., status: PROVEN}`, landed_as
  the tools-local path

#### Scenario: no candidates means no playbook file

- **WHEN** a sweep classifies zero candidates
- **THEN** `runs/harvest-playbook.json` is not written

### Requirement: Harvest rides both audit vocabularies with three words

The capability SHALL register exactly three new actions —
`harvest_scan` (one row per sweep invocation: swept / candidates /
skipped / archived counts + the playbook path when written),
`script_harvested` (one row per classified candidate: signals +
provenance; `phase: "archived"` with the reason when verification
refuses), `harvest_landed` (one row per landed candidate: tool path +
manifest) — in the unified 17-field stream under BOTH vocabularies
(e2e `AUDIT_ACTIONS` + the `harvest` category + convenience emitters
the e2e HOST calls with the engine's structured result;
`event_taxonomy.EMIT_ACTIONS` for the production CLI face), following
the #458 registration pattern where each face emits through its own
stream.

#### Scenario: the three words ride both vocabularies

- **WHEN** the vocabulary modules are imported
- **THEN** all three words appear in e2e `AUDIT_ACTIONS` and
  `event_taxonomy.EMIT_ACTIONS`, and categoryize under `harvest`

#### Scenario: a full sweep leaves a complete audit trail

- **WHEN** a sweep classifies 1 candidate + 1 one-off and lands the
  candidate
- **THEN** the stream holds exactly one `harvest_scan` row (skipped
  count 1), one `script_harvested` row, one `harvest_landed` row, each
  with the 17-field schema

### Requirement: The e2e spine hosts the sweep post-run, fail-open

The e2e pipeline (`scripts/e2e/checkpoints.py`) SHALL invoke the
harvest exactly once per run at the top of `finalize()` — after the
last checkpoint lands, before the report is built (the harvest rows
land inside the report's audit-trail summary), on every terminal path
except the contamination-abort path. The host SHALL pass the pipeline's
own run-start timestamp as the sweep scope floor. The step's ENTIRE
body — engine resolution included — SHALL sit inside one fail-open
cage: a harvest failure is one rate-limited warn and NEVER changes the
run's exit code, final status, or checkpoint step statuses.

#### Scenario: harness terminal path sweeps once

- **WHEN** the pipeline reaches finalize on an ALL-PASS run whose
  workspace holds a success-traced script
- **THEN** the sweep runs once and the candidate lands before the
  report is written

#### Scenario: harvest failure never breaks the harness

- **WHEN** the harvest engine raises inside finalize
- **THEN** the report is still written, the exit code and final status
  are unchanged, and the failure is one rate-limited warn

#### Scenario: contaminated workspace never sweeps

- **WHEN** staging detects contamination and the run aborts
- **THEN** no harvest sweep runs and no harvest rows exist
