# Design — issue-252-hypothesis-bridge

## Anchors verified (2026-09-19, worktree HEAD 748a33d)

| Anchor | Found at | Drift |
|---|---|---|
| candidates prose contract | scripts/hypothesis_seeder.py:62-70 `_scaffold_body` ("the orchestrator fills `candidates` … never mechanized") | none |
| candidates as plain strings | scripts/hypothesis_store.py:127 `Hypothesis.candidates: list[str]`; `to_frontmatter` :142; `_parse` :258-259 comma-split | none |
| #446 no-second-representation red line | scripts/hook_activation.py:396 ("no fourth liveness representation — #446 F-class red line"); the same family governs queue representations (event taxonomy, decision-surface anchor) | none |
| #250 plan_epistemics mint | scripts/plan_epistemics.py:210 `mint_epistemic_claims` (claims carry `boundary_type: epistemic`, `answers_question` = pq_id, ΔH fields) | none |
| #234 sibling-mint pattern | scripts/target_ladder.py:302 `mint_sibling_claims` (origin/obstacle_for/ladder_family edge fields on the claim row; idempotency marker (origin, obstacle_for, ladder_family) — marker-not-text) | none |
| claim status transition writer | scripts/kunglao_record.py:255 `claim_migrator` (`_set_claim_status` :513; terminal gates; ledger + kunglao_log mirror) | none |
| settlement vocabularies | scripts/tool_value.py:67 POSITIVE_SETTLEMENTS {PROVEN, VERIFIED}, :68 NEGATIVE {REFUTED, NEGATIVE, DEAD}; scripts/status_defs.py TERMINAL (8 values) | none |
| TS rank pool entry | scripts/priority_ratio.py:707 `priority_ratio` (candidates = OPEN + attempts<3 + terminal parents); claim `competitor_group` field documented v1.7 in templates/state/claim-register.yaml:25 (q_id namespace — the `hyp-` prefix is collision-free) | none |
| store write faces + consumers | HypothesisStore.create/_write/transition; upstream impact (GitNexus): MEDIUM/38 — dispatch_gate, state_anchor, think_seat, oracle_runner, notes_writer, kunglao_resume, seeder, digest_build, convergence_check, backtrack_loop (all READ faces preserved — no API change) | none |

## D1 — the family linkage (one representation)

`scripts/hypothesis_bridge.py`:

- `FAMILY_GROUP_FMT = "hyp-{hyp_id}"` — the family id stamped on arm
  claims' `competitor_group` (the issue-mandated format; the claim
  field's documented v1.7 namespace is task_spec q_id, so `hyp-` is a
  collision-free namespace). `ARM_ORIGIN = "hypothesis-arm"`,
  `HYPOTHESIS_REF = "hypothesis_ref"`.
- **Namespace guard (review F8)**: `family_hypothesis_id` requires the
  suffix to match the hypothesis-ID grammar `H-\d+`; and
  `family_claims` membership requires BOTH the group AND the
  mint-issued `hypothesis_ref` edge field — an external q_id that
  merely looks like `hyp-<x>` neither adjudicates a family (the sync
  ignores it) nor passes the lint (E2b names it).
- `mint_family_arms(ws, hyp_id, candidates, *, answers_question=None)`
  — one OPEN claim per candidate appended to claim-register.yaml via
  the normal mint path (atomic tmp+replace, the plan_epistemics shape;
  claim ids from `failure_analysis_gate._next_claim_id` — the single
  ID grammar). Idempotency marker `(origin, hypothesis_ref, arm_key)`
  where `arm_key` is the normalized candidate slug stored on the claim
  (marker-not-text, the #234 rule). **Key-collision refusal (review
  F6b)**: two distinct candidates sharing the 200-char slug — within
  the batch or against a minted arm — REFUSE the batch explicitly;
  never a silent collapse or partial mint. The candidate string is
  NEVER written to the hypothesis file (no second representation).
- `mint_pending_candidates(ws)` — the sweep/migration face: for every
  hypothesis with candidate strings, mint each as an arm and rewrite
  the hypothesis with `candidates=[]` (strings leave the store once
  claimed). This is how the #669/#692/#110 filler contracts stay
  unchanged while their output joins the economy.
- `check_bridge_lint(ws)` — the no-orphan-representation guard:
  E1 a candidate string parked in hypotheses/ (the sweep has not paid
  it) = a write to hypotheses/ without a corresponding claim mint;
  E2 a claim with `competitor_group: hyp-<id>` whose hypothesis file
  is missing; E2b a hyp-namespace claim without the mint-issued
  `hypothesis_ref` marker (F8); E3 derivation divergence — an OPEN
  family whose member claims already derive confirm/refute (the sync
  did not run: the persistent-crash detector for F4, repaired by
  `--sync`). Empty list = clean.

## D2 — the family ledger sync (#528 transitions, unchanged internals)

`sync_family_ledger(ws) -> dict` (called from `claim_migrator` AFTER a
successful register write, guarded — the migration must never fail
because the ledger sync did):

- membership = mint-issued arm claims (group + `hypothesis_ref`) whose
  hypothesis file exists (missing-file arms are lint-reported, not
  synced).
- `family_verdict(arms)` is the SINGLE derivation shared by the sync
  and the lint (no drift): any arm in POSITIVE_SETTLEMENTS
  (PROVEN/VERIFIED) -> "confirm"; every arm terminal AND at least one
  in NEGATIVE_SETTLEMENTS -> "refute" — **the refuting reference is a
  NEGATIVE arm id only (review F2); a DEFERRED/STALE-only family is
  budget exhausted, not a refutation, and stays pending** (refuted is
  terminal forever, so a deferral must never mis-adjudicate it);
  anything else -> "pending".
- verdict confirm on an OPEN family -> `transition(confirmed,
  confirming_fact_id=<winning arm id>)` (the field carries the
  deciding reference — the notes_writer superseded_by=note_id
  precedent) AND every OTHER open hypothesis sharing the confirmed
  one's competitor_group transitions `superseded`
  (`superseded_by=<family id>`) — "any arm PROVEN -> competing
  hypotheses superseded". **Losing OPEN arms retire claim-level
  SUPERSEDED (review F3)** — `superseded_by = the winning arm id`
  (the status_defs SUPERSEDED semantics: closed by replacement) — for
  the confirmed family AND each superseded sibling, so a decided
  question stops drawing TS budget (`priority_ratio.is_open` excludes
  them).
- **No-re-emit guard (review F5)**: an already-confirmed/refuted
  family reports `unchanged` (no duplicate `family_confirmed`/
  `family_refuted` events on subsequent settlements); terminal states
  that do not match the verdict are `skipped` and never rewound —
  decided hypotheses stay decided (#528); the accepted one-way
  semantics: arms cannot re-settle, and a family adjudicated from the
  arms it had is not revisited when new arms appear later.
- Register writes (arm retirement) are ONE atomic rewrite, only when
  something changed.

## D3 — filler/family integrations (existing sites, additive)

- **#234** `target_ladder.mint_sibling_claims`: before the sibling
  loop, `ensure_family` (body marker `obstacle-family:<claim_id>`,
  claim_id=parent obstacle claim, self group); each NEW sibling gains
  `competitor_group: hyp-<H-id>` + `hypothesis_ref` (additive fields —
  the existing marker idempotency and the obstacle_ladder tests'
  keyed assertions are unaffected).
- **#250** `plan_epistemics.mint_workspace`: for each minted pq_id,
  reuse the existing pq-bound hypothesis when present (the #109
  binding shapes: body marker `pq:<qid>` or group `pq-<qid>`/`pq:<qid>`)
  else `ensure_family` with marker `pq:<qid>` + group `pq-<qid>`
  (recognized by #109 admission and seeder idempotency); stamp each
  minted epistemic claim with the family linkage. The claims keep
  `boundary_type: epistemic` — NOT re-minted, NOT double-represented;
  the family ledger's member IS that claim.
- **Sweep + lint wiring (review F7)**: `digest_build` sec_g seed block
  calls `mint_pending_candidates` and then `check_bridge_lint`
  (fail-open; `bridge_lint_findings` emit + stderr WARN) — candidate
  strings are paid into the economy at every cold start and the
  E1/E2/E2b/E3 findings surface at every cold start, not only via the
  CLI.
- **Seeder prose contract mechanized**: `_scaffold_body` now names the
  bridge ("arms mint as claims via scripts/hypothesis_bridge.py …
  family state syncs from claim settlements"); `candidates=[]` stays
  (the #662 RED8 assertion holds).

## D4 — static writer allowlist (the regression pin)

A test (not a lint script) calls
`hypothesis_bridge.writer_scan_offenders` over `scripts/` AND
`hooks/` (review F6: both trees). Writer signals, calibrated so the
CURRENT tree trips exactly the five allowlisted faces + the bridge
(zero false positives): (a) the `Hypothesis(` dataclass constructor;
(b) a store reference (name/type) AND a store write face
(`.create(`/`._write(`/`.transition(`); (d) the hypothesis frontmatter
schema key (`schema_rev`) AND a raw file write — the no-import
raw-frontmatter evasion. A REAL bridge import line
(`from hypothesis_bridge import …` — a comment mention does NOT count,
review F6b) exempts. The allowlist is FIVE modules (hypothesis_store,
hypothesis_seeder, think_seat, backtrack_loop, notes_writer —
scaffold/bet/retro-seed/adjudication faces, none arm-minting);
kunglao_record is exempt without listing because it imports the bridge
(the sync call site). A future arm-minting writer without the bridge
fails the test — the parallel-queue regression is lint-guarded.

## D5 — the #109 admission coupling (review F1 — the inlet gate)

`hooks/dispatch_gate._hypothesis_admission` (the first-dispatch gate
for a PQ neighborhood) previously counted STORE CANDIDATE STRINGS only
(`open_candidates_for_question >= 2`) — the exact representation the
bridge drains and bans: a live first-dispatch deadlock on lint-clean
workspaces, with a repair text instructing the banned parking. The
migrated read counts the UNION of both faces:
`len(set(strings) | set(arms)) >= 2`, where arms =
`open_family_arms_for_question` (OPEN mint-issued arm claims whose
family hypothesis is pq-bound via the #109 shapes or a
claim_id->answers_question link). The strings face stays as a
TRANSITIONAL pool (legacy feeders keep their contracts; the sweep
migrates them). The REJECT repair text now names the mint path first
(`hypothesis_bridge --mint`), mentioning the transitional string face
as such. Sequencing note: admission precedes top1 (protocol
completeness precedes the value teeth). End-to-end pinned:
sweep-drained workspace -> `mint_family_arms` -> first dispatch
ADMITTED (`test_minted_family_arms_admit_first_dispatch`); one arm
alone still rejects (the bar is competing explanations, not
representation).

## Blast radius (GitNexus, main-repo index, 2026-09-19)

- HypothesisStore upstream: MEDIUM / 38 impacted / 11 direct — all
  READ faces, no API change in this change.
- seed_from_task_spec LOW/2 (tests); seed_apkid_candidates LOW/0
  (runtime-dispatched); claim_migrator LOW/1; mint_sibling_claims not
  statically indexed (CLI/runtime dispatch). Practical risk LOW — all
  wiring is additive and guarded.
