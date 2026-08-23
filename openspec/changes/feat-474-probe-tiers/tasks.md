# Tasks — probe capability tiers (#474)

## 1. OpenSpec (SDD)

- [x] 1.1 proposal.md (evidence table + three-tier classification + MCP honesty ceiling)
- [x] 1.2 spec.md (REQ: three-state decompiler / jdwp handshake / capability opt-in)
- [x] 1.3 `openspec validate feat-474-probe-tiers` PASS

## 2. RED tests (write first, must fail)

- [x] 2.1 `tests/test_probe_tiers_474.py`:
  - MCP registered-only (registry has ghidra + bridge port reachable, no capability evidence) → decompiler WARN, detail "capability unverified", probe tier LIVENESS — never PASS
  - capability trial (fake analyzeHeadless that exits 0 on -import) under caps=True → PASS with CAPABILITY tier
  - jdwp fake server echoing 14 bytes → PASS; server echoing wrong bytes → FAIL; timeout → FAIL
  - `check(ws, t)` default never invokes the capability probe (seam call-count = 0); `--capability` CLI flag reaches it
  - JSON output carries `probe` per item
- [x] 2.2 Confirm RED recorded (assertion failures on old code)
- [x] 2.3 commit `test: RED probe tiers (#474)`

## 3. GREEN

- [x] 3.1 `ProbeTier` enum + `CheckResult.probe` field (default PRESENCE)
- [x] 3.2 `_check_decompiler` three-state: caps opt-in PASS / liveness WARN / FAIL (android pure-DEX nuance kept)
- [x] 3.3 `_jdwp_handshake` (14-byte echo) + `_adb_jdwp_probe` (adb jdwp → forward → handshake) + `jdwp_debug` android check
- [x] 3.4 `check(caps=...)` param + CLI `--capability`; CHECK_SETS android += jdwp_debug
- [x] 3.5 classify existing probes (pefile/gitnexus/su-id/getprop = CAPABILITY; forward-probes/vm/tcp = LIVENESS; which/file-exists = PRESENCE)
- [x] 3.6 migrate affected legacy assertions (fake-PASS decompiler tests → WARN)
- [x] 3.7 android matrix doc: jdb/jdwp line in kunglao-init os_section + golden fixture regen
- [x] 3.8 CHANGELOG Unreleased entry

## 4. Gate

- [x] 4.1 `uv run python -m pytest -q -m "not load_sensitive"` green
- [x] 4.2 `uv run python scripts/release_receipt.py --check` green
- [ ] 4.3 commit + push + PR (base dev, Closes #474)
