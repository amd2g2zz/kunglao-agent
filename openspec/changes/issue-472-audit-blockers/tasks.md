# tasks — issue-472-audit-blockers

## 1. RED (TDD — tests first, each fix)

- [ ] 1.1 Wave cage RED (tests/test_e2e_runner.py): mid-wave raising
  act → siblings' records land + ERROR ActRecord + dispatch_result row
  with caged null reason; wave-of-one raising act caged (no raise);
  auto-face missing prompt_file → ERROR record + "prompt_file_unreadable".
- [ ] 1.2 resolve_claims RED (tests/test_e2e_runner.py): corrupt YAML
  → warn present + defaults restored; non-dict spec → warn;
  anchors-absent → silent; MISSING spec file → silent (D-6 face).
- [ ] 1.3 retry-counter RED (tests/test_max_retries_604.py): garbage
  counter file → {} + one rate-limited warn (deduped on second read).
- [ ] 1.4 _safe_int RED (tests/test_kunglao_log.py + audit twin in
  tests/test_e2e_runner.py): garbage duration_ms/exit/epoch → no raise,
  null + value_unparseable reasons; float('inf') → null (OverflowError
  caged, D-1); float('nan') → null; garbage epoch does NOT re-inherit
  the tick (ordering pin, D-3); numeric strings still coerce.
- [ ] 1.5 exit-registry RED (tests/test_hook_exit_codes.py): ExitCode
  4/5/6/7 pinned; completion_gate + workguard_gate rows present with
  documented faces; shim constants == registry values == literals
  (drift-guard transfer pin, D-2; test_notes_closure_762's substring
  pin must stay green untouched).
- [ ] 1.6 pipeline-cage RED (tests/test_e2e_runner.py): raising
  checkpoint step → FAIL result + report written + EXIT_CHECKPOINT_FAIL.

## 2. GREEN (implementation, minimal diffs)

- [ ] 2.1 llm_faces: `_wave_act` helper (cage both wave paths) +
  prompt-file guard in AutoLlmFace.run_dispatch; audit.py
  emit_dispatch_result gains additive exit_null_reason kwarg.
- [ ] 2.2 checkpoints._resolve_claims: is_file pre-check (silent),
  kunglao_log.warn "e2e.resolve_claims" on spec-unreadable (except +
  non-dict branch); import kunglao_log.
- [ ] 2.3 worker_budget_gates.read_retry_counter: warn on parse
  failure (kunglao_log.warn dedupe = rate limit).
- [ ] 2.4 kunglao_log: `_safe_int` (TypeError/ValueError/OverflowError)
  + apply ONLY at the event-dict coercion sites (ordering rule D-3) +
  value_unparseable reasons added before the AUTO_NULL sweep +
  docstring amendments (emit epoch paragraph, AUTO_NULL_FIELDS note,
  audit.py twin comment).
- [ ] 2.5 hook_exit_codes: ExitCode 4-7 + completion_gate row + enum
  comment amendment (exit-1 dual meaning) + header reconciliation
  (0-vs-nonzero + stdout-JSON Stop-hook mechanism, D-4);
  hooks/completion_gate.py constants derive from the registry in a
  SEPARATE try/except after the existing block (D-5) with per-constant
  literal fallbacks.
- [ ] 2.6 checkpoints.run_pipeline: step cage via `_record` FAIL
  (error detail in evidence JSON only — D-8 tradeoff documented).

## 3. Gates

- [ ] 3.1 pytest touched suites green (test_e2e_runner, test_kunglao_log
  + channel, test_max_retries_604, test_hook_exit_codes,
  test_top1_reject_603, completion/workguard/notes-closure/notes-fake/
  summary-fake suites), `-n 4`.
- [ ] 3.2 ruff clean on touched files (pre-existing E501 at
  hooks/completion_gate.py:55 noted as baseline).
- [ ] 3.3 `devkit/quality_gates.py --quick` green.
- [ ] 3.4 `scripts/comment_hygiene_lint.py` clean; PAIRED re-mint when
  comments land (--emit → deploy --write → mint → commit).
- [ ] 3.5 detect_changes equivalent: git diff review vs origin/dev
  (gitnexus MCP face unreachable this session — documented
  substitution).

## 4. Review gate

- [ ] 4.1 Independent code-reviewer subagent over the staged diff →
  PASS.
- [ ] 4.2 Evidence `.claude/reviews/472-*.md` (reviewer- id, verdict
  PASS, diff_sha256 = staged binary sha) → review_gate.py mint.

## 5. Ship

- [ ] 5.1 Push branch, PR to dev, body with openspec mapping table +
  per-fix test evidence + gates output.
- [ ] 5.2 CI five legs green (GnuTLS flake → rerun --failed; never
  merge red) → `gh pr merge --merge`. Do NOT close #472.
