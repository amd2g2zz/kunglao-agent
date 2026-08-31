# Tasks — assembly history (#700)

- [ ] 1. openspec four-piece (this proposal/design/spec/tasks)
- [ ] 2. RED: tests/test_assembly_history_700.py
  - [ ] 2.1 second write_init_report archives prior report (content preserved at .init-report.1.json)
  - [ ] 2.2 rotation keeps newest KEEP=5 archives, deletes oldest beyond
  - [ ] 2.3 KUNGLAO_INIT_REPORT_KEEP=2 override honored; invalid value falls back to default
  - [ ] 2.4 archive helper never raises (pathological collision swallowed; write still succeeds)
  - [ ] 2.5 install_attempt + install_failed events land in runs/logs kunglao-*.jsonl (tool + detail fields)
  - [ ] 2.6 install_declined event on no-consent headless degrade
  - [ ] 2.7 install_declined event on IDA mcp_url branch
  - [ ] 2.8 emit failure never breaks the install loop (monkeypatched raise swallowed)
- [ ] 3. GREEN: kunglao-init.py rotation helper + docstring update; toolchain_install.py guarded emit + 3 call sites; event_taxonomy +3 words
- [ ] 4. regression: tests/test_toolchain_install.py, tests/test_init_exit_codes.py, event-stream anchor suite green
- [ ] 5. gates: devkit/quality_gates.py all 7 (host ledger 6 known reds unchanged)
- [ ] 6. segments committed (docs → RED → GREEN), each mint-gated
