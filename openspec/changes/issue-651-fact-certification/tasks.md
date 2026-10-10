# tasks — issue-651-fact-certification

## 1. The certification gate (lint_facts — single source)

- [x] `read_register_proven(ws)` — the register's PROVEN claim ids (tolerant)
- [x] `certification_defects(fm, body, proven, fact_ids)` — grammar (`lint_fact`) + terminal-status register-backing (every cited claim PROVEN; claim-less terminals uncertifiable)
- [x] RED: gate unit tests

## 2. The consumption faces

- [x] `rlvr.state.fact_face`: `verified` counts only certified terminal facts; `count` unchanged
- [x] `e2e.checkpoints._facts_citing`: exact frontmatter citation via `collect_claim_refs` + grammar clean + fabricated terminal excluded; substring scan retired
- [x] RED: face semantics tests

## 3. The farming-chain closure

- [x] the two-junk-files scenario through the real settle path: credit == no-facts baseline, store row `facts_citing: 0`, posterior observation identical
- [x] RED→GREEN: `tests/test_fact_certification_651.py`

## 4. Verification

- [x] focused suites green (state, lint_facts, checkpoints settle, strategy store)
- [x] full fast suite green; ruff clean; comment/invocation/formal-code lints clean
- [x] deploy manifest re-emitted (state.py, checkpoints.py, lint_facts.py rows) + verify
- [x] `openspec validate issue-651-fact-certification` exit 0; `release_receipt.py --check` rc 0
