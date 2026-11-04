# Tasks — issue-365-distill-engine

1. [x] SDD: openspec proposal/design/spec referencing the #365 binding
       rulings + A1-A5 (this folder).
2. [x] TDD RED: tests/test_distill_schema_365.py — distill-item/1 lint
       (field table reds, JSON schema, episode projections).
3. [x] `scripts/distill_schema.py` GREEN: dataclass + JSON schema + lint.
4. [x] TDD RED: tests/test_distill_score_365.py — dimension extremes,
       threshold abandon, assessor identity recording.
5. [x] `scripts/rlvr/distill_score.py` GREEN: mechanical dims (rule lint /
       density / recall-delta) + injected assessor + score-aware playbook
       ordering (P3 leftover close).
6. [x] TDD RED: tests/test_distill_rollout_365.py — reward bands, adverse
       evidence gate, ledger rows, EMIT_ACTIONS word, prior fold.
7. [x] `scripts/rlvr/distill_rollout.py` GREEN + event_taxonomy word.
8. [x] TDD RED: tests/test_distill_lifecycle_365.py — 3-strike rounds,
       re-admission, exhaustion removal from surfaces, ledger archive.
9. [x] `scripts/rlvr/distill_lifecycle.py` GREEN.
10. [x] TDD RED: tests/test_distill_dgate_365.py — three-question pass/fail.
11. [x] `scripts/rlvr/distill_dgate.py` GREEN.
12. [x] TDD RED: tests/test_hybrid_distill_365.py — research loop (barren
        abandon, budget caps, mock search injection, no network IO pin),
        self pipeline over a synthetic workspace, conflict flags + lineage
        wall.
13. [x] `tools/auxiliary/hybrid_distill.py` GREEN (--strategy self|hybrid).
14. [x] mechanisms.yaml event-driven entry (trigger.type: event,
        cost_class, cockpit_signal).
15. [x] Registration: scripts/README.md + scripts/rlvr/README.md + rlvr
        facade; ext index baseline + tools/_index-auxiliary.md +
        tools/_INDEX.yaml; deploy-manifest --write LAST.
16. [x] Gates: uv-only, targeted pytest -n 4 ALL-PASS, quality gate 9,
        ext-scan, deploy-manifest verify, openspec validate.
