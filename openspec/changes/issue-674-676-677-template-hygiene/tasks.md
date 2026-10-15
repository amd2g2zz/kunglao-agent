# tasks — issue-674-676-677-template-hygiene

## 1. issue 674 — deployed-manifest version receipt

- [x] `_read_version_from_deployed_manifest()` (carrier read, fail-open
      + warn on corrupt, None on absent/versionless)
- [x] `read_skill_version()` chain: pyproject → plugin.json → receipt →
      raise (guard message names all three sources)
- [x] RED: `test_deployed_copy_resolves_skill_version_with_manifest_fallback`,
      `test_convergence_check_no_crash_on_deployed_copy` (+ precedence,
      guard, corrupt-carrier pins)
- [x] GREEN: all five pass

## 2. issue 676 — terminal claims vs ORPHAN_CLAIM

- [x] Reproduce per the issue recipe (render-marker plan + terminal and
      non-terminal register claims): ORPHAN rows for exactly the terminal
      claims, rc=2, unchanged after re-render
- [x] Fix: `ORPHAN_CLAIM` exempts canonical TERMINAL statuses (option b,
      detector-side; renderer settled section recorded as the open
      complementary option in design.md D2 — owner ratification noted)
- [x] RED/GREEN: `test_plan_drift_no_orphan_after_re_render`,
      `test_plan_drift_proven_exempt_from_orphan_but_still_unverified`,
      `test_plan_drift_orphan_still_fires_for_frontier_claims`

## 3. issue 677 — header comment preservation

- [x] `_leading_header` + `_write_prefix` replace the stamp-only prefix
      (byte-identical header re-prepend, stamp recovery chain kept)
- [x] `main()` split (`_mutate` / `_apply_append`) clears the pre-existing
      C901 on the touched file (design D4)
- [x] RED: `test_ws_yaml_preserves_stamp_and_marker_comments`,
      `test_verify_stamps_empty_after_write`

## 4. Verification

- [x] targeted suites green: register writer, template version, stamps,
      plan-drift family, timeline, deploy lifecycle, convergence matrix,
      verdict logging, write guard, settlement matrix
- [x] `uv run ruff check scripts/template_version.py scripts/ws_yaml.py
      scripts/plan_drift_detector.py` → All checks passed
- [x] comment-hygiene + formal-code lints clean; counts unchanged
      (3/5/15); new tests debt-free (0/0); emit-run collateral reverted
- [x] `deploy_manifest.py --write` re-emitted (3 script shas)
- [x] `openspec validate issue-674-676-677-template-hygiene` exit 0
