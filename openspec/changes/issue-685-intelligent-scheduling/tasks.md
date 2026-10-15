# tasks — issue-685-intelligent-scheduling

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-685-intelligent-scheduling` (proposal,
      design, tasks, specs/intelligent-scheduling/spec.md) — the design
      carries the null-action baseline comparison protocol.
- [x] 1.2 Impact analysis before touching the registry surface: GitNexus
      index absent in the worktree; mechanical call-site survey ran
      instead (`action_space.ACTIONS` consumers: `priority_ratio` +
      `planning_actions` (the settleable gate — the new entries are
      non-settleable, still refused) + two test modules; the `ActionSpec`
      change is additive — new defaulted field + keyword). Rank
      byte-equivalence pin re-run green. Risk LOW; recorded in design.md.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 tests/test_intelligent_scheduling_685.py — the four named RED
      contracts: sleep/wake action logged with propensity + source; k =
      min(free_slots, f(entropy)) observable and logged; the null action
      selectable (cost 0) with the baseline on every decision; the three
      budgets tracked. Plus vocabulary, record-persistence, declared-
      precedence, refusal, and watchdog-demotion pins.
- [x] 2.2 tests/test_scheduling_selection_685.py — the pure-math suite:
      the width derivation and its edges, the Gumbel top-k without
      replacement (distinct, replay-deterministic), the exact
      Plackett-Luce propensity, and the sampler honesty pin (the draw
      varies across seeds and tracks its logged propensity — a
      deterministic sort fails it).
- [x] 2.3 RED confirmed: collection `ModuleNotFoundError: No module named
      'intelligent_scheduling'` (output captured for the PR body).

## 3. GREEN

- [x] 3.1 scripts/action_space.py — the scheduling five registered at the
      orchestration level (sleep / wake_on / probe / close_loop / none),
      `ActionSpec.scheduling` flag, count pin updated; `none` cost 0.
- [x] 3.2 scripts/scheduling_selection.py — the wake sampler's pure math:
      f_entropy / adapt_k; Gumbel top-k without replacement; the exact
      Plackett-Luce propensity of the ordered draw.
- [x] 3.3 scripts/intelligent_scheduling.py — the decision recorder:
      registry-derived vocabulary; the null block / null_propensity
      baseline; budget_face (tokens / tool_calls / verify_calls);
      read_state; decide() persisting runs/.scheduling-decision.json + one
      kind=scheduling row; the armed watchdog block; loud refusals for
      unknown declared actions and non-finite weights; CLI.
- [x] 3.4 tests/test_action_space_12.py — vocabulary expectation extended
      (the five), null-action cost exemption documented in the metadata
      test; frozen rank capture untouched.

## 4. Registrations + gates

- [x] 4.1 scripts/README.md catalog row (intelligent_scheduling.py).
- [x] 4.2 deploy_manifest --write (three-registrations face).
- [x] 4.3 Gates with real output: the 685 suites green (15/15 recorder +
      8/8 selection), the regression trio (682 / 679 / action_space_12)
      green, comment_hygiene_lint + formal_code_lint clean without
      --emit-baseline (new files carry zero markers — zero debt added),
      openspec validate green.

## 5. Review gate + ship

- [ ] 5.1 Independent review -> PASS -> review evidence minted per
      scripts/review_gate.py (per commit).
- [ ] 5.2 PR to dev with mapping table, gates output, honest limitations
      (learned priors are the next slice; tick-loop wiring is orchestrator-
      applied by design); CI green; comment on the issue.
