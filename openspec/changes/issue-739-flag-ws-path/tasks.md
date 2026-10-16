# tasks — issue-739-flag-ws-path

## 1. The RED contract
- [x] tests/test_ws_flag_args_739.py: strict loud refusal (5 flag
      shapes), quiet silent fallback (sibling + cwd), arg-wins
      untouched, the RC1 repro end-to-end (heartbeat_touch --help
      writes nothing)
- [x] confirmed RED before implementing (7 failed / 1 passed)

## 2. The guard
- [x] scripts/ws_layout.py: `_is_flag`; resolve_strict loud refusal;
      resolve_quiet absent-treatment

## 3. Gates
- [x] 8/8 suite green; resolver neighbor suites 28 green; ruff clean
- [ ] review-gate mint; CI green
