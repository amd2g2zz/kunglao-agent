# Tasks — Agent 行为三态宪法 (issue #447)

## Phase 1 (this PR)

- [x] 1.1 Write `docs/agent_3state_charter.md` (single source)
- [x] 1.2 `scripts/ask_for_direction_gate.py`: TYPE_D/TYPE_S patterns (English-only) + find_must_ask/stop_signals + check() priority S > D > C > A/B
- [x] 1.3 Remove Chinese patterns from TYPE_A/TYPE_B (English-only policy)
- [x] 1.4 `rules/kunglao-convergence-loop.md` hard prohibition #1 → charter reference
- [x] 1.5 `scripts/kunglao-init.py` comment references charter (Type D at intake)
- [x] 1.6 `hooks/dispatch_gate.py` must-stop hook (before claim-health check)
- [x] 1.7 `tests/test_ask_for_direction_charter.py` (18 tests)
- [x] 1.8 `tests/test_dispatch_protocol.py` + TestDispatchMustStop (3 tests)
- [x] 1.9 openspec/{proposal,design,spec,tasks}.md
- [ ] 1.10 Commit + push + open PR

## Future (out of scope)

- [ ] v1 dispatch protocol `reversible: false` field (declared vs inferred must-stop)
- [ ] workspace-level identity-ambiguity check at dispatch time (count VMs)
- [ ] CI simulation: ask_for_direction_gate over canned orchestrator outputs
