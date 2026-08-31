# Design — #794 audit subprocess env determinism

Reproduction base: worktree branch `fix/794-audit-env-determinism` off dev
`225005d`. Baselines measured on this machine (macOS, UTF-8 locale):

| Parent shell state | `tests/test_v012_milestone_audit.py` |
|---|---|
| clean (`env -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) | 14 passed, 1 skipped |
| polluted (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | 2 failed — `test_replay_init_minimal_workspace_contract`, `test_replay_init_refuses_empty_bins`; stderr = `kunglao-init: HARD REJECT — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is truthy ('1'); scaffold blocked...` |

The polluted stderr matches the issue's Windows report symptom class
(diagnostic contains no bins/analysis-target vocabulary) — mechanism
confirmed, not inferred.

## Core decision: inherit-minus-behavioral, NOT a full env sandbox

`_run_cli` keeps `dict(os.environ)` as its base. Rationale:

- `_run_cli` resolves the interpreter dynamically (`sys.executable`), the
  #457 lesson: hard infrastructure pins broke the CI matrix. A full env
  sandbox (whitelist-allowlist) would have to re-derive PATH, PYTHONPATH,
  venv activation vars, proxy vars — every one of those a silent-failure
  generator on a contributor machine we never see. Infrastructure vars are
  load-bearing; behavioral vars are the actual defect surface.
- Precedent: `conftest.py::golden_master` pops exactly the var it knows it
  consumes (`PRIORITY_WEIGHTS`); `test_template_version_536.py` and
  `test_workspace_carriers_538.py` filter exactly
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. The repo convention is
  inherit-minus-known-behavioral, maintained as an explicit list.

## Behavioral-var list maintenance

```python
# Behavioral env vars: change the CLI's exit path / decision flow rather than
# its infrastructure. Each entry cites the gate that consumes it.
_BEHAVIORAL_ENV_VARS = (
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",  # #276 Phase-0 HARD REJECT gate
)
```

- Pop happens AFTER the `env=` merge: the scrub is the last word. A caller
  passing `env={"CLAUDE_...": "1"}` must not be able to re-pollute the child
  (the pin test asserts exactly this direction).
- Whitelist-extension procedure: a new behavioral var is added here + to the
  pin test's scrub loop + a one-line comment citing the consuming gate.
  Anything observed to alter CLI decision flow in future (#449 pending-list,
  target-alignment) joins this tuple; infrastructure vars (PATH, PYTHONPATH,
  HOME, venv vars) never do — see sandbox rationale above.

## UTF-8 forced IO (covers the unrefuted Windows GBK leg)

- Child side: `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` via `setdefault` —
  explicit caller values win, preserving the `env=` override contract that
  exists today (`full_env.update(env)`).
- Parent side: `encoding="utf-8", errors="replace"` replaces `text=True`.
  Same CompletedProcess shape (`returncode: int`, `stdout/stderr: str`);
  #457 items #2-#5/#12 established this exact repair for other seams, and
  `conftest.py::golden_master` already carries the identical pair with the
  GBK rationale comment (#317 stdout contract).

## Pin strategy (tests/test_audit_env_determinism_794.py)

Echo-probe subprocesses through the REAL `_run_cli` (imported via
`importlib` from `test_v012_milestone_audit.py` — no helper copy, so the pin
cannot drift from the seam it pins). No heavy init fixtures:

- Pin A (scrub): run an `python -c` probe printing the flag's value under
  `env={FLAG: "1"}` → child must see the scrubbed (absent) value. Also pin
  the verbatim #794 symptom at the behavioral level: empty-bins init refusal
  under `env={FLAG: "1"}` must diagnose bins/analysis-target, not the gate.
- Pin B (UTF-8): probe asserts child sees `PYTHONUTF8=1` /
  `PYTHONIOENCODING=utf-8` (after `monkeypatch.delenv` so the pin cannot pass
  vacuously on a machine that already exports them); a setdefault-contract
  probe asserts explicit `env={"PYTHONUTF8": "0"}` still wins; a latin-1
  child-output probe asserts the capture side survives non-UTF-8 bytes with
  usable text attributes (strict `text=True` decode raises → this pin is RED
  pre-fix on any non-latin-1 host).

## Sweep verdict (dict(os.environ) in tests/)

| Site | Runs flag-gated CLI? | Verdict |
|---|---|---|
| `test_v012_milestone_audit.py:127` | yes (kunglao-init, #794 target) | fixed in this change |
| `test_exit4_no_repair_e2e.py:174` | yes (drives real `kunglao-init.py`; gate would flip the forced exit-4 into exit-3) | same-batch fix |
| `conftest.py:111` (golden_master) | no (convergence/health/plan CLIs; none consume the flag); already utf-8 replace | no change |
| `test_suite_health.py:122` (golden replay) | no (same golden set); `text=True` locale decode is a latent #457-class gap but no consuming var and no observed failure | reported, no change |
| `test_trajectory_replay.py:70` | no (ask_for_direction_gate / failure_analysis_gate / convergence_check / kunglao_resume / heartbeat_loop_prompt consume no flag); already utf-8 replace + `PYTHONIOENCODING` | no change |
| `test_bindiff.py:43` / `test_ghidra_async.py:42` | no (ghidra tool CLIs consume no flag) | no change |

## Alternatives rejected

- **Full env sandbox** — breaks #457's dynamic-resolution lesson; rejected.
- **Skip-if-flag-set guard** — hides the leak instead of fixing it; the
  polluted run would silently lose the replay coverage the suite exists for.
- **Fixing the suite's CLIs to ignore the flag under pytest** — product-code
  change to satisfy a test harness; the gate is intentional session-scope
  behavior (#233/#276); rejected.

## Measured evidence (this branch, macOS/UTF-8 worktree)

| Run | Command | Result |
|---|---|---|
| pre-fix clean baseline | `env -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS … pytest tests/test_v012_milestone_audit.py -q --no-cov` | 14 passed, 1 skipped |
| pre-fix polluted baseline | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 … pytest tests/test_v012_milestone_audit.py -q --no-cov` | **2 failed** (`…minimal_workspace_contract`, `…refuses_empty_bins`; stderr = #276 HARD REJECT text) |
| RED pins | `… pytest tests/test_audit_env_determinism_794.py -q --no-cov` (pre-fix seam) | **5 failed, 1 passed** — the pass is the setdefault override-contract pin (green by design in both phases); latin-1 pin died with `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9` (strict `text=True`, the #794 Windows leg reproduced on macOS) |
| GREEN clean | `… pytest tests/test_v012_milestone_audit.py tests/test_audit_env_determinism_794.py -q --no-cov` | 20 passed, 1 skipped |
| GREEN polluted | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 … pytest tests/test_v012_milestone_audit.py -q --no-cov` | 14 passed, 1 skipped (was 2 failed) |
| sweep RED | polluted `… pytest tests/test_exit4_no_repair_e2e.py -q --no-cov` (pre-fix) | 1 failed, 6 passed (forced exit-4 flipped to #276 gate exit) |
| sweep GREEN | same file, clean + polluted | 7 passed both |
| trio clean | all three touched test files | 27 passed, 1 skipped |
| full suite (worktree) | `… pytest -q --junitxml` | 4516 tests, **2 failed — pre-existing machine-local**: `test_env_drift_475…test_noop_without_substrate` + `test_toolchain…test_android_server_fail_without_listener` reproduce identically on **pristine origin/dev 225005d** on this host (real adb device attached: `adb devices` → `wslvyltsoft8yxba device`); zero coupling to this branch's files; zero delta |
| quality gates | `devkit/quality_gates.py` | Gates 1,3,4,5,6,7 PASS; Gate 2 blocked by the two machine-local reds above (host has live adb), green in CI |
| release receipt | `scripts/release_receipt.py --check` | exit 0 |
| lint | `ruff check .` | All checks passed |
