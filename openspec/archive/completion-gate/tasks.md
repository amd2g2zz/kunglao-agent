# Tasks — code-owned completion gate (#55)

## 1. Setup

- [x] 1.1 Worktree wt55 on branch `completion-gate` at dev baseline `4192703` (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline measured: scripts/ 226 passed; tests/ 309 passed + 1 skipped + 6 pre-existing failures (test_acceptance meta-gate, test_skill_lte_500_lines, 4× test_convergence_completeness)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: termination is LLM discretion; layering vs #43/#44/#54; task-oracle.yaml + 4 exit codes)
- [x] 2.2 design.md (D1-D10 + R1-R5; D3 = user-vs-agent deny-list; D4 = #54 reason-enhancement; D7 = 全面 extended check; D8/D9 = activation + FAIL_OPEN)
- [x] 2.3 spec.md (REQ: judge 4 exit codes / mechanical deny-list / precedence 3>2>1>0 / 全面 zero-tolerance / CLI exit=exit_code / Stop shim activation+FAIL_OPEN+block-decision / wire_up Stop idempotent + ALL_HOOKS / cross-ref #43#44#54)
- [x] 2.4 tasks.md
- [x] 2.5 README.md
- [x] 2.6 `openspec validate completion-gate` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 `test_exit0_all_closed`: 3 items all closed_by set → exit 0, reason contains PASS (Acceptance 3 + base PASS)
- [x] 3.2 `test_exit1_regression_2026_08_11`: oracle = issue task_text + 6 unsigned open_items [G4,G5,G6,#10,#11,#12] → exit 1 + reason names all 6 (Acceptance 2 — replay regression)
- [x] 3.3 `test_exit2_agent_self_signed_defer`: defer authorized_by="agent" → exit 2 (Acceptance 4 negative)
- [x] 3.4 `test_exit2_empty_authorized_by`: defer authorized_by="" → exit 2
- [x] 3.5 `test_exit3_none_oracle`: judge(None) → exit 3
- [x] 3.6 `test_exit3_empty_task_text`: oracle {} → exit 3
- [x] 3.7 `test_exit3_whitespace_task_text`: task_text="   " → exit 3
- [x] 3.8 `test_user_signed_defer_passes`: defer authorized_by="用户" resolves the item → exit 0 (Acceptance 4 positive)
- [x] 3.9 `test_source_agent_overrides_user_like_authorized_by`: source="agent" + authorized_by="hr" → exit 2
- [x] 3.10 `test_precedence_exit2_wins_over_exit1`: unsigned defer + unresolved item → exit 2
- [x] 3.11 `test_comprehensive_keyword_in_reason`: 2026-08-11 task_text (全面分析) → exit 1 + reason contains 全面/comprehensive
- [x] 3.12 `test_comprehensive_rejects_tier_language_defer`: 全面 task_text + defer reason "备注级" → exit 2
- [x] 3.13 `test_comprehensive_keeps_genuine_user_defer`: 全面 task_text + defer reason "不用查" → exit 0
- [x] 3.14 `test_cli_exit_codes_and_json`: CLI exit 0 all-closed / exit 1 regression / exit 3 missing file; JSON well-formed
- [x] 3.15 `test_premature_termination_fingerprint_folding`: declaration_text supplied + exit 1 → reason carries fingerprint id (D4 #54 integration)
- [x] 3.16 `test_module_docstring_cross_references_43_44_54`: module docstring names #43, #44, #54
- [x] 3.17 Stop-shim tests: `test_stop_not_activated_passthrough`, `test_stop_activated_blocks_exit1`, `test_stop_stop_hook_active_passthrough`, `test_stop_malformed_oracle_blocks_exit3`, `test_stop_activated_no_oracle_passthrough`
- [x] 3.18 Wire-up tests: `test_all_hooks_contains_completion_gate`, `test_wire_up_registers_stop_completion_gate`, `test_wire_up_stop_idempotent`
- [x] 3.19 Confirm RED: `python -m pytest tests/test_completion_gate.py -q` → ModuleNotFoundError (scripts/completion_gate.py + hooks/completion_gate.py not yet implemented)

## 4. GREEN — scripts/completion_gate.py + hooks/completion_gate.py

- [x] 4.1 `judge(oracle, declaration_text=None)`: precedence 3>2>1>0; mechanical deny-list (AGENT_IDENTIFIERS + source field); 全面 keyword detection + tier-language defer rejection; #54 fingerprint folding via premature_termination_detect.detect (optional, declaration_text supplied)
- [x] 4.2 `main()` CLI: argparse `<oracle-file>` + `--declaration-file`, yaml.safe_load the oracle, JSON verdict, process exit = exit_code
- [x] 4.3 `hooks/completion_gate.py` Stop shim: stdin payload → resolve workspace (first with task-oracle.yaml) → strict activation (is_active_strict) → stop_hook_active anti-loop → call judge → emit `{"decision":"block","reason":...}` or pass-through; FAIL_OPEN at every layer
- [x] 4.4 module docstring cross-references #43, #44, #54 as complementary
- [x] 4.5 Confirm GREEN: `python -m pytest tests/test_completion_gate.py -q` → 41 passed

## 5. wire_up_settings Stop section + ALL_HOOKS

- [x] 5.1 `scripts/wire_up_settings.py`: add `_ensure_stop` + a `Stop` section registering hooks/completion_gate.py (no matcher; dedupe by command basename); preserve existing PreToolUse/PostToolUse entries
- [x] 5.2 `scripts/hook_activation.py`: add `completion_gate` to `ALL_HOOKS`
- [x] 5.3 Confirm wire-up tests pass via `_patch_home` monkeypatch (NEVER the real ~/.claude/settings.json)

## 6. Validation

- [x] 6.1 `python -m pytest tests/test_completion_gate.py -q` → 41 passed
- [x] 6.2 `python -m pytest scripts/ -q` → 226 passed, 0 failures (no regression)
- [x] 6.3 `python -m pytest tests/ -q` → 350 passed (309 baseline + 41 new), 1 skipped, the SAME 6 pre-existing failures unchanged
- [x] 6.4 `openspec validate completion-gate` PASS (final)

## 7. Commit + PR

- [x] 7.1 Commit SDD artifacts (`4563c86`)
- [x] 7.2 Commit RED tests (`ed92fed`)
- [ ] 7.3 Commit GREEN impl (scripts/completion_gate.py + hooks/completion_gate.py + wire_up_settings + hook_activation)
- [ ] 7.4 Push branch `completion-gate`, `gh pr create --base dev --head completion-gate` with body file
- [ ] 7.5 Do NOT merge; orchestrator verifies independently first (PR left OPEN)
