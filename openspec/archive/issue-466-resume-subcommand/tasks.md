# Tasks: resume subcommand (issue #466)

- [x] 1. SDD trio (this change) — proposal / design / tasks
- [x] 2. RED: `tests/test_kunglao_resume.py` failing on baseline (module
       absent, registry 3-command) — commit hash recorded
- [x] 3. GREEN: `scripts/kunglao_resume.py` — health / summary / data-age /
       timeline / next-step lookup, text + `--json`, rc 0/1/2, read-only
- [x] 4. GREEN: `scripts/kunglao.py` `resume` subcommand (delegation, no
       logic)
- [x] 5. GREEN: `skills/subcommands.yaml` resume record + three render
       surfaces (root SKILL.md menu/routing/next-steps, skills/resume/
       SKILL.md, README table, skills/help/SKILL.md row)
- [x] 6. GREEN: widen `tests/test_subcommand_zeroarg_ux.py` registry
       assertions to four commands; add `kunglao_resume.py` to
       `tests/test_cli_matrix.py` CLIS
- [x] 7. Negative paths: empty/nonexistent workspace → rc 2 + init
       guidance; stale heartbeat → STALE annotation + rc 1 + #461 re-arm
       advice
- [x] 8. Degradation drills ≥3 missing sources, behavior matches design
       D3 matrix
- [x] 9. Gates: ruff clean; quick pytest green; worktree-local
       `devkit/quality_gates.py` ALL-PASS; Gate 5
       `.subagent-review/2026-08-20-466.json` (verified_by pending
       reviewer)
- [x] 10. RUNBOOK (`.review/RUNBOOK.md`, never committed): change list,
        test map, self-identified risks
