# tasks — issue-460-intake-battery

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-460-intake-battery` (proposal,
      design, tasks, specs/intake-battery/spec.md);
      `openspec validate issue-460-intake-battery --strict` green.
- [x] 1.2 Adversarial design review against the exact contracts
      (die_probe CLI, apkid_scanner library face, intake_promise
      chain, feature_mining extraction, init wiring). Process
      deviation disclosed: no subagent-dispatch tool exists in the
      session (same disclosure as the merged Part B change); the
      review ran as a dedicated in-session adversarial pass
      (design.md "Design review"). Verdict FAIL → folded BEFORE any
      test or code: F1 usable-evidence requirement (MEDIUM), F2 no
      third unmined probe (MEDIUM), F3 applicability lives in the
      probes (LOW), F4 die via CLI subprocess (LOW); L-notes
      recorded. Re-validated --strict green after folding.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 tests/test_intake_battery_460.py — battery produces both
      evidence files + ledger facts (fake probe CLIs); probe-absent
      (CLIs missing) → rows absent, no usable evidence, battery
      never raises; no-sample lane-aware no-op; die-only-writes-on-
      produced; ledger schema.
- [x] 2.2 intake_promise usable-evidence pins: unavailable/error
      artifacts → prescan state missing (RED against parseable);
      Part B evidence-presence pin updated (fixture gains status ok).
- [x] 2.3 init-level: probe-absent workspace passes the init battery
      block with absence recorded (the wiring never blocks init).
- [x] 2.4 minability: battery-produced evidence in the
      feature-mining fixture root → the golden table row gains
      die/apkid values (usable/packers/entropy) with zero miner
      changes; determinism pins re-run.

## 3. GREEN

- [x] 3.1 scripts/intake_battery.py — the battery face (die CLI +
      apkid library, ledger writer, CLI re-run face), never raises.
- [x] 3.2 scripts/intake_promise.py — `_probe_evidence_present`
      usable-evidence fold (usability rules reused from
      difficulty_calibration).
- [x] 3.3 scripts/kunglao-init.py — battery block before the #813
      promise block (WARN-tier wiring, env_incident on defect).
- [x] 3.4 fixture extension: e2e-ws-a battery-produced evidence +
      regenerated golden table.

## 4. Registrations + gates

- [x] 4.1 scripts/README.md catalog row for intake_battery.py.
- [x] 4.2 tools/_INDEX.ext.yaml entry + deploy_manifest --write
      --verify (the three-registrations face).
- [ ] 4.3 Gates with real output: new suite + intake-promise +
      feature-mining + init batches, ruff clean on changed files,
      devkit/quality_gates.py --quick ALL-PASS.

## 5. Review gate + ship

- [ ] 5.1 Independent review (in-session adversarial pass over the
      staged diff — process deviation disclosed) → PASS → review
      evidence minted per scripts/review_gate.py (paired re-mints if
      review comments change the diff).
- [ ] 5.2 PR to dev ("feat: #460 intake probe battery — features
      exist from run #1 (instrument)") with openspec mapping table,
      gates output, honest limitations; CI five legs green (GnuTLS
      flake → rerun --failed; never merge red); merge. Comment on
      #460 (battery landed; flag activation awaits EX-5 re-evaluation
      on battery-fed data). Do NOT close #460.
