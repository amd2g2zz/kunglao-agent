# source-reliability-715 delta — issue-715-source-reliability

## ADDED Requirements

### Requirement: Evidence items carry source and reference-class labels

Every evidence item entering the reliability learning SHALL carry two
labels: `source` (the producing tool name) and `reference_class` (the
reference frame, one of `raw`, `derived`, `inferred`). The write faces
SHALL refuse - with a loud result dict, never a raise - an item whose
labels are missing or outside the taxonomy, and SHALL NOT record any
event for it. The taxonomy SHALL be a label vocabulary only: no
reference class SHALL be seeded with a different prior, and the tier
ordering SHALL NOT be read as a trust ranking anywhere.

#### Scenario: a labeled item is accepted and an unknown class refused

- **WHEN** `record_refutation` is called with
  `{source: "ghidra-pseudo", reference_class: "derived"}` and then with
  `{source: "x", reference_class: "rumor"}`
- **THEN** the first call returns `recorded: True` and the source class
  `ghidra-pseudo|derived` carries one refutation, while the second
  returns `recorded: False` naming `reference_class` and no event lands

#### Scenario: the label taxonomy is not a prior

- **WHEN** two fresh classes differing only in reference class (e.g.
  `raw` vs `inferred`) are read before any event about either
- **THEN** both read the identical uniform prior Beta(1, 1) with basis
  `prior` and mean 0.5

### Requirement: Refutation raises beta and confirmation raises alpha

The reliability of a source class SHALL be the Beta posterior

    Beta(alpha, beta | source_class, context_class)

folded from append-only invalidation events. Evidence REFUTED by later
evidence SHALL add 1 to the source class's beta (alpha untouched);
evidence CONFIRMED SHALL add 1 to alpha (beta untouched). Rows SHALL be
append-only with schema `source-reliability/1`; the fold SHALL be a
read-face property and SHALL never rewrite raw rows. A refuting evidence
item SHALL NOT be auto-credited: its own source learns only when IT is
confirmed. The store SHALL be shared across workspaces under the
strategy-store root (env override honored), and every read SHALL be
fail-open (missing or dirty store -> the prior face, one canonical
warn).

#### Scenario: refuted evidence updates the source beta

- **WHEN** an evidence item from `ghidra-pseudo|derived` is refuted by
  later evidence and the store is folded
- **THEN** that class's beta equals its previous value plus 1, alpha is
  unchanged, and the posterior mean falls

#### Scenario: confirmed evidence updates the source alpha

- **WHEN** an evidence item from `raw-asm|raw` is confirmed and the
  store is folded
- **THEN** that class's alpha equals its previous value plus 1, beta is
  unchanged, and the posterior mean rises

### Requirement: Reliability generalizes to new contexts

A read SHALL resolve with backoff: the exact (source_class,
context_class) cell when it has observations; otherwise the source-class
marginal pooled across all contexts; otherwise the uniform prior. A
context that has never observed the source SHALL read the marginal, so
reliability learned for a source in one context applies to the same
source in new contexts. The read result SHALL name which face answered
(`basis` in `cell` / `marginal` / `prior`).

#### Scenario: a new context inherits the source-class learning

- **WHEN** a source accumulates refutations under one context label and
  is then read under a different, never-seen context label
- **THEN** the read reports basis `marginal`, a beta above the prior,
  and a sampled theta below the prior mean

### Requirement: Thompson sampling explores uncertain sources

The `theta` read face SHALL draw one sample from the read posterior
(stdlib `betavariate`; a default seeded rng when none is given). No
rule SHALL pre-select which reference frame to doubt: exploration SHALL
be a property of the posterior width alone. A thinly observed
(high-variance) source SHALL sample wide enough to outdraw a settled
source at a non-trivial rate, while a settled-low source SHALL be
effectively never selected.

#### Scenario: uncertainty keeps a source explorable

- **WHEN** three sources stand at a settled mediocre posterior, an
  unobserved prior, and a settled-bad posterior, and candidates are
  selected by the maximum `theta` draw over many seeded rounds
- **THEN** the unobserved source wins a substantial share of rounds
  while the settled-bad source effectively never wins
