# Tasks — issue 1086 S18 (wake gate wiring)

## 1. Premise checks (before writing code)

- [x] The wrapper does not exist: `git grep -ln wake_gate -- scripts hooks
      skills` → only `heartbeat_tick.py` (the gate), `mechanisms.yaml` (the
      declaration) and the 801 test; `external_kicker.py` is the dead-session
      kicker, not it (chain brief's measured facts, re-verified by grep).
- [x] The gate is real and quiet-clean: `experiments/scheduler/
      quiet_day_replay.py` baseline run on the untouched tree → P1/P2/P3 all
      PASS (quiet 288 polls/0 wakes, material 5 events/5 wakes, noise 288
      rows/0 wakes) — output in the s1 handoff.
- [x] Existing checks not rebuilt: `tests/test_economics_801.py` already pins
      the gate (predicate, quiet-hour zero prompts, stale-heartbeat wake);
      the new module pins the CONSUMER only.
- [x] Blast radius (GitNexus `impact`, upstream): `build_prompt` LOW (15
      impacted, 3 direct), `verify_loop` LOW (12), `constitution` LOW (3) —
      no signature changes, text only.

## 2. RED first

- [x] `tests/test_wake_gate_wiring_1086.py` written against the missing
      module: 18 failed (`ModuleNotFoundError: No module named
      'heartbeat_wake_gate'` + the contract pins) — RED output in the s1
      handoff.

## 3. The wrapper

- [x] `scripts/heartbeat_wake_gate.py`: gate_argv / build_crontab_line /
      build_schtasks_command (strings only) / run_gate (runner seam) /
      classify (rc AND marker) / loop_prompt (the emitter) / session_alive
      (the #39 predicate) / inject (stage + conditional kick, deliver seam) /
      wake_pass / main (`--wake-gate`, `--dry-run`, `--print-registration`,
      `--interval-min`, `--claude-bin`, `--gate-timeout`).
- [x] Exit codes: 0 quiet / 3 wake / 2 stop / 1 fault-loud.

## 4. The contract

- [x] SKILL.md activation block: the wrapper registration line + the emitter
      line relabeled (payload + armed watchdog; no issue numbers in the
      body — the skill-contract lint pins that).
- [x] SKILL.md 1.4: QUIET carve-out; idle-fault and THINK EMPTY-forbidden
      scoped to a WAKEN tick; the WAKE sentence verbatim.
- [x] `heartbeat_loop_prompt.py`: registration docstring, step-0 tick in gate
      mode with the QUIET branch, `--verify` fix guidance naming the wrapper.
- [x] `kunglao_resume.py` REARM_ADVICE: gate-first, watchdog kept.
- [x] `mechanisms.yaml`: `wake_gate.entry` → the wrapper; description +
      cockpit_signal updated.
- [x] Closeout appeal #1 — the four remaining prompt-first surfaces rewritten
      gate-first with the watchdog wording kept:
      `hooks/worker_budget_sinks.py` (REJECT_FIX envelope + not-registered
      message), `references/governance/guardrails.md` §6.1,
      `references/contracts/cold-start-contract.md`, and
      `scripts/eval_loop_runner.py`'s TICK_GATE remedy; references/_INDEX.yaml
      re-pinned; three drift-back pins added (gate line BEFORE the
      CronCreate line).

## 5. Registration triple + baselines

- [x] `scripts/README.md` catalogue row.
- [x] `tools/ext-scan.py` regeneration (7 new index lines).
- [x] `deploy-manifest.yaml` regeneration — LAST, after content freeze
      (667 entries, --verify OK).
- [x] `scripts/hygiene_baseline.yaml` + `scripts/formal_code_baseline.yaml`
      re-emitted for the new files (both lints clean).

## 6. Verification

- [x] New module GREEN: 18 passed (seam pins + the real-CLI production path
      through the real gate, `--dry-run`).
- [x] Contract-surface regressions: economics_801 / loop_prompt_split_434 /
      heartbeat_off / prompt_command_611 / reset_continuity_616 /
      kunglao_resume / heartbeat_bootstrap / heartbeat_autonomy_754 /
      init_handoff / framework_rigidity_57 / mechanism_scheduler_878 /
      declaration_scan / ext_index / contract_docs /
      project_skill_deploy_1002 / worker_death_resume_11 /
      difficulty_thresholds_16 / dispatch_contract /
      write_contract_visibility_523 / loop_completion_contract_523 /
      scorer_authority / verify_truth_609 / envelopes / skill_contract /
      cognition_759 / canonical_chain_752 / doc_sync — all green.
- [x] `quiet_day_replay.py` re-run after the change: three pins PASS,
      identical numbers (after-output in the s1 handoff).
- [x] `openspec validate issue-1086-wake-gate-wiring --strict` valid;
      `--changes` totals 110 passed / 0 failed.
- [ ] devkit quality gates (1 3 4 5 6 7 8 9 10) at commit time
      (s1 runs them at the commit step; the closeout re-runs the full set).
- Known environment-blocked (fails on the CLEAN tree too, offline z3 wheel
  cache miss): `test_upgrade_016_sweep.py::test_hook_wiring_runs_in_framework_env`
  — CI owns it.

## 7. S21 — the wake decision wiring

- [x] Premise re-verified on this tree: `intelligent_scheduling` had no
      runtime caller (grep hits: README / registry comments / its own
      module) — the seat #685 recorded, nothing applied.
- [x] RED first: `tests/test_wake_decision_wiring_1086.py` — 12 failed
      / 1 passed (the quiet pin, correctly green) before the wiring;
      RED output in the S21 s1 handoff.
- [x] `scripts/heartbeat_wake_gate.py`: the WAKE branch consults
      `intelligent_scheduling.decide` via `_real_wake_decision` (lazy
      import; `decide`/`decision_rng` seams; `--decision-seed` CLI face
      for deterministic replay), records the decision block on the
      receipt, and a drawn `none` injects nothing (recorded, rc 3).
- [x] `scripts/intelligent_scheduling.py`: `probability_source` added to
      the record + signal row (selection_law_exact / unknown — the
      dispatch vocabulary; deterministic faces never impersonate a law).
- [x] GREEN: 13 passed; the four draw-sensitive S18 pins pinned with
      fixed rng / `--decision-seed 0`.
- [x] `quiet_day_replay.py` re-run after the change: three pins PASS
      (output in the S21 s1 handoff).
