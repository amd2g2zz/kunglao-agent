# Tasks — target-alignment (#455)

## 1. Setup

- [x] 1.1 Branch `v012/issue-455-target-alignment` off `dev` 6462fe4 (one issue / one PR / one branch / one worktree at D:/works/kunglao-wt/455)
- [x] 1.2 Baseline quick gate green: `uv run --project . python -m pytest -q -m "not load_sensitive"` (recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: 6-item evidence chain — sniff-first-file, type=env-contract selector, containers unmodeled, silent sniff acceptance, undefined zero-arg, CLAUDE.md consumes type only)
- [x] 2.2 design.md (D1-D8 + R1-R5 rejected)
- [x] 2.3 spec.md (REQ: pending fail-closed / multi-file target / container listing / android VM-channel negative / zero-arg order / input-zero / task_spec render / #449 chain slot)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate issue-455-target-alignment` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `tests/test_decision_pending.py` — round-trip to_json/from answers, non-object rejection
- [x] 3.2 no `--type` non-interactive: pending list + exit 8, zero scaffold, sniff NOT accepted (checkbox 1)
- [x] 3.3 multi-file bins/: target decision mandatory, no default; resolve picks a non-sorted-first file and it reaches C-001/CLAUDE.md (checkbox 2)
- [x] 3.4 MSI (CFBF fixture) + APK (zip fixture): container detected, contents listed, type never guessed (checkbox 3)
- [x] 3.5 android: no vm_reachable/remote_debugger items, `_tcp_connect` zero calls; windows still has vm_reachable (checkbox 4)
- [x] 3.6 zero-arg: pending `workspace` first decision, no bare argparse error; malformed-flag usage still RC_ERROR=1 (checkbox 5)
- [x] 3.7 AST gate: no `input()`/`builtins.input()` call in scripts/*.py (checkbox 6)
- [x] 3.8 CLAUDE.md render: task_spec vm_detonation + scope-out present; absent file → no section, no residue; corrupt yaml → RC_ERROR (checkbox 7)
- [x] 3.9 E2E chain: zero-arg → resolve workspace → resolve target+type → task_spec → CLAUDE.md constraints → android toolchain report, one chain (checkbox 8)
- [x] 3.10 resolve misuse: unknown target / bad json → RC_ERROR=1
- [x] 3.11 Confirm RED: collection error (decision_pending missing) / assertion failures recorded; commit `test: RED <behavior> (#455)`

## 4. GREEN

- [x] 4.1 `scripts/decision_pending.py` — PendingDecision/PendingDecisionList + to_json + answers loaders
- [x] 4.2 `kunglao-init.py` — survey_bins / file_kind / container_listing / cfb stream names; align_target matrix; emit pending + RC 7; `--target` / `--resolve`; workspace nargs="?"
- [x] 4.3 delete prompt_type / resolve_type / sniff_type; detect_sample(ws, target)
- [x] 4.4 `write_claudemd` task_spec section + `templates/CLAUDE.md.base.tmpl` slot; analysis_target_object persistence
- [x] 4.5 `toolchain.py` CHECK_SETS + NEVER_CHECKS; `toolchain_install.py` input() removal; run() isatty branch removal
- [x] 4.6 migrate legacy cases in test_init_typeaware.py / test_init_exit_codes.py to the new contract
- [x] 4.7 docs: skills/init/SKILL.md, skills/kunglao-agent/SKILL.md, agents/kunglao-init-worker.md, kunglao-init docstring
- [x] 4.8 quick gate green: `uv run --project . python -m pytest -q -m "not load_sensitive"`

## 5. REFACTOR + validation

- [x] 5.1 extract helpers where duplicated; keep functions <50 lines; RC_* constants; fail-closed branches reviewed
- [x] 5.2 re-run quick gate; `python -c "import scripts.convergence_check"` smoke
- [x] 5.3 `.review/RUNBOOK.md` (change list / checkbox↔test map / risks / RED hash / gate tail)

## 6. Commit

- [x] 6.1 `sdd(target-alignment): intake step 0 — proposal/design/spec/tasks (#455)`
- [x] 6.2 `test: RED <behavior> (#455)`
- [x] 6.3 `feat(target-alignment): <summary> (#455)` (GREEN + docs)
- [x] 6.4 `refactor/docs` as needed (no history rewrite; no push)
