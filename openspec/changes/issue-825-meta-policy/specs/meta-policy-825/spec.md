# issue-825-meta-policy — delta spec (the meta-policy rewire)

The #806 axis, P2: the meta-policy becomes the explicit learner that
picks commits from context-conditional value statistics, and the pool
retrieval feeds the executor's context at the decision points. The
context-free family bandit is demoted to a cold-start prior (abolished
as a central dispatch decision path).

## ADDED Requirements

### Requirement: Commit selection conditions on the context vector

`select_commit(ws, features, ...)` SHALL score the commit actions from
the P1 value table (`context_features × action → {n, mean_reward,
mean_cost}`), aggregating cells by deterministic feature overlap,
shrunk toward the cold-start prior by observation count
(`conf = n / (n + N_SHRINK)`). The synthetic fixture pins: SAME family,
DIFFERENT context features → DIFFERENT chosen commit (17/17
combinations).

#### Scenario: same family, different context, different commit

- **WHEN** the pool holds reward-stamped episodes proving `persist`
  profitable under feature set {fam-x, cond-a} and `switch` profitable
  under {fam-x, cond-b}
- **THEN** selecting with [fam-x, cond-a] returns persist and
  selecting with [fam-x, cond-b] returns switch — for all 17
  generated combinations

#### Scenario: cold start — no value-table coverage rides the prior

- **WHEN** the pool has no reward-stamped episodes intersecting the
  context
- **THEN** the selection source is the prior and the chosen action is
  the prior's argmax (bandit statistics + exogenous feature shifts
  only)

### Requirement: The family bandit serves only as cold-start prior

The dispatch decision path SHALL NOT consult the family bandit
(`q_cells`) except through `meta_policy.cold_start_prior` blended into
the commit score. Grep-verifiable: no q_cells/bandit consult exists in
the hook dispatch gate, the dispatch context block, or the retrieval
face.

#### Scenario: the bandit is not a central dispatch path

- **WHEN** the meta-policy sources are scanned
- **THEN** the only q_cells reference on the meta path lives inside
  the cold-start prior face, and the dispatch gate/dispatch context/
  retrieval modules contain no bandit consult

### Requirement: Retrieval fires at the decision points and feeds context

`assemble(ws, features, phase)` SHALL retrieve through the P1 read
face at exactly the legal phases, rank by the utility-score weights,
filter by MIN_UTILITY, cap at RETRIEVE_MAX, and attach
feature-matched playbook fragments. `envelope_block(ws, claim, phase)`
(schema `meta-policy/1`) SHALL be the SINGLE dispatch interface
carrying commit + context + budget; `render_block` renders the
prompt-side text with the KUNGLAO_META_POLICY marker. The dispatch
context block (`build_dispatch_context`) SHALL attach it as an
optional fail-open `meta_policy` key.

#### Scenario: retrieved cases appear at both phases

- **WHEN** the pool holds a matching case and the envelope block is
  built at phase=episode_start and again at phase=commit_boundary
- **THEN** both blocks' context.cases carry the case id and
  render_block names it

#### Scenario: the dispatch context carries the meta block

- **WHEN** build_dispatch_context runs on a workspace with pool
  coverage
- **THEN** the returned context carries `meta_policy` with the chosen
  commit and the retrieved case ids; a loader failure leaves the key
  absent and never raises

### Requirement: Exactly three learnable knobs

Configuration SHALL expose exactly three knob groups — (a) value-table
weights, (b) utility-score weights, (c) retrieval threshold/count —
each env-overridable with a documented default. No other tunable
parameter exists on the meta path.

#### Scenario: knobs move behavior

- **WHEN** RETRIEVE_MAX is set to 1 (or MIN_UTILITY raised above a
  case's utility)
- **THEN** the assembled context carries exactly that budget's worth
  of cases

### Requirement: Component-ablation hooks

KUNGLAO_META_RETRIEVAL=0 SHALL remove the retrieval component (empty
cases/playbook; budget still reported). KUNGLAO_META_VALUE_TABLE=0
SHALL remove the value-table term (selection rides the prior;
pool-different contexts no longer change the choice).

#### Scenario: retrieval off is a real ablation

- **WHEN** KUNGLAO_META_RETRIEVAL=0 and the pool holds matching cases
- **THEN** the envelope block's context carries no cases and no
  playbook

#### Scenario: value table off removes the contextual term

- **WHEN** KUNGLAO_META_VALUE_TABLE=0 and two contexts have different
  pool-proven best actions
- **THEN** both selections return the SAME action (the prior's), and
  the source reports the ablation

### Requirement: The utility chain is measured

The episode SHALL optionally carry `retrieved` (episode-start case
ids) and per-commit `cited` case ids (additive, tolerated by the
episode/1 validator). `utility_chain(doc)` SHALL report the tracked
chain: retrieved count, cited count, cited∩retrieved count, and
whether the outcome improved (reward.r > 0).

#### Scenario: retrieved-cited-improved chain

- **WHEN** an episode stamps retrieved [C-1, C-2], cites C-1 on its
  commit, and carries a positive reward
- **THEN** utility_chain reports retrieved=2, cited=1,
  cited_from_retrieved=1, improved=true

## Constraints honored

- A2: value table + playbook stay the P1 derived views (no new store;
  the value-table module writes nothing — pinned in #824 and not
  regressed).
- A4: only reward-stamped episodes feed the table (the P1 honest-gap
  rule); the trust spine is only ever CALLED.
- A5: zero new human decision points; the hook face stays fail-open
  (dispatch is never blocked by the meta policy).
- No touch: settlement/verifier semantics, #818 in-flight tests,
  #816 corpus, claims_store/scalar semantics.
