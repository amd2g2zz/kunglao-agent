# Proposal: fix toolchain native-lib detection — _probe_native_so central directory, has_native_so chain fixation, IDA/Ghidra-equal decompiler copy

## Why

Issue #756. Field evidence (live-run sample APK,
`<sample-sha256>`,
414804023 bytes, 206 `lib/**/*.so` entries): `_probe_native_so` scans only
the first 4KB of each `bins/` file for `lib/` / `.so`. An APK's local file
headers sit at scattered offsets and its central directory sits at the file
TAIL — for this sample the head 4KB contains neither byte string, so the
android decompiler check ran with `has_native_so=False` and degraded a HARD
requirement to a WARN on a fully native sample.

Secondary: the FAIL copy (`detail`, `FIXES["decompiler"].fix`) leads with
Ghidra-specific instructions, reading as "ghidra is mandatory" even though
the check itself accepts Ghidra OR IDA OR an MCP registration.

## What Changes

1. **C1** `_probe_native_so`: zip-shaped files are probed via the central
   directory (`zipfile.ZipFile(p).namelist()` → any name with prefix `lib/`
   and suffix `.so`). Non-zip files keep the existing `.so`-suffix rule;
   corrupt zips fail open to the legacy head-4KB scan (never raise).
2. **C2** chain fixation: the only `has_native_so` consumer is
   `_check_android` (toolchain.py L1641); windows/linux pass `None`
   (unconditional HARD). Tests pin: APK-with-.so → FAIL/HARD semantics;
   pure-DEX APK → WARN.
3. **C3** copy equality: decompiler FAIL detail and
   `FIXES["decompiler"].fix` present Ghidra and IDA as peers
   ("install Ghidra OR IDA — either satisfies this check"), MCP path listed
   unchanged; `#408` installer reference retained (pinned by
   tests/test_init_toolchain_gate.py + tests/test_mcp_supply.py).
   `scripts/toolchain_install.py` comments synced if exclusive-sounding copy
   is found; functional INSTALL_PLANS unchanged (auto-installing Ghidra
   remains one valid satisfaction path).

## Impact

- `scripts/toolchain.py` (_probe_native_so, _check_decompiler details, FIXES)
- `tests/test_toolchain_bug_756.py` (new acceptance suite)
- read-only field validation against the live-run sample above
