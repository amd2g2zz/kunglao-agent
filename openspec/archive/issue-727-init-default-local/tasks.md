# tasks — issue #727

- [ ] 1.1 openspec four-piece (proposal/design/specs/tasks)
- [ ] 2.1 RED tests/test_init_channel_default_727.py (all-unavailable→local+WARN,
      ssh-available→no degrade, explicit-unavailable→no auto-switch,
      emit fail-open, init-report channel block, probe command shapes)
- [ ] 3.1 GREEN scripts/init_channel_default.py (probes + resolve + emit)
- [ ] 3.2 event_taxonomy: register `channel_default`
- [ ] 3.3 kunglao-init: resolve before scaffold; write_init_report(channel=...)
      at both call sites
- [ ] 4.1 targeted suites green; tests/test_init*.py no regression
- [ ] 5.1 quality gates (ledger basis: 6 known host reds)
