## 1. Setup

- [x] 1.1 Worktree `D:/kunglao-issue-669-apkid-prescan` branch `issue-669-apkid-prescan` off origin/dev (post-#664 merge `f5665c1`)
- [x] 1.2 Baseline: 47/47 core completion-gate GREEN inherited (#664 merged)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D1-D8)
- [x] 2.3 specs/apkid-prescan/spec.md
- [x] 2.4 tasks.md
- [ ] 2.5 `openspec validate issue-669-apkid-prescan` PASS

## 3. RED tests (`tests/test_apkid_scanner.py`)

- [ ] 3.1 RED1: synthetic apkid JSON parse -> evidence/apkid.json with status:ok, summary rollup
- [ ] 3.2 RED2: apkid binary missing -> status:unavailable, exit 0
- [ ] 3.3 RED3: non-APK input (.jar / .dex) -> status:error, exit 1
- [ ] 3.4 RED4: schema shape: all top-level keys + summary keys always populated
- [ ] 3.5 RED5: toolchain FIXES + _STATIC_NEXT_ACTIONS contain apkid
- [ ] 3.6 RED6: kunglao_init.py android flow invokes scanner at Phase 0 (mocked)

## 4. Implementation

- [ ] 4.1 `scripts/apkid_scanner.py` (NEW): run(), parse_output(), write_evidence(), main() CLI
- [ ] 4.2 `scripts/toolchain.py`: FIXES + _STATIC_NEXT_ACTIONS gain apkid; CLI presence probe
- [ ] 4.3 `scripts/toolchain_install.py`: apkid install plan (pip)
- [ ] 4.4 `scripts/hypothesis_seeder.py`: read evidence/apkid.json after seeding, append candidates to pq-family competitor_groups
- [ ] 4.5 `scripts/kunglao_init.py`: android flow Phase 0 invokes scanner (after target alignment, before jadx dispatch)

## 5. Docs + fold-in

- [ ] 5.1 CHANGELOG.md v0.1.3 Round 3 append
- [ ] 5.2 `references/re-library/languages-platforms.md` android section: apkid integration note
- [ ] 5.3 openspec validate re-run PASS
- [ ] 5.4 pytest: new GREEN; no regression on completion-gate + anomaly + hypothesis suites

## 6. PR + merge

- [ ] 6.1 mint + commit (ruff + review_gate)
- [ ] 6.2 push via Git Data API + PR (Closes #669)
- [ ] 6.3 squash-merge + delete branch