# phase6-digest-failure-registry

## What
Add mechanical digest generation (2-4KB six-section markdown) + structured failure-registry, replacing full progress.txt cold-start read.

## Why
Cold-start reads ~76K tokens/round (progress.txt 158KB全读). Mechanical 2-4KB digest halves cold-start (target ≤38K). Failure memory currently relies on LLM self-recall (confabulates); structured registry makes it durable.

## Scope
- scripts/digest_build.py: build_digest(ws) / write_digest(ws) / digest_completeness(ws) — six sections (head/sec_a..sec_f), no LLM
- templates/failure-registry.yaml: structured WHEN/THEN/anchor template
- tests/test_digest.py: 8 tests (sections/size-upper/fidelity/completeness/pure/no-llm/structured/empty)
- (deferred) cold-start injection wiring into orchestrator cold-start-contract; E6.1 real-workspace size/cold-start measurement

## Acceptance
- test_digest 8/8 green; full suite green
- numeric fidelity: facts unit field carried verbatim (handoff-check --anchors compatible)
- completeness: new verified fact appears in digest on rebuild
