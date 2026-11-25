# Tasks — issue 1005, C1 s2

## 1. Premise checks (before writing code)

- [x] Re-verify item ④'s premise instead of inheriting it: `grep -rn
      cockpit-ratio` over `scripts/ hooks/ devkit/ tools/` → one reader,
      `scripts/heartbeat_tick.py:761`; `git diff --name-status dc7676ff
      feat/1001-monitor-removal-l11` → that branch deletes the file;
      #1086 (2026-11-25) makes `heartbeat_tick --wake-gate` the registered
      cron command and says "This card does not delete it"; `git grep
      wake-gate` over the L11 tree → no hits. Conclusion: the premise is
      stale, no new runtime reader is built (design.md D4).
- [x] Verify the organs the report reads actually exist on real samples:
      facts organ (`facts/_INDEX.md` present with zero rows while `facts/`
      holds no other file in a real workspace; frontmatter path needed
      elsewhere), dispatch organ (a real workspace has no
      `runs/mission_ledger.yaml` while its session has a worker transcript),
      intervention organ (`bench_tokens.collect` user-turn rule).
- [x] Verify the transcript window: the workspace name stamp is local time
      labelled `Z` (`eval_loop_runner.py:1175,1281`), measured against a real
      session's last-row timestamp — so it cannot bound the search
      (design.md D5).
- [x] Record RED: `tests/test_capability_report_1005.py` against the base tree
      (no `scripts/capability_report.py`) → collection error, and the faces
      that depend on ①②' gauges fail on the base modules; counts and the
      command are in the s2 handoff (evidence kept outside the repository).

## 2. The gauge

- [x] `scripts/capability_report.py`: six sample faces plus the cockpit ratio
      face, each naming its organ, with `None` + reason where an organ is
      absent.
- [x] Accuracy through `eval_control_arm`'s predicates and rate functions;
      claimed closure from the checker's bit; falsification legs behind
      `--regrade` only.
- [x] Batch `aggregate` over the same functions, so a campaign readout and a
      per-sample face cannot drift.
- [x] CLI: `--results` / `--workspace`, `--task`, `--tier`, `--regrade`,
      `--out`; one report per sample plus `summary.json`; exit 2 on refusal.
- [x] No corpus content in any face (ground truth is named, never copied).

## 3. Pins

- [x] Facts: index organ, frontmatter fallback, index excluded from the file
      count, stale-index delta, missing directory.
- [x] Accuracy: PASS with evidence, SKIP/REFUSED not answers, absent verdict
      not a FAIL, unregraded never accused, checker-bit provenance, regrade
      without a candidate.
- [x] Ground truth: present unit, unknown unit, unit without a file, no task
      id, no leak of a ground-truth constant.
- [x] Tokens: orchestrator/worker split, harvested face preferred over a
      re-fold, absent transcript, never priced from tokens, pre-provenance row
      labelled.
- [x] Wall / dispatch / human / cockpit organs and their absent paths.
- [x] `aggregate` equals `eval_control_arm.arm_metrics` on the same rows.
- [x] CLI: reports + summary written, three refusal paths.

## 4. Real-data evidence (read-only)

- [x] Every local eval-results document replayed through the gauge: 29
      documents, exit 0 on every one that names a workspace, no traceback.
- [x] A killed session whose transcript survives reports its token split
      (real sample `ws-tf-snake-trainer-v1-20261028T131042Z-68731`:
      orchestrator output 148,443 / worker output 41,484 / wall 5399.899 s /
      dispatch 9 / user turns 2 / verdict REFUSED).
- [x] A passing release-tier sample reports accuracy from the corpus unit that
      exists (`win-kdf-l1`: PASS, proven-with-evidence, dispatch 12).
- [x] Historical rows whose corpus units were pruned report
      `unit not resolvable` instead of inventing a grade.

## 5. Registration (last, separate commit)

- [x] `scripts/README.md` catalogue row for the new gauge.
- [x] `tests/_tiers.py` FAST_MODULES entry (the suite is in-process; it writes
      only under `tmp_path`).
- [x] `deploy_manifest.py --write` then `--verify` (manifest LAST).
- [x] `openspec validate issue-1005-capability-report --strict`.
