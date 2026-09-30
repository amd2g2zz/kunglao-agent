# Design — issue-458-online-distillation

## Context

The dispatch loop (#459/#462) launches worker acts through three faces
(orchestrator/auto/dry) and lands every act in the unified 17-field
audit stream. The tool shelf is a fixed index (43 registered tools) the
worker reads semantically; the re-library is a batch-distilled reference
corpus; the quality bar (泛化+自启, references/contracts/distill-
pipeline.md) gates what may become a card. Missing: the runtime bridge —
when the shelf has no viable candidate, nothing measures the miss,
nothing retrieves, nothing lands.

## Goals / Non-Goals

Goals: the five organs of the proposal, each the smallest honest
mechanism; the trigger is the worker's semantic verdict (mechanically
parsed, never rules-matched); budgets are the only restraint face;
landing is tiered and the global shelf stays write-free at runtime.

Non-goals: capability aliasing of any kind; touching the kernel organs
(#462 architecture untouched — the distill act is a CONSUMER of the
dispatch faces, not a new sampler); promotion mechanics (the existing
gate is the promotion face); LLM/network in CI.

## Actual / Concrete Design Decisions

### D1 — which faces host the trigger (and which do not)

Two hosts, both where #462's dispatch/act wirings already live:

- **E2E host** — `scripts/e2e/checkpoints.py`, one `_maybe_distill`
  step per tick AFTER the dispatch wave lands. In dry/auto mode the
  act's report is on disk when the wave lands; in orchestrator mode
  the act lands a tick or more later — the scan runs EVERY tick, so
  the trigger fires on the first tick after the report exists (the
  lag is inherent to open-loop mode and the per-tick scan absorbs
  it). At most ONE distill act per tick; a synchronous single-act
  launch→execute→land chain that calls the LLM faces' own
  launch_dispatch/run_dispatch directly — NEVER `_launch_dispatch`
  (review HIGH-3): the #462 envelope sampler rides that seam, a
  distill act declares no method family, and #462's single-decision-
  source ruling allows the sampler's consumers to be kernel faces
  only — so no `method_family_recorded` row is ever emitted for a
  distill act and its dispatch rows never enter the measured
  proposal channel.
- **Production host** — `hooks/round_closure.py` (SubagentStop): #462
  D1 already ruled Stop(worker) the round-closure decision event and
  this hook already hosts the production kernel faces (compose + T2).
  At worker stop the report is complete on disk: the hook scans for
  the marker, checks the budget ledger, emits the trigger audit row,
  and stamps `runs/distill-trigger.json`. The ACT itself stays an
  orchestrator decision (the decision-rights matrix: dispatch is an
  LLM seat): the loop protocol (SKILL.md) documents the distill
  dispatch the trigger file calls for — the trigger file's production
  consumer is the orchestrator following that protocol (an advisory
  channel; the miss rate stays measurable from the stream), not a
  tick-read state file. The hook never blocks or disturbs the stop
  path (the #462 fail-open double-cage posture).
- **Rejected hosts**: `hooks/dispatch_gate.py` (PreToolUse) — the
  enforcement face for failure-blocked claims; the shelf-miss is not
  known at dispatch time (it is discovered by the worker DURING the
  act), so the gate cannot detect it, and #462 located no face there.
  A dedicated recall/inject hook — rejected: a second injection
  channel duplicates the tick's state-reading role.

### D2 — the budget ledger (the restraint ruling, as budgets)

`<ws>/runs/distill-budget.json`, schema `distill-budget/1`, the
mission_ledger counter pattern (whole-document replace, atomic
writer-unique tmp + os.replace + 0644, the #462 D6 write discipline):

```json
{
  "schema": "distill-budget/1",
  "run_id": "dstr-3f9c1a20",
  "run_started_ts": "2026-09-30T12:00:00Z",
  "per_run_budget": 2, "per_run_used": 1,
  "hops_budget": 12,    "hops_used": 4,
  "triggers": {"crypto:decode": "attempt-1",
               "format:unknown:evidence/die.json": null},
  "consumed_markers": ["runs/worker-status-C-004.md"],
  "global": {"acts": 1, "hops": 4, "landed": 1}
}
```

Semantics:

- **Run identity is engine-minted and monotone** (review HIGH-1): the
  ledger's `run_id` changes ONLY through an explicit engine-CLI re-init
  face that mints a fresh id (uuid/clock-derived) and resets the
  per-run counters. No caller-, session-, or workspace-supplied run id
  is ever trusted (a session resume or a worker-written file must not
  reset the counters); the SubagentStop host treats the ledger's
  existing `run_id` as current and never resets at the hook.
- `per_run_budget` — hard cap on distill acts per run (default
  `DISTILL_ACTS_PER_RUN = 2`); resets only at the re-init face.
- `hops_budget` — hard cap on discovery hops PER RUN (default
  `DISTILL_HOPS_BUDGET = 12`), resetting with `per_run_used` at the
  re-init face. `global.hops` is the lifetime OBSERVATION counter and
  caps nothing. A caps-legal report can still exceed the remaining
  hop budget (many roots × 3 branches) — that report rejects whole;
  the ledger, not the algebra, is the binding bound.
- `triggers` — per-run trigger memory keyed by trigger token: the
  marker's free-form capability token for (a), and a fixed implicit
  token `format:unknown:<evidence-file>` for (b) (the evidence file
  stays unknown the whole run — without a token the format trigger
  would re-fire every tick and every closure). A second trigger on an
  already-triggered token records a skipped duplicate, never a second
  act. The ledger also carries `consumed_markers` (the marker file
  paths already acted on) so a stale marker file from an earlier run
  cannot re-fire — and the scan only reads worker-status files whose
  mtime is ≥ the ledger's `run_started_ts` (belt and braces; trigger
  memory is the primary dedup).
- **Never loosened**: module constants are the CEILING. A stored
  budget above the default clamps down to the default at load; a
  stored budget below it is honored (tightening is always legal).
  There is no env/config face that raises a cap.
- **Fail-closed**: an unreadable or corrupt ledger reads as
  exhausted; the trigger emits its refusal as a `distill_result` row
  with `phase="refused"` and the reason (`budget_ledger_unreadable`)
  — the three-word vocabulary stays exactly three (no refusal word
  is minted), and refusals key to the trigger, never to a dispatched
  act. Distillation is the optional capability — corruption must not
  open the floodgate.
- **Concurrency** (review MEDIUM-2): the read-check-debit-write
  critical section runs under a workspace-scoped `fcntl.flock` on a
  sibling lockfile — `os.replace` gives atomicity (no torn file), not
  mutual exclusion, and concurrent SubagentStop processes can both
  run the faces (#462 D6 context); the lock closes the lost-update
  race that would overspend the caps.
- Threat model (review MEDIUM-7): the ledger restrains honest
  mistake-frequency, not a hostile act — the distill act (and any
  worker) holds workspace write access and could edit or delete the
  ledger (reset `per_run_used`, rotate `run_id`, zero the budget).
  ANY ledger edit by an in-workspace writer is inside the accepted
  risk; per-run defaults bound the damage of a forged reset, and the
  caps are guarantees against error, not against in-workspace
  writes.

### D3 — the trigger marker contract (semantic verdict, mechanical parse)

Two triggers, both honest miss signals, both mechanical detections in
the engine (single source: `scripts/online_distill.py`):

- **shelf-miss marker** — a line in `runs/worker-status-*.md`:
  `shelf-miss: <capability-token> [sample=<relpath>]`. The token is
  free-form (the worker's own vocabulary — deliberately NOT a
  registry lookup, per the rules-based rejection); the optional
  sample path is a HINT the oracle validates against the anchored
  sample (D5), never a trust anchor itself. The scan reads only
  worker-status files whose mtime is ≥ the ledger's `run_started_ts`
  and skips files in `consumed_markers` (review MEDIUM-3: a stale
  marker from an earlier run must not re-fire into the fresh run's
  budget); the per-run trigger memory is the primary dedup.
- **unknown-format probe failure** — reading the evidence shape of
  the REAL producers (review HIGH-4 — the shapes are pinned to the
  producing tools, not invented): `evidence/die.json` counts as
  unknown-format ONLY when it is present and usable (at least one
  DIE call produced a data block) AND its `derived.language` is
  null/falsy (the producer's undetected encoding — `null`, never a
  literal "unknown" string); `evidence/apkid.json` counts ONLY when
  `status == "ok"` AND `findings` is empty (an operational
  `status: "error"` is an infra failure, not a miss — no-signal, per
  the never-infer rule). Detection never re-runs a probe. The
  implicit trigger token is `format:unknown:<evidence-file>` so the
  per-run trigger memory dedupes it like any marker (review
  MEDIUM-4).

No other trigger exists. A missing marker file, a probe operational
error, or a missing evidence file is the honest no-signal (pinned
negative test) — the engine never infers a miss from claim failure,
timeouts, or tool exit codes.

### D4 — the distillation act (bounded, methodology-first)

The act is ONE dispatched LLM act through the EXISTING faces with a
reserved identity (review LOW-2): `DispatchRequest.agent =
"kunglao-distill"` and `claim = "distill-<attempt-n>"` — a reserved
non-register id space that never enters the claim register, the
ranker, or the `dispatched` set of analysis claims. The e2e host
calls `face.launch_dispatch(req)` / `face.run_dispatch(req, handle)`
DIRECTLY (never `_launch_dispatch`: that seam rides the #462 DTS
  envelope sampler, whose consumers the kernel-actuation spec
restricts to kernel faces — review HIGH-3 — and whose sampled family
would pollute the measured proposal channel). One described change
to the auto face (review MEDIUM-5): `AutoLlmFace.run_dispatch`
derives `--allowedTools` from the request's declared tools rack (the
envelope already carries `tools`), defaulting to today's list when
the rack is the default — distill requests declare a
WebSearch-inclusive rack, every existing request keeps its
byte-identical rack. The prompt file carries the contract; in
orchestrator mode the request file is emitted as-is. The contract,
enforced by the engine on the act's REPORT (never trusted from the
act's self-declaration alone):

- **Retrieval order** — local re-library first (references/re-library/
  incl. case-distilled + osint + formats), THEN web search. Every
  source is recorded: relibrary refs must RESOLVE to real repo files
  (the engine checks existence — a fabricated local citation rejects
  the report); web refs must carry URL + access date and are marked
  advisory (never directly PROVEN — the repo idiom).
- **Method extraction** — the report carries `methods[]`: the
  methodology extracted from imperfectly-matched sources (decision
  rules, branch tables, mental models), case specifics discarded.
  Mechanical floor: ≥ 1 method (absence = rejection; the quality
  JUDGMENT stays with the post-run gate — the engine only enforces
  the shape).
- **Recursive case expansion caps** — a hop is `{root, branch,
  verified_against}`: case A (a root source) mentions tool B /
  dataset C (a branch source), verified against the sample. HARD
  caps, validated on the report: DEPTH 1 — a branch may never serve
  as another hop's root (no chains); BREADTH 3 — at most 3 branch
  hops PER ROOT (the number of roots is uncapped by the algebra; the
  ledger's remaining per-run hop budget is the binding total bound —
  a caps-legal report over many roots can still exceed it and then
  rejects whole); every hop spends one hop-unit. A report violating
  any cap or the remaining budget is rejected whole (its candidates
  never reach the oracle); the rejection is the distill_result row.

Report shape: `runs/distill-candidates/attempt-<n>/report.json`
(schema `distill-report/1`: trigger echo, sources, hops, methods,
candidates[{name, file, capability, oracle{args, expect_rc,
expect_stdout_contains}}]).

### D5 — sample-as-oracle (the engine runs the anchored bytes)

The engine — never the act — resolves the oracle sample from the
workspace's ANCHORED sample face first (review HIGH-2): the
workspace's declared analysis material (task_spec's target/bins
anchor — the sha-pinned sample the run is about), never the
marker's `sample=` hint as a trust anchor. The hint is VALIDATED
against the anchor (mismatch = recorded no-oracle, no landing). An
anchorless workspace (no declared material) falls back to the
guarded marker path — a workspace-containment path guard only — and
the fallback is marked in the audit row (`sample_source:
"marker-fallback"`); the honest face (`sample_source:
"anchored"`) is the default. A manifest-supplied sample path is
never trusted — the engine injects the resolved one. The engine
executes each candidate as a bounded subprocess against those bytes
and records per candidate: rc, stdout sha256 + tail, expect-
conformance, the resolved sample's sha256. No oracle run (no
resolvable sample, subprocess failure, timeout) = no landing,
outcome recorded honestly.

Honesty bound (review MEDIUM-6): the oracle's EXPECTATIONS are
self-declared by the same act that authored the candidate — the
engine verifies mechanical conformance (declared rc, stdout marker,
non-empty output) against the anchored bytes and records
`oracle_self_declared: true` on every tier-1 landing (manifest +
audit row); the oracle makes landing MECHANICALLY WITNESSED against
the anchored sample, not semantically earned — semantic quality
stays with the post-run promotion gate, and the manifest carries
the sample sha256 so promotion can re-verify independently.

### D6 — landing tiers

- **Tier 1 (runtime, this change)** — a candidate whose oracle
  satisfied lands in `<ws>/tools-local/<name>.py` with
  `<name>.manifest.json` (name, capability, attempt, sources, hops,
  methods, oracle outcome, landed_ts): usable immediately in-run
  (the worker doc points workers at tools-local/ alongside the
  shelf). The audit row `candidate_landed` carries tool + attempt.
- **Tier 2 (post-run, EXISTING face)** — promotion to the global
  shelf goes through the standing distill quality gate (泛化+自启)
  as a wave task reading the landed manifests; the engine exposes NO
  write face to tools/ or references/ — a runtime global write is
  impossible by construction, not by convention.

### D7 — audit vocabulary and streams

Three words — `distill_attempt`, `distill_result`, `candidate_landed`
— registered in BOTH vocabularies where #457/#462 established them:
`e2e/audit.py` (AUDIT_ACTIONS + a `distill` category bucket; the e2e
loop's rows) and `event_taxonomy.EMIT_ACTIONS` (kunglao_log; the
production hook's and engine CLI's rows). Row semantics (review
MEDIUM-1):

- `distill_attempt` — emitted when an act DISPATCHES (detail
  `phase="dispatched"`). The production closure's trigger signal
  also rides this word with `phase="triggered"` — an explicitly
  exempted signal face (the production act is the orchestrator's
  decision and may never follow; a triggered row therefore does not
  imply a result row, and the row's detail says so).
- `distill_result` — exactly one per DISPATCHED attempt (validation
  + oracle outcome, rejections included). Budget refusals are NOT
  result rows of acts (nothing dispatched) — a refusal rides
  `distill_result` with `phase="refused"` keyed to the trigger.
- `candidate_landed` — exactly one per landed candidate.

Because the act dispatches through the standard faces, its
`dispatch_attempt`/`dispatch_result` pair ALSO lands (the existing
unconditional face rows) — the exactly-one guarantee is per
distill-vocabulary word, alongside that standard pair, and both
sides are pinned. The capability token rides `detail.capability`
(never the `arm` field — review LOW-3: arm stays the attribution
arm and stays null for distill rows); `tool`/`artifact` carry the
landed tool path / the report path.

### D8 — dry-face honesty boundary

In dry mode the distill act's CONTENT is scripted (the dry responder
writes a real report + a REAL working candidate implementing the
re-library method), but the trigger scan, budget algebra, report
validation, oracle execution, and landing all run the REAL engine
code paths. The candidate is a genuine parameter-recovery decoder
(anchor-differential + period detection), not a stub that always
passes — the fixture's oracle satisfaction is earned on real bytes.

## Fixture substrate (constructed, repo-safe)

- `tests/fixtures/distill-458/make_fixture.py` — generator: a tiny
  synthetic binary (magic + structured payload, ~512 B) encrypted
  with `c[i] = ((p[i] ^ K[i mod 8]) + i) & 0xFF` (periodic XOR +
  position add — genuinely absent from crypto-tool's 8 algorithms;
  verified against xor-add (backward data-chained) and rolling-xor
  (32-bit state)). Zero real-sample bytes; committed artifact is the
  generator + its output + expected plaintext digest.
- `references/re-library/patterns/decode/byte-transform-id.md` — the
  methodology card (house format, English, zero provenance noise):
  unknown byte-transform identification via anchor-differential key
  recovery, period detection, bounded parameter search, structural
  verification. General: no fixture constants in the card.

## Risks / Trade-offs

- Marker discipline is worker-side (a worker that improvises without
  reporting the miss is invisible) — accepted: the marker is a
  documented worker contract, same shape as the W-15 status-first
  rule; the audit stream keeps the miss rate measurable.
- Dry-mode retrieval content is canned — accepted and documented
  (D8); auto/orchestrator modes carry the real act.
- The ledger restrains mistake-frequency, not a hostile act: ANY
  edit (delete, reset, rotate run_id, zero the budget) by an
  in-workspace writer is inside the accepted risk — the ledger is
  advisory against workspace writers, per-run defaults bound a
  forged reset's damage, and `global` observes frequency for the
  restraint ruling without being tamper-proof.
- Tier-1 landing is mechanically witnessed, not semantically earned
  (D5): a tautological candidate can land run-local; the anchored-
  sample sha256 on every manifest + the `oracle_self_declared` flag
  keep the promotion face honest, and tier-1 never reaches the
  global shelf.

## Alternatives Considered

- Rules-based trigger (capability keywords → distill) — REJECTED by
  owner ruling (same-day): the alias-table disease; the worker's
  semantic verdict is the only honest miss signal.
- Restraint as prohibition (distill only in batch waves) — REJECTED:
  the owner ruling asks for ONLINE capability; restraint survives as
  the D2 budgets.
- Direct runtime write to tools-local only, no oracle — REJECTED:
  unverified candidates landing in-run is exactly the persuasion
  surface the evidence discipline forbids; the oracle is the
  difference between earned and asserted.
- A per-claim distill claim type in the ranker — REJECTED: the ranker
  ranks ANALYSIS claims; distillation is a capability act with its
  own budgets, not a competing value claim (no second decision
  source, #462's single-source ruling extended).

## Design outlook (owner research directive, 2026-09-30 — planned transitions, not retrofits)

Four findings from the skill-distillation/self-evolution literature review
(ASI, Code2Skill, ACE, Alita, MCP-Zero, plus a cost-accounting critique)
pin where this capability heads next. Each is recorded HERE so it is a
planned transition, never a surprise retrofit:

- **O1 — skills-as-code preference.** An induced candidate prefers
  EXECUTABLE form (script/tool) over prose method notes: executable,
  verified skills beat text memory (ASI/Voyager's central result). This
  design already lands code — `tools-local/<name>.py` is the deliverable
  and the manifest's `methods[]` prose is provenance/metadata, not the
  product. The standing rule going forward: a prose-only method note is
  second-class and lands only when no code form is possible (the
  validator may later REQUIRE an executable candidate for tiers that
  have one).
- **O3 — version-stamps + drift re-audit.** Every shelf entry —
  including newly landed run-local candidates — should carry
  environment-version stamps (dependency surface, platform surface);
  drift detection (the #467 deploy-gate pattern) triggers re-audit, and
  a stale entry is DEMOTED, not deleted (demotion keeps the audit trail
  and the posterior history). The tier-1 manifest already carries the
  oracle outcome + sample sha256; the version stamps are the next
  manifest field.
- **O4 — deprecation by cost.** A candidate that keeps getting selected
  and keeps losing (posterior negative) RETIRES (PARK-style) instead of
  bloating the shelf — retrieval-counted cost. The #461 posterior
  machinery shape is the intended reuse; the budget ledger's global
  counters are already the raw selection/landing signal this would
  consume.
- **O5 — visibility→retrieval threshold.** Full-shelf visibility (the
  43 one-liners read by the LLM worker) is fine at today's size, but
  THIS capability is what starts the shelf growing (every landed
  candidate is a future retrieval candidate). Planned transition: past
  a stated threshold (order 100 entries), the full-index read switches
  to posterior-ranked semantic retrieval (ASI's retrieval face). The
  marker contract is unchanged — the worker still reports the semantic
  miss; only the shelf-reading face changes.

Adjacent awareness (out of scope here): post-run workspace script
harvesting (separate card) will feed the SAME run-local landing surface
this change builds; `land_candidate` + the manifest shape are the
generic landing API — a second producer must reuse them, not fork them.

## Design-Review Dispositions (openspec gate, 2026-09-30)

The adversarial design review (independent subagent, vs the #462
kernel-actuation change, the round-closure hook, the e2e faces, the
evidence/facts discipline, die_probe/apkid producers, and the crypto
algorithm set) returned PASS with fixes required — no CRITICAL, no
redesign. All findings are dispositioned in place:

- HIGH-1 (production run identity undefined / spoofable) — FIXED:
  D2 run identity is engine-minted and monotone; only the explicit
  re-init face resets per-run counters; the SubagentStop host never
  resets at the hook.
- HIGH-2 (marker sample path trust hole) — FIXED: D5 resolves the
  oracle sample from the anchored sample face; the marker hint is
  validated against it; anchorless fallback is guarded and marked in
  the audit row.
- HIGH-3 (riding `_launch_dispatch` would make the #462 sampler a
  non-kernel consumer and pollute the proposal channel) — FIXED: D1/
  D4 the e2e host calls the faces directly, never `_launch_dispatch`;
  no `method_family_recorded` row for distill acts.
- HIGH-4 (probe-evidence shape invented: die.json "language/key/
  unknown", "apkid-prescan candidates" match no producer) — FIXED:
  D3 pins the real shapes — die.json `derived.language` falsy on a
  usable report; apkid.json `status=="ok"` with empty findings;
  operational errors are no-signal.
- HIGH-5 (hops budget scope undefined; the "≥ any single act"
  invariant false) — FIXED: D2 hops_budget is per-run; global.hops is
  observation-only; the false parenthetical replaced by the actual
  rule (a caps-legal report can exceed the remaining budget and then
  rejects whole).
- MEDIUM-1 (exactly-one inconsistencies: refusal word, production
  signal rows, dispatch twins) — FIXED: D7 refusals ride
  distill_result(phase="refused") keyed to the trigger; the
  production `phase="triggered"` signal row is an explicit exemption
  (act optional); the guarantee is per distill-word alongside the
  standard dispatch pair.
- MEDIUM-2 (os.replace is not mutual exclusion; concurrent
  SubagentStop can overspend) — FIXED: D2 flock-guarded critical
  section.
- MEDIUM-3 (stale markers re-firing into fresh runs) — FIXED: D3
  mtime ≥ run_started_ts filter + consumed_markers ledger list.
- MEDIUM-4 (format trigger has no dedup token) — FIXED: D3/D2 the
  implicit token `format:unknown:<evidence-file>`.
- MEDIUM-5 (auto face hardcodes allowedTools without WebSearch) —
  FIXED: D4 the described change — AutoLlmFace derives --allowedTools
  from the request rack, default byte-identical; distill requests
  declare the WebSearch-inclusive rack.
- MEDIUM-6 (self-declared oracle expectations; "earned" overstated)
  — FIXED: D5 `oracle_self_declared: true` on every tier-1 landing,
  anchored-sample sha256 in the manifest, claim softened to
  "mechanically witnessed".
- MEDIUM-7 (risk statement covered deletion only) — FIXED: D2
  threat-model paragraph + Risks rewrite (any ledger edit by an
  in-workspace writer is inside the accepted risk).
- MEDIUM-8 (genuine-miss discriminator undefined) — FIXED: the spec
  scenario now pins the discriminator — no registered subcommand,
  over its documented parameter space as pinned by the test,
  reproduces the fixture's expected plaintext digest/magic header.
- LOW-1 (two false D1 seam claims: post-act report timing; trigger
  file consumer) — FIXED in D1 (orchestrator-mode lag absorbed by
  the per-tick scan; the trigger file's consumer is the orchestrator
  per the SKILL.md protocol, an advisory channel).
- LOW-2 (claim id space unspecified) — FIXED: D4 the reserved
  `distill-<attempt-n>` id space, never in the register/ranker.
- LOW-3 (arm field overload) — FIXED: D7 the token rides
  detail.capability; arm stays null.
- LOW-4 (worker-doc visibility unpinned) — FIXED: the landing
  requirement gains the worker-documentation scenario (pinned by a
  doc test).

Clean non-findings recorded by the review: the spec delta is
ADDED-only for a new capability (no existing spec modified; the
vocab additions follow the #459/#462 additive registration
discipline; the 43-tool index is untouched); the kernel organs
(compose single-point, ranker, #432 vocabulary) are untouched; the
web-evidence discipline (URL+date, advisory, never-directly-PROVEN)
matches the established idiom; no runtime write face to tools/ or
references/ exists.
