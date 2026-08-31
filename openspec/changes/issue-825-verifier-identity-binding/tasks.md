# Tasks — #825

- [ ] 1. `dispatch_gate.py`: append `{ts, agent_type, claim_id, task_id}` to `runs/dispatch-ledger.jsonl` on every Agent dispatch (hook-owned file)
- [ ] 2. `write_gate.py::_fact_runs_records`: require ledger entry (agent_type=kunglao-redteam, claim_id match, ts > fact mtime) for the redteam-md path; drop the `overall=="VERIFIED"` acceptance entirely
- [ ] 3. `lint_facts.py`: promote register↔facts verify_status drift from WARN to ERROR when no ledger entry backs `passes`
- [ ] 4. `plan_drift_detector.py::extract_verified_claim_ids` (child #826): consume the ledger instead of the glob
- [ ] 5. Tests: (a) self-authored redteam md without ledger → R1 reject; (b) L1-only json → R1 reject; (c) real redteam dispatch → pass; (d) backdated ledger line (ts < fact mtime) → reject
- [ ] 6. Regression fixture: replay the incident workspace shape (8 template files, 265ms span, no ledger) — all 15 claims must fail R1
