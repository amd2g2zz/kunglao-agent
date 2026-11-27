## Context

On Darwin 24 x86_64, baseline commit 1686a1bb and the issue's fake ADB setup, one instrumented CLI execution took 34.545 s (pytest 41.56 s). subprocess timings included `jadx --version` 3.590 s, two `mdfind` queries 3.061 and 3.808 s, `brew list --cask` 0.350 s, `brew --prefix ghidra` 0.288 s, and fake `adb devices` 1.319 s; remaining recorded commands each took under one second. Process startup and Python filesystem walks also contribute, but were not separately timed. This run passed; the issue reports three 60 s timeouts on another baseline run. It is not evidence that mdfind alone caused them.

The old fixture sets `KUNGLAO_CLAUDE_JSON`, but `registered_names` no longer reads that global source. Without workspace MCP registration the real CLI runs the local IDA and Ghidra discovery ladder, including Spotlight, application-directory walks, and Homebrew. Other real host tool probes remain and may vary.

## Decisions

Use `.mcp.json` in the temporary workspace, the supported input, to register fixture server names. The actual CLI returns an `analyzeHeadless` supply with an explicit capability-unverified detail; registration is not proof of a working server. A fake `mdfind` marker confirms the local ladder is not invoked while real debug flag logic and fake ADB still execute. This fixture does not test decompiler availability or replace the dedicated toolchain tests.

## Risks / limits

The CLI still checks other real host tools. This reduces observed unnecessary discovery, not a proof of a hard runtime bound on arbitrary hosts. Linux and Windows are unverified. No malware sample is run.

The regression copies the real scripts into a temporary plugin root with an empty plugin manifest and limits PATH to fake ADB and a marker `mdfind`; the interpreter and ADB stub use the absolute venv Python path. This prevents a host `idat64` or plugin-carried registration from bypassing the intended test. With the former global-only fixture, the real CLI returned debug flag FAIL and created the marker (pytest exit 1, 1 failed in 10.92 s); with workspace registration it returned the unverified supply and did not create the marker (exit 0, 1 passed in 2.16 s). The copied scripts execute unchanged. The shell-based fake commands were verified on macOS; Windows execution is unverified.

## Integration contract

The caller is pytest: the existing three cases invoke `scripts/toolchain.py` in a subprocess for a temporary workspace, and the isolation regression invokes the same unchanged scripts copied to a temporary plugin root. The trigger is the Android JSON check (`--type android --json`), with an absolute Python interpreter, a fake ADB reporting a device and its `ro.debuggable` value, and a workspace `.mcp.json` declaring a fixture `ghidra` MCP registration. The CLI reads the actual workspace and produces JSON checks; that registration produces `decompiler` supply `analyzeHeadless` with capability explicitly unverified, not evidence of a running server. The actual Android check reads fake ADB output: opt-out plus `0` yields WARN, opt-out plus `1` yields PASS, and absent task specification plus `0` yields HARD FAIL and exit 1.

The reproducible fingerprint is `.venv/bin/python -m pytest -q tests/test_debug_flag_task_spec_25.py::test_debug_flag_fixture_avoids_unrelated_local_decompiler_scan`: its temporary plugin manifest is empty, PATH contains only fake binaries, and the marker records any `mdfind` invocation. The old global-only fixture causes the marker assertion to fail; workspace registration leaves it absent and reports the unverified supply while retaining the debug flag FAIL. The regression exercises the real CLI and supply selection, not a real MCP server or local decompiler. Other host probes in the original cases are not bounded by this fixture, and the subprocess still has its existing 60-second timeout.

INV-009 records the existing registration-scope and capability-evidence contract. This fixture uses the supported workspace registration instead of the deleted global input and verifies that the actual CLI reports the registered supply as unverified; it therefore exercises that contract without asserting a live server. The invariant does not cover the separate explicit endpoint reachability probe. Its independent per-PR check selects existing scope, environment-check, and toolchain tests. Those tests passed on macOS; Linux and Windows remain unverified, and the toolchain CLI test still uses host probes.
