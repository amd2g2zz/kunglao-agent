## 1. Setup

- [x] 1.1 Worktree `D:/kunglao-issue-670-mem-gated-jadx` branch `issue-670-mem-gated-jadx` off origin/dev (post-#669 merge `b9d6a4c`)
- [x] 1.2 Baseline: 79/79 inherited GREEN (#662/#663/#664/#669)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D1-D10)
- [x] 2.3 specs/mem-gated-jadx/spec.md
- [x] 2.4 tasks.md
- [ ] 2.5 `openspec validate issue-670-mem-gated-jadx` PASS

## 3. RED tests

apk_mem_gate (8 RED):
- [ ] 3.1 RED1 small APK -> jadx-ok
- [ ] 3.2 RED2 large APK -> smali-only
- [ ] 3.3 RED3 medium APK -> targeted-jadx
- [ ] 3.4 RED4 JAR -> refuse
- [ ] 3.5 RED5 dex_bytes_total = sum of dex sizes
- [ ] 3.6 RED6 avail_gb fallback
- [ ] 3.7 RED7 calibration_basis always populated
- [ ] 3.8 RED8 evidence JSON written even on REFUSE

baksmali_index (4 RED):
- [ ] 3.9 RED1 baksmali missing -> noop + warning
- [ ] 3.10 RED2 schema shape
- [ ] 3.11 RED3 gitnexus-shape compat
- [ ] 3.12 RED4 per-class xref fail-open

## 4. Implementation

- [ ] 4.1 `tools/static/apk_mem_gate.py` (NEW)
- [ ] 4.2 `tools/static/baksmali_index.py` (NEW)
- [ ] 4.3 `scripts/toolchain.py`: FIXES + _STATIC_NEXT_ACTIONS gain baksmali (URL embedded)
- [ ] 4.4 `scripts/convergence_check.py`: Event enum gains JADX_INFEASIBLE (intake-level)
- [ ] 4.5 `scripts/route_capability.py`: add apk_mem_gate-aware dispatch selection
- [ ] 4.6 `scripts/kunglao_init.py`: android flow Phase 0 calls apk_mem_gate

## 5. Docs + fold-in

- [ ] 5.1 CHANGELOG.md v0.1.3 Round 3 append
- [ ] 5.2 `references/re-library/languages-platforms.md` android section
- [ ] 5.3 openspec validate re-run PASS
- [ ] 5.4 pytest: no regression on prior suites

## 6. PR + merge

- [ ] 6.1 mint + commit
- [ ] 6.2 push via Git Data API + PR (Closes #670)
- [ ] 6.3 squash-merge + delete branch