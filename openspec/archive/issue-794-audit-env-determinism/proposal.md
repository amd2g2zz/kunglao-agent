# Audit subprocess env determinism — behavioral-var scrub + UTF-8 forced IO (#794)

## Why

`tests/test_v012_milestone_audit.py::_run_cli` builds the child environment
with `full_env = dict(os.environ)` — full inheritance of the parent shell.
Any behavioral env var the parent carries therefore flows into every kunglao
CLI the replay suite drives, and `kunglao-init`'s #276 Phase-0 environment
guard (HARD REJECT on truthy `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) fires
before the bins/toolchain logic the test is actually pinning. Issue #794
reports exactly this on a Windows machine: `test_replay_init_refuses_empty_bins`
"fails" with a diagnostic that talks about AGENT_TEAMS instead of
bins/analysis target. Orchestrator attribution (issue comment, 2026-08-27):

- dev HEAD `225005d` CI green + macOS/UTF-8 clean-env run green (both replay
  tests pass) → NOT contract drift, NOT a behavior regression.
- Polluted parent shell (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) reproduces
  the Windows symptom verbatim on macOS → environment attribution confirmed.
- Second, unconfirmed leg: Windows GBK decode of child output (the helper
  uses `text=True` — locale decode, no `errors` policy), same failure family
  #457 already fixed elsewhere. test 1 (exit=0 missing `state_hash`) does not
  match the AGENT_TEAMS symptom, so the decode face must be covered too.

## What Changes

Test-side only; zero product-code changes:

1. `tests/test_v012_milestone_audit.py::_run_cli` becomes a deterministic
   subprocess seam:
   - scrub behavioral env vars (currently the single #276 flag) AFTER the
     explicit `env=` merge, so neither the parent shell nor a caller can leak
     them into the child;
   - `setdefault("PYTHONUTF8", "1")` + `setdefault("PYTHONIOENCODING",
     "utf-8")` (explicit caller values still win — the existing `env=`
     override contract is preserved);
   - `subprocess.run(..., encoding="utf-8", errors="replace")` replacing bare
     `text=True` (mirrors conftest `golden_master` and the #457 encoding
     fixes; `returncode/stdout/stderr` CompletedProcess shape unchanged).
2. New pin file `tests/test_audit_env_determinism_794.py` — echo-probe pins
   on the real `_run_cli` (imported from the audit module, no fixture copy).
3. Same-class helper `tests/test_exit4_no_repair_e2e.py::_run` (also drives
   the real `kunglao-init.py` via full `dict(os.environ)` inheritance) gets
   the identical scrub+UTF-8 treatment.

## Impact

- **Affected**: `tests/test_v012_milestone_audit.py`,
  `tests/test_exit4_no_repair_e2e.py`, new
  `tests/test_audit_env_determinism_794.py`, this change folder.
- **Unaffected**: all product code under `scripts/`, `hooks/`, `tools/` —
  the #276 gate itself is correct behavior for real sessions; only the test
  harness stops importing session state from whatever shell launched pytest.
- **Risk**: low. `setdefault` keeps explicit `env=` overrides working; the
  scrub list is additive and pinned by the new pin file.
