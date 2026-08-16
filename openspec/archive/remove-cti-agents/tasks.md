# Tasks: Remove CTI agents (B4-1)

## TDD (RED phase)

- [ ] T1: Write `tests/test_no_cti_agents.py` — RED test asserting absence of CTI agents and references
- [ ] T2: Verify RED — new test must FAIL on current tree

## Implementation (GREEN phase)

- [ ] I1: `git rm agents/cti-correlator.md agents/shodan-host.md`
- [ ] I2: Update `references/guardrails.md` — remove cti-correlator/shodan-host from specialist list
- [ ] I3: Update `references/convergence-loop.md` — remove CTI correlation routing line
- [ ] I4: Update `references/operational-mechanics.md` — remove cti-correlator from bootstrap-tolerance list
- [ ] I5: Update `release-manifest.yaml` — remove two agent entries
- [ ] I6: Update `agents/kunglao-worker.md` — remove cti-correlator/shodan-host from description
- [ ] I7: Update `agents/verdict-scorer.md` — remove cti-correlator evidence input line
- [ ] I8: Update `tests/test_release_receipt.py` — remove from MANIFEST_AGENTS set
- [ ] I9: Update `tests/test_global_rule_subset.py` — remove from synthetic fixture

## Verify

- [ ] V1: Run full test suite — no new failures beyond 2 known
- [ ] V2: `grep -rn "cti-correlator\|shodan-host" agents/ references/ release-manifest.yaml` — zero hits
- [ ] V3: `npx openspec validate remove-cti-agents` — RC=0
- [ ] V4: Stage all changes with `git add` (do NOT commit)
