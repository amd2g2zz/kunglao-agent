# Tasks: issue-756 toolchain 判定 bug

- [x] C0. openspec scaffolding (proposal/design/tasks)
- [ ] C1. `_probe_native_so` → zip central directory probe
  - [ ] RED: tests/test_toolchain_bug_756.py unit matrix
    (APK tail-offset lib/*.so True; pure-DEX False; plain .so True;
    BadZipFile fail-open; garbage False no-crash)
  - [ ] GREEN: implement zipfile.namelist probe + BadZipFile/OSError fallback
  - [ ] commit `fix(#756): _probe_native_so 读 zip central directory`
- [ ] C2. has_native_so chain fixation tests
  - [ ] android workspace + APK-with-.so ⇒ decompiler FAIL/HARD (live-run repro)
  - [ ] android pure-DEX APK ⇒ decompiler WARN
  - [ ] audit note: single consumer L1641; windows/linux pass None (HARD)
  - [ ] commit `fix(#756): has_native_so 传参链固化测试`
- [ ] C3. copy equality
  - [ ] FAIL detail + FIXES["decompiler"].fix → "Ghidra OR IDA — either
        satisfies this check"; MCP path listed unchanged; "#408" retained
  - [ ] toolchain_install.py comment sync (if needed)
  - [ ] commit `fix(#756): decompiler FAIL 文案 IDA/Ghidra 平等`
- [ ] Quality gates: pytest targeted + full sweep, release_receipt --check,
      devkit/quality_gates.py, ruff check .
- [ ] Evidence `.review-gate/evidence-756-r1.md` + review_gate mint + commits
- [ ] Field validation (read-only live-run APK → True) recorded in evidence
- [ ] PR to dev + auto-merge squash
