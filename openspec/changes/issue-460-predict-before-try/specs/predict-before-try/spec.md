# predict-before-try delta — issue-460-predict-before-try (Part B)

## ADDED Requirements

### Requirement: Feature-conditioned prior is flag-gated and inert by default

The feature-conditioned prior SHALL be gated behind the
`KUNGLAO_PREDICT_BEFORE_TRY` environment flag (read at call time,
"1" = enabled, everything else = disabled, default DISABLED). With the
flag disabled, or enabled but no valid feature table present, the
Q-cell kernel, the DTS sampler, and every sampler receipt SHALL be
byte-identical to the pre-change kernel for the same store, inputs,
and seed. The tests under `tests/test_rlvr_bitexact.py` SHALL pass
unmodified.

#### Scenario: flag off produces the identical receipt

- **WHEN** the same workspace store and seed are sampled twice, once
  with the flag unset and once on a tree predating this change
- **THEN** the receipt JSON is byte-identical (family, candidates,
  theta, weight, gamma)

#### Scenario: flag on without a table stays inert

- **WHEN** the flag is enabled but no feature-table/1 rows can be
  loaded for the workspace
- **THEN** no feature pool enters any cell posterior and the sampler
  behaves exactly as flag-off

### Requirement: Similarity over feature-table/1 vectors is Jaccard on canonical tokens

The similarity between two feature vectors SHALL be the Jaccard
coefficient over a canonical token-set projection of the
feature-table/1 features object: identity tokens (lane=, ptype=,
lang=, entry=) for non-null scalar fields, one token per TRUE
packer-flag boolean (pf:), one token per detected packer (pk:) and
obfuscator (ob:), difficulty tier/dominant-factor tokens when the
difficulty block is present, and probe-fact tokens (die:usable,
apkid:usable, die:packer=) when those facts hold. NULL or absent
fields SHALL emit no tokens (absence never scores). The coefficient
SHALL be 1.0 for identical token sets, 0.0 for disjoint sets, and 0.0
when both sets are empty. The function SHALL be deterministic and
order-independent.

#### Scenario: identical features are fully similar

- **WHEN** two feature vectors produce the same token set
- **THEN** similarity is exactly 1.0

#### Scenario: degraded evidence lowers similarity, never fabricates distance

- **WHEN** one vector carries detected packers and the other has empty
  detection lists because its probe evidence was absent
- **THEN** the shared tokens still count and the coefficient is
  strictly between 0.0 and 1.0 — missing evidence reduces similarity
  without inventing opposing tokens

#### Scenario: empty union scores zero

- **WHEN** both token sets are empty
- **THEN** similarity is 0.0 (no borrowing on no evidence)

### Requirement: The feature pool is a second anchor source under the one SHRINK_CAP

A feature-conditioned pool SHALL be computed per (features, family)
as the similarity-weighted masses over OTHER mined instances' outcomes
attributed to that family: per row, mass = (similarity, similarity)
scaled by the row's outcome — settled credit when non-null, else 1.0
for landed and 0.0 for timeout/blocked act results, else the outcome
is excluded (unknown never scores). The live sampler face SHALL pool
every table row (a previous run with the identical feature hash is
prior history, not leakage); an optional explicit `exclude_run` by
run_id SHALL be honored when supplied (the replay's leave-one-run-out
split — no fuzzy run-identity join exists). When enabled, the pool
masses SHALL be added to the hierarchical anchor masses BEFORE the
single SHRINK_CAP is applied, so the family/global pool remains the
base borrow at weight 1 per observation, the feature pool rides on top
similarity-discounted, and the total borrowed pseudo-observations
never exceed SHRINK_CAP. Pool accumulation SHALL be deterministic
(table order, input-order float64 reduction), and a pool of zero
masses SHALL leave the posterior bit-identical to no pool.

#### Scenario: similar-instance evidence tilts the anchor

- **WHEN** the flag is on, a table carries structurally similar
  instances whose outcomes in family f are predominantly successful,
  and the cell itself is cold
- **THEN** the cell's posterior mean with the feature pool is strictly
  higher than without it, and both stay within the SHRINK_CAP-bounded
  anchor form

#### Scenario: the cap bounds the pool like any anchor mass

- **WHEN** the feature pool alone carries more pseudo-observations
  than SHRINK_CAP
- **THEN** the total anchor weight is capped at SHRINK_CAP exactly as
  the family pool alone would be

#### Scenario: the replay excludes its held-out run explicitly

- **WHEN** a pool is computed with exclude_run set to the held-out
  run's run_id
- **THEN** that run's outcomes are excluded from the pool, and every
  other row (including identical-feature-hash rows) pools

#### Scenario: a zero pool is a no-op

- **WHEN** every row's similarity to the query features is 0.0
- **THEN** the cell posterior is bit-identical to the flag-off path

### Requirement: Per-project_type probe-list gating is retired from the intake face

The intake promise prescan block SHALL record a DIRECT capability
fact for every probe tool (die, apkid) on every lane and project_type:
the toolchain report item when present, else host tool presence, else
probe-evidence presence — a uniform state vocabulary with no
per-project_type membership rule and no "layer not in this
project_type's probe set" note anywhere in the tree. The fixed
first-claim probe obligation (`prescan_obligation`) SHALL remain
byte-identical while the flag is off and SHALL be replaced, when the
flag is on, by a probes-as-arms note carrying the prior-ranked arm
order. Capability checks (toolchain tool presence probing, #436
resource-safety wrappers) SHALL continue to run unchanged.

#### Scenario: promise records probe facts uniformly

- **WHEN** the intake promise is built for a project_type whose
  toolchain check set omits a probe tool
- **THEN** the prescan block still carries that tool's record derived
  from direct presence facts, with no per-project_type note and no
  missing key

#### Scenario: capability checks keep running

- **WHEN** the retirement lands
- **THEN** toolchain CHECK_SETS probing is unchanged (facts, not
  rules) and the jadx resource-safety gate behaves identically

### Requirement: Probe arms rank by expected information gain at cold start

When the flag is on, the probe arms (die-probe, apkid-prescan) SHALL
be ranked as ordinary arms by expected information gain: gain =
unknown revealable tokens / total revealable tokens, where each
probe's revealable-token set is static (die: language/packer/entropy
facts; apkid: packer/obfuscator facts) and tokens already present in
the current features are known. With no instance features every
revealable token is unknown, so identification probes SHALL rank above
method arms whose priors are uninformative; a probe with zero unknown
revealable tokens SHALL yield zero gain and rank below informative
method arms. Ranking ties SHALL break deterministically (gain, then
revealable-token count, then arm name). The ranked order SHALL be
deterministic given the features.

#### Scenario: cold start orders probes first

- **WHEN** the current features carry no probe facts (empty token
  set) and the flag is on
- **THEN** both probe arms rank above every method arm

#### Scenario: known facts demote the probe

- **WHEN** the current features already carry all of a probe's
  revealable tokens
- **THEN** that probe's gain is 0.0 and it ranks below method arms
  with non-uniform feature-conditioned priors

#### Scenario: the ranking is a pure function

- **WHEN** the same features are ranked twice
- **THEN** the order is identical

### Requirement: MC replay A/B gates activation (EX-5)

The A/B replay SHALL ship as experiments/ex5_predict_before_try.py
(EX-5) with committed results (ex5-results.json) and a report
(ex5-predict-before-try.md), replaying policy A (flat cells + fixed
probe set, feature prior off) against policy B (feature-conditioned
prior + probe arms, flag on) over a mined feature table using
leave-one-run-out splits (the held-out run excluded from its own
training pool by explicit run id), reporting cold-start first-act
success rate and oracle PASS rate per held-out run and aggregated.
The replay SHALL be deterministic (seeded trials; same table ⇒
byte-identical results) and SHALL declare itself underpowered when
fewer than 3 usable runs exist. The feature-conditioned prior and the
probes-as-arms obligation SHALL remain default-off unless policy B
wins the replay decisively at real table scale AND the flag flip is
approved; an underpowered or losing result SHALL ship flag-off with
the result reported honestly.

#### Scenario: the replay is reproducible

- **WHEN** the experiment runs twice over the same table
- **THEN** ex5-results.json is byte-identical

#### Scenario: a non-decisive result keeps the flag off

- **WHEN** the table is underpowered (fewer than 3 usable runs) or
  policy B does not win both metrics decisively
- **THEN** the default flag value stays off and the report says so
  prominently
