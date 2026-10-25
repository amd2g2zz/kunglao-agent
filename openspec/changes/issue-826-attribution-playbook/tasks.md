# issue-826-attribution-playbook — tasks

1. [ ] SDD: openspec change directory (this change), `openspec validate`
   clean
2. [ ] RED: `tests/test_attribution_playbook_826.py` — synthetic
   fixtures pin: feature-importance ranking (failure contrast), the two
   distinct failure methods (tool-missing vs hypothesis-wrong), the
   exogenous demotion, switch-without-attribution RED, tune-without-
   delta RED, the 9x dead-path re-probe RED (8+tune GREEN), playbook
   case-specific refusal + method fragment ride, surprise ->
   re-examination commit on the contradiction fixture, the four-knob
   ablation with output-terms pricing, envelope enrichment additive to
   the P2 faces (the episode_start commit key-set pin stays exact)
3. [ ] GREEN: `scripts/rlvr/attribution.py` — feature_importance /
   method_attribution / exogenous demotion / report + digest ref
   (deterministic stdlib counting over the P1 pool; no fitted params,
   no storage, no model calls)
4. [ ] GREEN: `scripts/rlvr/commit_semantics.py` — tune/switch commit
   validation (envelope fields), the dead-path gate (DEAD_PATH_CAP),
   enrich_block (additive envelope decoration), surprise_check +
   reexamination_block, price_ablations (the four-knob face)
5. [ ] GREEN: `scripts/rlvr/playbook.py` — compressed_view over the P1
   playbook view: case-specific refusal, self-starting check,
   support-ranked fragments (no store)
6. [ ] wiring: `meta_retrieval.assemble` serves the compressed playbook
   (KUNGLAO_META_PLAYBOOK switch); `meta_policy.envelope_block` calls
   the additive enrichment; `render_block` additive lines; knobs() two
   additive switch keys
7. [ ] registration: rlvr facade lines, scripts/README.md rows,
   tests/_tiers.py fast-tier entry
8. [ ] trio order: baselines emit FIRST, ext-scan, `deploy_manifest
   --write` LAST, then verify
9. [ ] targeted suites green (`-n 4`), discovery gate ALL-PASS, openspec
   validate clean, evidence + mint (reviewer_id kunglao-p3-826), then
   push + PR (no merge)
