# issue-824-model-contract — delta spec (the model contract)

References the #806 axis axioms: A1 output-centric reward (per-fact
credit retired to audit), A2 single-model law, A3 growth = derived
views sharpen/thicken/compound, A4 trust = the reward channel, A5
zero-human. Every requirement below carries its axiom.

## ADDED Requirements

### Requirement: The episode is the pool's only grain, machine-readable (A2)

An episode SHALL be one markdown file `runs/episodes/episode-<claim>.md`
whose YAML frontmatter carries schema `episode/1` and the machine-
readable fields: `id`, `claim`, `created`/`updated` (UTC-Z), 
`context_features` (list of short tokens), `commits` (ordered list of
`{seq, action, summary}` with `action` ∈ the six-commit vocabulary
select/persist/tune/switch/verify/deliver), `outcome`
(`{status, verified, evidence_ref}`; status ∈ completed/failed/blocked),
`cost` (`{tokens, seconds}`, non-negative numbers), `utility`
(`{retrievals, citations, utility}`), `reusable_fragments` (summary
strings), `milestones` (list of `{id, desc, verified, evidence_ref}`),
and `reward`. A document failing any field rule SHALL be refused by the
validator (`EpisodeError`) — a bad episode is RED, never tolerated.

#### Scenario: a well-formed episode validates

- **WHEN** an episode file carries all `episode/1` fields with legal
  values
- **THEN** `validate_episode` returns the parsed document

#### Scenario: a schema-less or mistyped episode is refused

- **WHEN** an episode file is missing `schema`, carries an unknown
  commit action, a negative cost, or a non-token context feature
- **THEN** validation refuses with the offending field named

### Requirement: Summaries only — the raw-log write is refused (A1 audit posture)

The schema SHALL cap every summary surface: each reusable fragment ≤
`FRAGMENT_CHAR_MAX` chars, ≤ `FRAGMENT_MAX` fragments, body ≤
`BODY_CHAR_MAX` chars. A write attempt whose fragments or body exceed
the caps (the raw-log shape) SHALL be refused — the pool never becomes
a log dump.

#### Scenario: a raw-log write attempt is RED

- **WHEN** an episode write carries a 5000-char fragment (a pasted log)
- **THEN** the write gate refuses with reason naming the summary cap

### Requirement: Writes pass the trust gate and the admission policy (A4)

The pool write gate SHALL admit an episode only when BOTH hold:
(a) **trust** — the episode outcome's `evidence_ref` resolves through
`verifier_integrity.resolve_verification` to a PASSED record
(fail-closed: absence/escape/fail-word = refused);
(b) **admission** — the episode is terminal with non-zero reward, OR a
failure with a non-empty clean attribution (`attribution` field on the
episode), OR a surprise event (`surprise: true`). An episode failing
either leg SHALL be refused with the reason; nothing is written.

#### Scenario: an unverified outcome never enters the pool

- **WHEN** an episode declares `outcome.verified: true` but its
  evidence reference resolves to no PASSED record
- **THEN** the write is refused and `runs/episodes/` stays unchanged

#### Scenario: a clean-attribution failure is admitted

- **WHEN** a failed episode carries a non-empty attribution and a
  resolving PASSED verification record
- **THEN** the episode lands in the pool

### Requirement: Read happens at three legal phases only (A2)

The pool read face SHALL accept exactly `phase ∈ {episode_start,
commit_boundary, blocked}` and refuse any other phase. Retrieval SHALL
rank by utility (decayed, deterministic tie-break on claim id) and bump
each returned episode's `utility.retrievals` counter.

#### Scenario: mid-execution retrieval is refused

- **WHEN** retrieval is requested with phase `mid_execution`
- **THEN** the read face refuses with the legal-phase vocabulary

### Requirement: The update policy decays unreferenced retrievals (A3)

At each settlement the update policy SHALL: update the settled
episode's stats; multiply the utility of episodes retrieved in the
preceding window but NOT cited by `UTILITY_DECAY` (retrieved-and-uncited
loses rank); re-value a cited episode up to at most `UTILITY_MAX`
(max-revalue); and prune pool capacity by lowest utility (utility, not
age, decides eviction).

#### Scenario: retrieval without citation decays (the green pin)

- **WHEN** an episode was retrieved at episode start but the settled
  episode cites another
- **THEN** after the settlement update its utility is strictly lower

#### Scenario: max-revalue is capped

- **WHEN** a cited similar episode is re-valued repeatedly
- **THEN** its utility never exceeds `UTILITY_MAX`

### Requirement: Indexers are pure derived views (A3)

The value table and the playbook view SHALL be computed over the
episode files at call time, in deterministic order, writing NO file
(no parallel store). Regeneration SHALL produce identical output for
identical pool bytes. The value table SHALL key context_features ×
commit action → {n, mean_reward, mean_cost}. The playbook view SHALL
admit only episodes with `outcome.status == completed` and a
trust-resolved verification, emitting deduped reusable fragments
capped per group.

#### Scenario: regenerate = same output, no store

- **WHEN** the value table is computed twice over an unchanged pool
- **THEN** both outputs are byte-identical and no new file exists in
  the workspace

### Requirement: The learning signal is task completion + milestones − cost (A1)

`compute_reward(completion, milestone_progress, cost)` SHALL return
`W_COMPLETION·completion + W_MILESTONE·milestone_progress − cost_term`
with documented policy constants and cost_term normalized into [0, 1].
The signature SHALL carry NO fact-credit parameter (per-fact credit is
structurally out of the learning signal; it survives only in the
existing audit faces). Each milestone SHALL count toward progress only
when its own evidence reference resolves to a PASSED record (the trust
spine gates milestone verification).

#### Scenario: the PE pathology scores ≈ 0 (synthetic fixture)

- **WHEN** an episode reports many verified facts (per-fact audit mass)
  but zero task completion and zero verified milestones
- **THEN** its learning-signal reward is ≤ 0 while the audit face can
  still report the fact credit

#### Scenario: an unverified milestone contributes nothing

- **WHEN** a milestone declares `verified: true` but its evidence
  reference resolves to no PASSED record
- **THEN** milestone progress ignores it

### Requirement: The settlement hook fires the update policy (A1→pool)

`on_settlement(ws, claim)` SHALL read the settled outcome through the
existing settlement read faces (called, never modified), compute the
episode reward, stamp it into the episode, and run the update policy
over the retrieval window.

#### Scenario: a settlement updates stats and reward

- **WHEN** `on_settlement` runs for a pool episode after a verified
  outcome
- **THEN** the episode's reward is stamped and its citation counter
  reflects the settlement
