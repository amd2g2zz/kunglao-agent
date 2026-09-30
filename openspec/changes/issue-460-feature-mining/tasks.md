# tasks — issue-460-feature-mining (Part A)

## 1. Gate 1 — spec first

- [x] 1.1 openspec change `issue-460-feature-mining` (proposal, design,
      tasks, specs/feature-mining/spec.md);
      `openspec validate issue-460-feature-mining --strict` green.
- [x] 1.2 Adversarial design-review subagent (architect) against
      existing openspec/specs + the card + live data: verdict FAIL
      (3H/7M/7L) — all defects folded into design.md/spec.md
      (pairing FIFO-per-claim, rc-null→unknown, coverage-cliff
      disclosure, declared_value reuse, mounted-block precedence,
      probe/packer shapes enumerated, root in sort key, registered
      token in scenario, decode-tolerance, L-fixes) BEFORE any test
      or code; re-validated --strict green.

## 2. RED (TDD — tests from the spec scenarios)

- [x] 2.1 tests/test_feature_mining_460.py — fixture extraction
      correctness: the 3 pinned runs produce the pinned golden rows
      (row identity fields, features keys, outcome tuples).
- [x] 2.2 malformed-source tolerance: corrupt/undecodable run-state
      run is skipped with warn and does not abort; dangling ws
      pointer degrades to nulls + empty outcomes; unparseable claim
      register → attribution falls to null; non-object evidence docs
      degrade (never crash).
- [x] 2.3 schema validation: every emitted row validates
      feature-table/1 (schema literal, 12-hex signature_hash, typed
      feature keys incl. enumerated probe/packer shapes, outcome
      vocabulary closed set); junk rows rejected field-precisely.
- [x] 2.4 determinism pin: two mines of the same fixture root are
      byte-identical AND equal the committed golden sha256; root
      order does not change bytes; (family, task_id, run_id, root)
      sort pinned.
- [x] 2.5 outcome attribution: timeout vs landed vs blocked vs
      rc-null-unknown vs unpaired-attempt-unknown; envelope
      registered token (static-decompile) beats register source;
      ledger settlement on a DISPATCHED claim → settled/credit;
      same-task runs share signature_hash, evidence-differing runs
      do not.

## 3. GREEN

- [x] 3.1 scripts/feature_mining.py — the miner (Decisions 1-4):
      run-state anchor, relative-pointer resolution, FIFO pairing,
      declared_value + settled() + difficulty_calibration reuse,
      canonical hash, mounted-block precedence, sorted jsonl emit,
      summary line.
- [x] 3.2 tests/fixtures/feature-mining-460/ — sanitized 3-run
      fixture root (landed+settled mix / timeout-loop with
      die+apkid evidence / degraded dangling-ws) + golden
      feature-table.jsonl (mined by the script, pinned).

## 4. Registrations + gates

- [x] 4.1 scripts/README.md catalog row (test_declaration_scan pin).
- [x] 4.2 tools/ext-scan.py re-scan → tools/_INDEX.ext.yaml.
- [x] 4.3 scripts/deploy_manifest.py --write (AFTER ext-scan).
- [x] 4.4 Gates with real output: new suite (32) + touched suites
      (declaration-scan / ext-index / deploy-lifecycle / doc-sync —
      141), ruff clean on changed files, devkit/quality_gates.py
      --quick ALL-PASS, comment_hygiene_lint clean (863 files) with
      the paired re-mint (--emit → deploy_manifest --write → mint →
      commit order held).

## 5. Review gate + ship

- [x] 5.1 Independent code-reviewer subagent → FAIL round (1 HIGH:
      kunglao_log ledger-face write into input roots; 2 MEDIUM: kind
      scoping, malformed-field crashes; 2 LOW) → all fixed + tests →
      PASS → PASS re-confirmed on the strengthened-test sha → evidence
      .claude/reviews/460a-feature-mining.md → review_gate.py mint.
- [ ] 5.2 PR to dev with Requirement → impl → test mapping table,
      gates output, Part-B-out disclosure; CI five legs green; merge;
      do NOT close #460.
