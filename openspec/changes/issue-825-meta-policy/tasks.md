# issue-825-meta-policy — tasks

1. [ ] SDD: openspec change directory (this change), `openspec validate` clean
2. [ ] RED: `tests/test_meta_policy_825.py` — synthetic fixtures pin:
   feature assembly from the three real sources (die/apkid/task_spec/
   capability facts, read-only), the 17/17 same-family-different-context
   commit pin, cold-start prior selection, both-phase retrieval
   visibility (episode_start + commit_boundary), the single-interface
   envelope + render marker, dispatch-context wiring (optional fail-open
   key), the three knob groups' effect, both ablation switches, the
   bandit-demotion grep pin, the utility chain (retrieved → cited →
   improved)
3. [ ] GREEN: `scripts/rlvr/meta_context.py` — feature assembly
   (task_spec + die/apkid salients + #812 capability facts, read-only,
   deterministic, schema-capped)
4. [ ] GREEN: `scripts/rlvr/meta_policy.py` — the three knob groups,
   cold_start_prior (the only q_cells consult on the meta path),
   select_commit (overlap-weighted value table + n-shrinkage),
   envelope_block + render_block (meta-policy/1, the single
   interface), utility chain faces (stamp_retrieved / record_citation
   / utility_chain)
5. [ ] GREEN: `scripts/rlvr/meta_retrieval.py` — phase-legal retrieval
   assembly (utility-score rank, threshold, budget cap, playbook
   attach, ablation switches)
6. [ ] wiring: `scripts/dispatch_context.py` build_dispatch_context —
   optional `meta_policy` key, fail-open (providers pattern)
7. [ ] registration: rlvr facade lines, scripts/README.md rows,
   tests/_tiers.py fast-tier entry
8. [ ] trio order: baselines emit FIRST, `deploy_manifest --write` LAST
   (dispatch_context imports pull the meta modules into the deploy
   closure)
9. [ ] targeted suites green (`-n 4`), local gates ALL-PASS, evidence +
   mint (reviewer kunglao-p2-825), then push + PR (no merge)
