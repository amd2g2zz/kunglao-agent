# design — issue-234-obstacle-ladder

## Verified anchors (2026-09-18, worktree @ 6e8cec2)

| Issue says | Actual | Drift |
|---|---|---|
| `failure_analysis_gate.py:579` one-liner statement | `"statement": f"Obstacle (from {claim_id}): {obstacle_text[:160]}"` | none |
| `failure_analysis_gate.py:577` promotion_attempts seeded, never incremented | `"promotion_attempts": 0,` in `_promote_obstacle_claim`; repo-wide grep: zero increment sites (only readers: dead_letter.scan, worker_budget_gates.check_promotion_attempts, convergence_check._dispatched_ids, ask_for_direction_gate.find_ladder_exhaustion) | none |
| `ask_for_direction_gate.py:588-589` tool-failure-shaped ladders | method-ladder print at :590, env-ladder at :594 (REJECT Type D-blocker branch) | minor (same block) |
| `_promote_obstacle_claim:570-586` construction | function spans 549-609; the cited window is the new-claim dict | minor |

## Module: scripts/target_ladder.py (new, ~250 lines)

Rides the ladder primitive as vocabulary — no new orchestrating organ.

### Data

- `TARGET_LADDER_LEVELS = ("T1", "T2", "T3")` — mirrors
  `infeasible_proposal.LADDER_LEVELS` shape.
- `OBSTACLE_CLASS_FAMILIES` — obstacle class -> mechanism-family enumeration
  (tuple = the class's family pool, ordered):
  - `interception`: hooking, repackaging, ca-install, proxy-interposition
    (issue #234 example, verbatim);
  - `visibility`: static-unpacking, dynamic-tracing, memory-imaging;
  - `execution`: native-execution, emulation, instrumented-runner.
- `FAMILY_FALLBACK` — surface-pivot, mechanism-substitution,
  environment-reconstruction. Unknown/absent class falls back (fail-open):
  the ladder must never be unwalkable because a class string did not match,
  exactly like instrument availability annotates but never filters.
- Ladder artifact: `runs/target-ladder-<claim>.yaml` (mirrors
  `runs/infeasible-ladder-<claim>.yaml`):
  `obstacle_class`, `attempts: [{level, family, action, outcome,
  instrument?}]`, `inventory: [{family, tried, failed_because}]`.
  `instrument` is ANNOTATION ONLY — validation never reads it as a filter.

### Functions

- `family_ladder_for(obstacle_class)` — the enumeration for a class.
- `ladder_defects(ladder, obstacle_class=None) -> list[str]` — empty iff the
  ladder is walked-valid: all 3 levels covered; every rung's family is in the
  class enumeration; NO family repeats (`family-repeat:T2/T3` defect = the
  acceptance "two same-family rungs -> ladder invalid").
- `settlement_blocker(ws, claim_id, register_text=None) -> str | None` — the
  NAMED reason or None. Defects: non-obstacle claim -> None (gate applies
  only to `origin: failure-obstacle`); ladder defects; empty inventory;
  inventory entry without its minted sibling (fan-out enforcement).
- `mint_sibling_claims(ws, obstacle_claim_id) -> list[dict]` — one sibling
  per inventory entry, idempotent per `(origin, obstacle_for, ladder_family)`:
  `{id, status: OPEN, boundary_type: obstacle-alternative,
  evidence_tier_attempted: 0, promotion_attempts: 0,
  depends_on: [<obstacle claim>], statement (family + tried + failed_because
  — actionable, the #234 one-liner complaint), origin: obstacle-alternative,
  obstacle_for: <obstacle claim>, ladder_family, promoted_from
  (the ladder artifact path), answers_question (inherited when the parent
  carries it)}` + real `claim_deps.yaml` edge. Same construction as
  `_promote_obstacle_claim` (idempotency marker, not text).
- CLI: `--check <C-NN>` (settlement blocker, exit 1 when blocked) and
  `--mint <C-NN>` (auto-register pending inventory siblings).

## Settlement gate (scripts/kunglao_record.py, claim_migrator)

CONFIRMED settlement = register status PROVEN on an obstacle claim ("really
can't" is a positive verdict on the blocking). Inserted as a fail-closed
write-side block (the #236 R3 shape) after the DEFERRED block, BEFORE the
PROVEN gate chain: `origin == "failure-obstacle"` + `new_status == "PROVEN"`
-> `target_ladder.settlement_blocker` must be None, else
`(False, "TARGET LADDER GATE: ...")` with the register unmodified. REFUTED is
deliberately NOT gated (#233 path-scoped closure standard requires refuting
obstacles to stay possible). ImportError of the gate module = BLOCKED
receipt (#78 REQUIRED_FOR_TERMINAL_STATE posture).

## 3-strike writer (scripts/dead_letter.py + hooks/worker_budget_sinks.py)

- `record_dispatch_failure(ws, claim_id) -> dict` — the live writer #146
  said the family lacked. Non-terminal claim: `promotion_attempts += 1`
  (register rewrite), and at `>= 3` the claim routes to the DLQ
  (`mark_dead` — DEAD + `blockers/dead-letter-<claim>.md`). Terminal claim:
  explicit no-op `{"incremented": False, "reason": "terminal ..."}`. Missing
  claim: `{"incremented": False, "reason": ...}` — never raises, never
  silently no-ops.
- Wiring: `post_check` (Agent PostToolUse completion sink) resolves the
  finished worker's claim from `[active_workers]` BEFORE `remove_worker`
  (same window as `_emit_tool_calls`), reads the worker's terminal status
  from `runs/worker-status-<worker>.md` (falling back to the tool_result
  transcript) via `lib_kunglao.parse_worker_status` (#444 single parse
  point), and on `failed|blocked|error` calls the writer. Fail-open: any
  exception -> stderr WARN, post_check still returns its own rc.

### Consumer blast radius (promotion_attempts gains a writer)

- `hooks/worker_budget_gates.check_promotion_attempts` — dispatch BLOCKS at
  >= 3: becomes reachable (was dead code by precondition). Intended.
- `scripts/dead_letter.scan` — 3-strike dangling set becomes non-empty:
  reachable. Intended.
- `scripts/convergence_check._dispatched_ids` — attempts >= 1 now counts
  failed-dispatch claims as "has dispatch evidence" for stuck detection:
  semantically CORRECT (a failed dispatch IS dispatch evidence).
- `scripts/ask_for_direction_gate.find_ladder_exhaustion` — ladder
  exhaustion marker (attempts >= 3 + candidate-less analysis) becomes
  reachable. Intended (issue: "siblings inherit the attempts<3 cap").

## Tests

- `tests/test_obstacle_ladder.py` — FAST tier (registered in
  `tests/_tiers.py` FAST_MODULES; no banned constructs): ladder defects,
  family distinctness, fallback enumeration, settlement blocker matrix,
  mint idempotency + linkage fields, record_dispatch_failure matrix,
  DLQ routing at 3 strikes, claim_migrator gate reject/pass, TS pool entry.
- `tests/test_obstacle_ladder_integration.py` — integration leg (not fast;
  hook import + register-rewrite through the real claim_migrator path with
  gates, kunglao_log emit face).

## Review fixes (r2, adversarial review 2026-09-18 — verdict BLOCK addressed)

- **F1 dual-face gate**: the hook-side backstop
  `hooks/worker_budget_gates.compare_register_change_proven_gate` (built for
  direct-register-edit bypasses, #15/#78) now runs
  `target_ladder.settlement_blocker` for every newly-PROVEN claim inside its
  violations loop, fed the register text it already read (same parse both
  faces, no extra read). ImportError = PROMOTION GATE fail-closed, the same
  REQUIRED posture as the BLIND/contradiction/inference/depth gates around
  it. The earlier "Alternatives rejected" entry only covered
  `check_register_transitions` — this is a different face and is now
  enforced, not documented away.
- **F2 class authority**: `obstacle_class` is pinned ON THE PARENT CLAIM at
  promotion (`failure_analysis_gate --obstacle-class` →
  `_promote_obstacle_claim` writes `obstacle_class` on the claim row; the
  analysis entry carries it for closure-backfill preservation).
  `settlement_blocker` (and mint) validate the artifact's declared class
  against the claim-pinned one: unpinned claim = defect (fail-closed until
  re-record), undeclared artifact class = defect, mismatch = defect. The
  family enumeration is keyed on the claim-pinned class — the artifact
  author can no longer choose their own pool at walk time. FAMILY_FALLBACK
  still applies to a claim pinned with an unknown free-text class (the
  ladder stays walkable); family-repeat invalidation remains the additional
  artifact-state check.
- **F3 guarded mint**: `mint_sibling_claims` refuses (explicit
  `{"minted": [], "refused": <reason>}`, CLI `REFUSED:` receipt, exit 1)
  unless the parent exists, carries origin failure-obstacle, and its ladder
  is walked-valid against the claim-pinned class with a non-empty
  inventory. No register/DAG pollution from mistyped ids. Idempotency
  marker comparison is case-insensitive (F7 seam, one-line hygiene).
- **F4 parsed origin route**: `_origin_from_register` (block-regex,
  fail-open on key order drift) deleted; `settlement_blocker` derives
  origin and the sibling snapshot from ONE yaml parse of the caller's
  register text (migrator's / backstop's already-read snapshot), falling
  back to a single file read only when no text is supplied. The void
  "never re-reads" justification is gone with it; the TOCTOU mix is closed.
- **F5 hook face**: the transcript fallback accepts ONLY the transcript's
  own closing line (`status: <token>` full-match on the last non-empty
  line) — quoted/echoed status fragments can no longer burn false strikes;
  a non-conforming tail yields None (absence of a strike, never a guess).
  The entry-missing path honors the warn contract: warns when the dispatch
  prompt carried a claim id (real starvation is audible), stays silent for
  non-claim Agent completions (verifiers must not spam).
- **F6 strike-3 routing**: `record_dispatch_failure` at
  `promotion_attempts >= DLQ_ATTEMPTS` escalates to the charter MUST-ASK
  lane — `blockers/must-ask-<claim>.md` (surfaces via convergence
  `_active_blockers`) + the taxonomy-registered `must_ask` event — and
  leaves the claim's status untouched, so `find_ladder_exhaustion` (pa>=3)
  HARD_PAUSEs the orchestrator on the next Type-D signal instead of the
  hook preempting the ask with a synchronous DEAD flip. `mark_dead` stays
  the explicit post-mortem face (`dead_letter --mark`); the DLQ route
  survives, the auto-DEAD does not. Strike non-decay is documented in the
  artifact (progress does not forgive strikes; reset is an explicit
  orchestrator decision).

## Alternatives rejected

- Gate inside `register_proven_gate.check_register_transitions` — that face
  validates →PROVEN transitions from register TEXT without workspace ladder
  IO context; the writer-side gate in claim_migrator is where the other
  status-specific preconditions live (#236 R3 precedent).
- Auto-mint inside the settlement gate — a read-shaped legality check must
  not mutate the register (mixing gate + write breaks the fail-closed
  receipt contract); instead the blocker DEFECTS an unminted entry with the
  mint command named, and `--mint` is the one auto-registration face.
- Gating REFUTED — would break the #233 path-scoped closure standard.
