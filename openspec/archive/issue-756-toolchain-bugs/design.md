# Design: issue-756 toolchain 判定 bug

## D1. Root cause forensics — head 4KB vs central directory (C1)

`_probe_native_so` (scripts/toolchain.py:738) read `p.read_bytes()[:4096]`
and returned True on a `lib/` or `.so` byte hit. APK layout violates that
assumption:

- local file headers sit at per-entry offsets that grow with payload size;
- the central directory lives at the file TAIL.

Field sample (read-only):
`/Users/dev/Downloads/live-run/analysis_workspace/bins/<sample-sha256>`

```
sha256        = <sample-sha256>
size          = 414804023 bytes
head[0:4096]  contains b'lib/' -> False ; contains b'.so' -> False
namelist()    = 41203 entries ; lib/**/*.so entries = 206
              e.g. lib/arm64-v8a/libAGFX.so, lib/arm64-v8a/libBaiduMapSDK_base_v7_6_7.so
```

=> legacy probe False on a fully-native sample → android decompiler gate ran
WARN-shaped where HARD semantics were owed.

## D2. New probe algorithm (C1)

Ordered, per file in sorted(bins/) over regular files:

1. name ends with `.so` → True (unchanged).
2. file looks zip-ish / any file: try
   `[n for n in zipfile.ZipFile(p).namelist()]` once; True if any entry has
   POSIX dir prefix `lib/` and suffix `.so`. (APK/JAR/APEX are zips; plain
   .so step 1 already covered non-zip native objects.)
3. `zipfile.BadZipFile` (and OSError) → FAIL OPEN to the legacy head-4KB scan
   (`lib/` or `.so` substring), preserving pre-#756 behavior for truncated /
   encrypted / misnamed blobs; never raise.

Performance: one namelist() call reads only the central directory records
(tail of file) — O(entries) metadata bytes, not the 400MB payload.

Fixtures must place the `lib/**.so` local header BEYOND byte 4096 (leading
stored `classes.dex` ≥ 8KB) so the test suite genuinely reproduces the
tail-offset condition instead of accidentally passing via a head-window hit.

## D3. has_native_so chain audit (C2)

Repo-wide grep (`_probe_native_so|probe_native|has_native_so`): exactly one
consumer — `_check_android` L1641:
`_check_decompiler(report, ws, has_native_so=_probe_native_so(ws), caps=caps)`.
`_check_windows` / `_check_linux` call `_check_decompiler(ws, caps=caps)`
(has_native_so=None ⇒ unconditional HARD, per docstring). No other modules,
tests, or fixtures depend on the probe. Fixation tests pin both android arms:
APK-with-.so ⇒ decompiler FAIL/HARD; pure-DEX APK ⇒ WARN/HARD.

## D4. Copy equality (C3)

Peers wording, MCP path preserved, `#408` anchor retained (pinned by
test_init_toolchain_gate.py::assert "#408" and test_mcp_supply.py::
assert "#408" in fix):

- FAIL detail (native): "Sample has native .so — decompiler REQUIRED for
  native code (install Ghidra OR IDA — either satisfies this check)".
- FAIL detail (no signal): "(install Ghidra OR IDA — either satisfies this
  check; or register a ghidra/ida-pro-vm MCP — see the #408 installer)".
- FIXES["decompiler"].fix: "install Ghidra OR IDA — either satisfies this
  check (#408 installer: set GHIDRA_HOME=<Ghidra install root> with
  support/analyzeHeadless(.bat), OR put idat64 on PATH); or register the
  ghidra/ida-pro-vm MCP via `claude mcp add`".
- scripts/toolchain_install.py: header comment "the Ghidra path (auto)"
  already documents the IDA mcp_url path — no functional copy change found;
  INSTALL_PLANS stay as-is (an auto Ghidra install satisfies the check).

## D5. Verification gates

New suite tests/test_toolchain_bug_756.py (unit probe matrix + subprocess
android integration) plus existing gates: test_toolchain.py,
test_apk_mem_gate.py, full-suite run (host-tool sanitized PATH),
release_receipt --check, quality_gates, ruff.
