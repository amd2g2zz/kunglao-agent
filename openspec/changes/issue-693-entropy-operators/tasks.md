# tasks — issue-693-entropy-operators

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-693-entropy-operators` (proposal,
      design, tasks, specs/entropy-operators/spec.md).
- [x] 1.2 Impact analysis before editing the one existing symbol
      surface (`rlvr/__init__.py` export map): gitnexus CLI impact
      (ambiguous `__init__` — disclosed) + mechanical importer survey
      (93 files import rlvr; change is 25 insertions / 0 deletions,
      additive-only). Risk LOW; recorded in design.md.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 tests/test_entropy_693.py — the five named RED tests:
      delta-H nonzero on non-degenerate distribution; entropy
      observable-only until the ADR-001 gate; invariant rejects an
      impossible candidate before an attempt; mismatch narrows to a
      named layer; constant-set diff separates reference from mutated
      MD5. Plus T4/T5 tests: termination cells keyed
      (kind, family, layer); covering matrix enumerates the search
      space.
- [x] 2.2 tests/test_constants_ref_693.py — the provenance suite:
      compact per-family re-implementations reading the module tables
      must reproduce hashlib digests (SM3: the published KAT vector),
      so every table word stays mechanically pinned.
- [x] 2.3 RED confirmed: collection ImportError on the three missing
      modules (run output captured in the PR body).

## 3. GREEN

- [x] 3.1 scripts/rlvr/constants_ref.py — reference tables (MD5 /
      SHA-1 / SHA-256 / SM3 IV+round constants; SHA-1 carries all FIVE
      IV registers) + `classify` mechanical diff (family / exact /
      missing / extra), every word pinned by the 2.2 provenance
      suite.
- [x] 3.2 scripts/rlvr/invariants.py — `check_candidate` / `prune` /
      `invariants_from_lengths`; inconclusive dimensions never reject;
      reasons name candidate + invariant + prediction + observation.
- [x] 3.3 scripts/rlvr/hypotheses.py — `refine_on_mismatch` (CEGAR
      3-branch tree), `mint_hypothesis` (closed layer vocabulary),
      `layer_death_cells` ((kind, family, layer) keying, unscoped
      bucket), `covering_matrix` (delegates to
      replay_equivalence.required_combos).
- [x] 3.4 scripts/rlvr/__init__.py — additive export map (three
      module imports + `__all__` names + docstring bullets).

## 4. Registrations + gates

- [x] 4.1 scripts/README.md catalog rows for the three modules.
- [x] 4.2 deploy_manifest --write (three-registrations face).
- [x] 4.3 Gates with real output: both entropy suites green (12/12),
      ruff on changed files, comment_hygiene_lint + formal_code_lint
      clean (new files carry no baseline entries — zero debt added),
      openspec validate green.

## 5. Review gate + ship

- [ ] 5.1 Independent review → PASS → review evidence minted per
      scripts/review_gate.py.
- [ ] 5.2 PR to dev with mapping table, gates output, honest
      limitations; CI green; merge; comment on the issue.
