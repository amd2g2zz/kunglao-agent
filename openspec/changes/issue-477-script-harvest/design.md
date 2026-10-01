# Design — issue-477-script-harvest

## Context

#474 landed the online-distillation spine: the budget ledger
(`runs/distill-budget.json`, `distill-budget/1`, flock-guarded critical
section, engine-minted run identity, never-loosen clamp, fail-closed
corruption), the tier-1 run-local shelf (`<ws>/tools-local/` +
`<name>.manifest.json` provenance manifests), the anchored-sample oracle
(`bins/` single-file resolution), and the three-word audit vocabulary
pattern. The workspace ALSO accumulates worker-written scripts
(`scripts/` per the CLI-script discipline; `evidence/*.py` helpers) that
today evaporate at workspace discard. The worker doc already sorts them:
reusable logic is a parameterized CLI under `scripts/`, sample-specific
one-offs under `scripts/sample_specific/`. The fact base already ties
scripts to outcomes: a fact's frontmatter carries `status`, `claim_id`,
and a `provenance` list where "any script called from `reproduce:` MUST
be a provenance entry with `role: recompute_script`".

## Goals / Non-Goals

Goals: one extractor module (`scripts/script_harvest.py`) in the
online_distill engine shape; the success-trace discriminator from
workspace-native signals only; landing THROUGH the #474 spine (same
shelf, same ledger document, same fail-closed discipline); the playbook
chain record (owner-directed co-product); the three audit words; fixture
tests for candidate/one-off/archived.

Non-goals: runtime (in-run) harvesting; global-shelf writes; LLM acts;
fact-base mutation; the #478 playbook schema (a minimal record feeds it).

## Actual / Concrete Design Decisions

### D1 — the reusability discriminator (success-trace, mechanical)

Sweep scope: Python files under `<ws>/scripts/` (recursive, EXCLUDING
the declared one-off dir `scripts/sample_specific/`) and
`<ws>/evidence/*.py`, each with mtime at or after the RUN-START
timestamp the HOST supplies — in e2e the pipeline's own run-start
(`ctx.state.started_ts`), on the CLI face an explicit `--since`
argument. The #474 ledger's `run_started_ts` is NOT the scope floor
(review HIGH-1): it is engine-minted and only persisted by the first
ledger-writing event (a mid-run distill act), so using it would
misclassify early scripts as stale exactly in the richest runs. Ledger
interaction at sweep time: a MISSING ledger is the cold-workspace
normal — fresh defaults, floor 0.0, landing allowed under fresh
counters; a CORRUPT ledger reads exhausted — classification may run,
landing may not (fail-closed).

A swept script is a CANDIDATE iff at least one of two workspace-native
signals fires; otherwise it is a one-off (counted, skipped):

- **(a) Verified-outcome trace (the strongest)** — some `facts/F*.md`
  whose frontmatter `status` matches EXACTLY `PROVEN` or `VERIFIED`
  (set membership, never substring — `VERIFIED-BY-W<n>-<method>`
  worker-declared forms and the banned `PARTIALLY-VERIFIED` do NOT
  qualify; they can still qualify the script through arm (b)) cites the
  script's workspace-relative path: a `provenance` entry whose `path`
  equals the path (the `recompute_script` role is the canonical case,
  any role counts — the fact's integrity does not depend on the role
  label), OR the `reproduce` line contains it, OR the fact body
  mentions it. A PROVEN fact exists only after independent adversarial
  verification (maker-checker), so the citation is a verified-outcome
  trace by construction, never a self-declaration.
- **(b) Reuse trace — demand evidence** — a LATER worker act reused the
  script, where "later" means the referencing document's mtime is at or
  after the script's (worker statuses are heartbeated every ~20 s, so
  raw mtime ordering alone is cheap — the PREDICATE carries the weight)
  and the reference is outcome-bearing, mechanically:
  (i) a `runs/worker-status-*.md` whose final `status:` line is `done`
  and whose `artifacts:` deliverable list contains the script path; or
  (ii) the path is referenced by at least TWO independent later
  documents from the reference-scan set (`runs/worker-status-*.md`,
  `facts/F*.md`). A bare mention — including the failure protocol's
  `what_I_tried` references to crashed attempts — fires nothing.
- **Declared one-offs never sweep**: `scripts/sample_specific/` is the
  worker doc's DECLARED one-off dir — excluded at sweep, before any
  citation scan. Fact-anchored verify scripts (`runs/verify-fNNN.py`,
  the fact template's canonical recompute location) are OUTSIDE the
  sweep scope by definition: they recompute one fact for one verifier —
  the boundary is recorded here, the summary counts only the swept
  scope. An undeclared one-off (no signal anywhere) skips at
  classification with its skip recorded in the sweep summary.
- **Citation hygiene**: provenance paths compare exactly; body/reproduce
  and reuse scans match the workspace-relative path string within the
  document text. A script never cites itself; the harvest module's own
  outputs (`tools-local/`, `runs/harvest-*`) are excluded from the
  reference scan so a landed candidate cannot manufacture reuse for its
  source.

Rejected alternatives: an LLM "reusability judge" (a second LLM seat
for what the fact base already records mechanically — the owner's
fewer-but-precise ruling); a git-history signal (workspaces are not git
repos); an execution-log signal (no such log exists in the workspace
contract); a bare-mention reuse predicate (review HIGH-2 — gameable by
heartbeat mtimes and failure-protocol mentions; rejected).

### D2 — the E-path hosting (post-run extractor on the #474 spine)

The sweep is POST-RUN by definition (outcomes exist only after acts
land) and is hosted exactly where the #458 spine's E contract lives:

- **E2E host** — `scripts/e2e/checkpoints.py`: one `_harvest_scripts`
  step fired at the TOP of `finalize()` — every terminal path of the
  runbook (ALL-PASS / FAIL / BLOCKED / PARTIAL) sweeps exactly once,
  after the last checkpoint lands and BEFORE the report is built, so
  the harvest rows are inside the report's audit-trail summary
  (review LOW-17; the report's exit code, final status, and step
  statuses are never changed by the harvest). `_abort_contaminated`
  does NOT host the sweep: a contaminated workspace produces no
  artifacts worth landing and must not grow any. The step follows the
  #458 hosting pattern with ONE deliberate strengthening (review
  MED-6): the ENTIRE step body — engine resolution via
  `_load_repo_module(ctx.repo, "script_harvest")` INCLUDED — sits
  inside one fail-open cage (a harvest failure is one rate-limited
  warn; the report the harness owes is never disturbed). Row emission
  splits by face exactly as #458 does: the e2e host emits the three
  words through the NEW e2e audit convenience emitters from the
  engine's structured result; the engine never emits e2e rows itself.
- **Production face** — the engine CLI (`script_harvest.py <ws>
  --harvest [--since TS]`, plus a read-only `--scan`): the
  orchestrator's post-run face outside the e2e harness, mirroring
  online_distill's CLI posture; the CLI face emits the production rows
  via `kunglao_log` (the same three words, the 17-field schema), the
  engine module staying kunglao_log-capable exactly like online_distill.
- **Rejected hosts**: the SubagentStop closure (per-worker-stop is
  in-run — outcomes for the stopping worker's own scripts may not exist
  yet, and the closure's fail-open posture must never gain a
  subprocess-spawning face); a per-tick step (re-sweeps, budget churn,
  no outcome stability between ticks).

### D3 — the verification form (fixture byte-exact, staged-then-verified)

The pinned input is the workspace's ANCHORED SAMPLE — the same `bins/`
single-file resolution #474's oracle uses (zero or multiple files
without a resolvable anchor → verification is impossible → the
candidate is not landed; fail-closed, no invented input). Verification
is STAGE-THEN-VERIFY (review HIGH-4 — the verified artifact must BE the
landed artifact, because a `scripts/`-neighborhood run puts the script's
own directory on `sys.path` and hides sibling-import breakage the landed
`tools-local/` copy would hit):

1. Copy the candidate into the shelf FIRST: `tools-local/<name>.py`
   (0755, the name rule in D4).
2. Run `[sys.executable, <landed path>, <sample>]` as one bounded
   subprocess (the #474 timeout), cwd = the workspace (review MED-7 —
   an undeclared cwd would pin a digest from a context that never
   recurs), capture stdout. Require rc == 0 and non-empty stdout.
   Record `sha256(stdout)`.
3. Run it AGAIN, fresh subprocess, same cwd. Require the identical
   sha256.

Both runs agreeing byte-exact IS the fixture verification a post-run
harvest can honestly perform: the run's own anchored sample is the
pinned input, and the agreed digest is the pinned output — recorded in
the manifest (`fixture: {input, input_sha256, stdout_sha256, runs: 2,
cwd}`; review MED-8 — the input digest makes the promotion expectation
independent of path rebinding) so the promotion wave re-verifies against
a fixed expectation. Scope note (recorded honestly): e2e workspaces are
discarded, so the pin is re-verifiable only where the anchored input
persists — it is a promotion-wave expectation, not a live replay face.
On any failure (missing/unresolvable sample, rc != 0, empty stdout,
timeout, digest mismatch across the two runs) BOTH staged files are
removed and the candidate is archived — a record under
`runs/harvest-archive/<name>.json` carrying the script path, the
reason (rc + stderr tail; `argv-contract` when rc == 2 with usage
output — the designed-in false-negative class of flag-taking CLIs, acked
per review MED-12), and the digest evidence. The worker's own file is
never moved or mutated (the workspace stays byte-reproducible for the
audit; the archive RECORD is the trail).

Rejected alternatives: comparing against the citing fact's `expected`
sha (the fact oracle runs with cwd=facts/ and its own argument shape —
a mismatch would indict the fact's lane, not the script; the fact's
oracle stays the fact's own L1 face); a single run with output pinned
at first sight (no cross-run agreement = no determinism evidence);
verifying the SOURCE in place then landing a copy (review HIGH-4 —
verified ≠ landed); hashing produced artifact files on disk (the engine
cannot know which file a script wrote without a declared contract).

### D4 — the provenance schema (manifest + ledger + playbook + the name rule)

Landing reuses the #474 spine's write discipline and directory; the
fork from `land_candidate` is dispositioned (review MED-9):
`land_candidate`'s contract is report-driven (attempt_dir + report
entry + declared oracle) — harvest's oracle is an evidence-trace double
run, not a report declaration. The reuse is of the write discipline
(atomic tmp + os.replace + 0644), the directory (`tools-local/`), the
lock, and the ledger document; the adapter that would feed harvest
evidence through the distill report schema is rejected (it would couple
two evidence models through one schema string).

- **Name rule** (review HIGH-5): the shelf name is the script's stem,
  charset-normalized to the DISTILL shelf vocabulary — lowercase,
  underscores → hyphens (the worker's `<verb>_<object>.py` discipline
  maps to `<verb>-<object>.py`), repeats collapsed, edges trimmed, then
  validated against the distill name regex
  `[a-z0-9][a-z0-9-]{1,63}`; unnormalizable → not landable (archived,
  reason `bad-name`). One shelf, one name vocabulary. Collision rule:
  `tools-local/<name>.py` already existing under a manifest whose
  schema is NOT `harvest-manifest/1` → refuse landing (archived, reason
  `name-collision`) — a distilled tool is never silently overwritten;
  an existing `harvest-manifest/1` manifest for the same `source_path`
  → idempotent skip (already landed); same name but different
  `source_path` → archived, reason `name-collision`.
- **Manifest** — `<ws>/tools-local/<name>.manifest.json`, schema
  `harvest-manifest/1` (a DISTINCT schema string from the distill
  `distill-manifest/1` — a consumer must be able to tell the two
  landing faces apart): `name`, `source_path`, `description` (the
  script's module docstring first line, bounded 200 chars, null when
  absent), `capability` (free-form worker vocabulary: the first
  `shelf-miss:`-style token in the citing worker statuses, else null —
  expected null for verified-trace-only candidates, review LOW-16),
  `served_in` (the citing facts' titles, bounded — the honest "when
  has this served" surface; the when/when_not naming was rejected as a
  misnomer, review LOW-15), `signals`
  (`{verified_trace: [fact ids], reuse_trace: [paths]}`), `facts`
  (`[{id, claim_id, status}]` — which facts/claims the script served),
  `fixture` (D3's pin + the env-version stamp `{"python",
  "platform"}` — the O3 stamp field #474's design outlook reserves),
  `landed_ts`.
- **Budget ledger** — the SAME document `runs/distill-budget.json`
  (schema `distill-budget/1` untouched), harvest-owned counter fields
  following the established counter pattern: `harvest_budget` (default
  `HARVEST_LANDS_PER_RUN = 2`, per-run landing cap — module constants
  are the ceiling, stored values above clamp down, below are honored),
  `harvest_used`, and `global.harvest_landed` (lifetime observation,
  carried across re-init with `global`), under the same
  `_LedgerLock` critical section. Harvest type-checks its OWN counter
  fields (review MED-11): a ledger valid for distill but carrying
  type-garbage harvest counters reads harvest-exhausted (fail-closed,
  one warn) — never a crash, never a reset. The distill act/hop
  counters are NOT consumed (no LLM act occurs); the distill `landed`
  counter is NOT consumed (separate mechanisms keep separate counters —
  honest accounting in one document).
- **Playbook chain record** (owner-directed co-product, review MED-10
  dispositioned: the #477 card's product-stack comment requires the
  script→evidence→outcome chain as a playbook candidate explicitly —
  this is owner cover, not speculative generality) —
  `<ws>/runs/harvest-playbook.json`, schema `harvest-playbook/1`, one
  `chains[]` entry per landed candidate: `{script, capability_input,
  evidence[], outcome: {fact, claim_id, status}, landed_as}` — the
  script, the anchored input (path + sha), the evidence artifacts its
  citing facts carry (provenance paths other than the script itself),
  and the strongest citing fact as the outcome. Written only when at
  least one chain exists (an empty playbook file is noise, not a
  record); one file per workspace, re-written whole per sweep (the
  ledger write discipline). #478's schema, when it lands, consumes or
  supersedes this record.

### D5 — audit vocabulary (three words, one category)

`harvest_scan` (one row per sweep invocation: swept/candidates/skipped/
archived counts + the playbook path when written — the honest visibility
face, so a skipped one-off is never silent), `script_harvested` (one row
per classified candidate: signals + provenance; phase="archived" with
the reason when D3 refuses landing), `harvest_landed` (one row per
landed candidate: tool path + manifest). Category `harvest`. Both
vocabularies register all three (e2e/audit.py `AUDIT_ACTIONS` +
`CATEGORIES` + convenience emitters; event_taxonomy.EMIT_ACTIONS), the
#458 registration pattern. Note (review LOW-16): `script_harvested`
breaks the `harvest_` prefix — `audit._category` gets an explicit
equality rule alongside the `candidate_landed` precedent.

## Risks / Trade-offs

- **Post-run means post-discard for ephemeral runs**: the e2e harness
  stages and discards workspaces; the sweep fires inside the harness
  lifetime (finalize) so candidates exist to observe. Production runs
  get the CLI face. Honest residual: a workspace deleted before
  finalize loses its scripts — same exposure every workspace artifact
  has.
- **Docstring-first-line description can be junk**: bounded to 200
  chars, nullable; provenance facts carry the real semantics.
- **Double-run cost**: two bounded subprocess runs per candidate, ≤ 2
  candidates per run by budget — bounded and small.
- **argv-contract false negatives**: flag-taking argparse CLIs (the
  house discipline's own shape) exit rc 2 under the single positional
  contract and archive with the `argv-contract` reason — the trail
  says why, honestly (review MED-12).
- **Path-mention false positives**: the verified arm demands exact-set
  PROVEN/VERIFIED status; the reuse arm demands the done-line
  deliverable or two independent later documents — bare mentions fire
  nothing (review HIGH-2 fix); the fixture verification is the final
  mechanical arbiter before landing.

## Design-review record (adversarial, pre-test)

Verdict PASS-with-fixes; 5 HIGH + 8 MEDIUM + 4 LOW findings — ALL
applied to this design + the spec deltas (HIGH-1 scope floor → run-start
supply + ledger-missing semantics; HIGH-2 reuse predicate →
outcome-bearing, bare mentions fire nothing; HIGH-3 exact-set status
matching + VERIFIED-BY-* → arm (b) only; HIGH-4 stage-then-verify;
HIGH-5 name rule + collision rules; MED-6 whole-body cage + host-emitted
rows; MED-7 cwd declared; MED-8 input_sha256 + pin-scope note; MED-9
land_candidate fork disposition; MED-10 playbook owner-cover recorded;
MED-11 harvest counter type-garbage fail-closed; MED-12 argv-contract
reason; LOW-13 runs/ verify-script boundary; LOW-14 at-or-after reuse
ordering; LOW-15 served_in rename; LOW-16 category equality rule +
capability-null note; LOW-17 finalize insertion point pinned). Zero
tests before this record.
