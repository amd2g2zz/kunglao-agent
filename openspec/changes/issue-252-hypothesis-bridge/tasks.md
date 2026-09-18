# Tasks — issue-252-hypothesis-bridge

- [x] SDD proposal + design + spec delta (this change)
- [x] RED: mint linkage — family arms mint as claims with
      `competitor_group: hyp-<H-id>` + `hypothesis_ref` + `origin:
      hypothesis-arm`, idempotent by marker, TS-samplable through
      priority_ratio (`tests/test_hypothesis_bridge_252.py`)
- [x] RED: settlement sync — any arm positive -> family confirmed +
      competing group hypotheses superseded; all arms terminal none
      positive -> refuted; mixed -> pending; terminal never rewound;
      wired into claim_migrator (integration via the ungated REFUTED
      path; sync crash never fails the migration)
- [x] RED: candidate-filler routing — #234 siblings and #250 epistemic
      claims stamped with family linkage at their existing mint sites;
      no re-mint, no double representation; sweep converts legacy
      candidate strings to arms and clears them
- [x] RED: lint guard — parked candidate strings error (E1); family
      claim to a nonexistent hypothesis errors (E2); swept/minted
      workspace clean; static writer allowlist test
- [x] RED: no-duplicate-representation — a minted candidate does NOT
      also appear as a store candidate string
- [x] GREEN: scripts/hypothesis_bridge.py (family_group/ensure_family/
      mint_family_arms/mint_pending_candidates/sync_family_ledger/
      check_bridge_lint + CLI)
- [x] GREEN: claim_migrator sync wiring (guarded)
- [x] GREEN: target_ladder.mint_sibling_claims family stamping
- [x] GREEN: plan_epistemics.mint_workspace family stamping + pq-family
      ensure (reuses the #109 binding shapes)
- [x] GREEN: digest_build sweep wiring (fail-open)
- [x] GREEN: hypothesis_seeder._scaffold_body prose contract mechanized
      (candidates=[] preserved)
- [x] Docs: templates/state/claim-register.yaml competitor_group
      comment names the hyp- namespace
- [x] Register the test module in tests/_tiers.py FAST_MODULES
- [x] openspec validate issue-252-hypothesis-bridge exits 0
- [x] Targeted suites + full fast tier (-n 8) + comment_hygiene_lint
      from root + ruff on touched files + deploy_manifest --write/
      --verify green
- [x] Review round 1 (adversarial BLOCK) — all findings fixed:
      F1 #109 admission migrated to count family arms (union with the
      transitional strings face; repair text names the mint path;
      end-to-end sweep-drained -> mint -> first dispatch ADMITTED in
      tests/test_hypothesis_admission_109.py; design D5);
      F2 negative-only refuting reference (DEFERRED/STALE-only stays
      pending; family_verdict single source);
      F3 losing OPEN arms retire claim-level SUPERSEDED on family
      resolution (confirmed + superseded siblings; out of the TS pool);
      F4 sync failure emits family_sync_failed + stderr WARN (no longer
      silent) and lint E3 derivation-divergence face detects a
      persistent crash;
      F5 already-adjudicated families report unchanged (no re-emit);
      F6 allowlist pin hardened (scripts/ AND hooks/, import-line not
      comment mention, raw-frontmatter tier, arm_key collision refusal;
      design D4 five modules);
      F7 check_bridge_lint wired into the digest cold-start face
      (bridge_lint_findings emit + WARN);
      F8 hyp- namespace grammar (H-\\d+) + mint-issued hypothesis_ref
      membership (E2b names capture attempts)
