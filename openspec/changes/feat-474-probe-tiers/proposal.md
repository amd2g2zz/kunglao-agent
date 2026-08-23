# Probe capability tiers — presence/liveness/capability + jdwp handshake + MCP honest degradation (#474)

## Why

The toolchain probes validate that a tool **exists**, not that it **works**:

| Probe | Implementation | Actual semantics |
|---|---|---|
| decompiler-MCP | `mcp_probe.registered_names` (scripts/mcp_probe.py:143-160) | reads a JSON registry — zero handshake; `~/.claude.json` entry does not mean the bridge process can serve a decompile |
| decompiler-CLI | `GHIDRA_DEFAULT.exists()` (env_check.py) / `_file_exists(ah)` (toolchain.py `_check_decompiler`) | pure file existence |
| VM/frida | `toolchain.py _tcp_connect` | port accepts TCP ≠ the service can process this sample |
| jdwp/jdb | zero hits repo-wide | android dynamic debugging (JDWP) has NO probe at all, though `ro.debuggable=1` is already HARD-enforced |

The matrix does have real functional probes (`pefile import`, `gitnexus --version`,
`adb shell su -c id`, `adb forward` + recv, `getprop ro.debuggable`) — but the
closer to the T2/T3 dynamic layer, the more they degrade to presence checks.

The worst case is the decompiler MCP path: `_check_decompiler` returns
**PASS** for any registered `ghidra`/`ida-pro-vm` name — a fake PASS that
satisfies the HARD init gate without evidence the decompiler can run. Python
cannot reach into the MCP session (analysis tools register only after
`connect_instance` succeeds, agents/ghidra-light.md), so a registry read plus
bridge-port reachability is ALL a probe can honestly claim — which is WARN
"capability unverified", never PASS.

## What Changes

- **New `ProbeTier` enum in scripts/toolchain.py** — `PRESENCE` (file/registry,
  ~0ms), `LIVENESS` (side-effect-free network handshake, seconds), `CAPABILITY`
  (real trial run, minutes). `CheckResult` gains a `probe: ProbeTier` field
  (default `PRESENCE`, so existing callers/dataclass consumers keep working);
  JSON output carries it per item.
- **Decompiler three-state honesty (#474 acceptance 1)**:
  - CAPABILITY-PASS: only when `analyzeHeadless` actually imports a minimal
    synthetic ELF (`analyzeHeadless <proj> <name> -import <synthetic>`) —
    available ONLY under the new `caps=True` / `--capability` opt-in
    (capability runs are minutes-long, init-only per the issue contract).
  - LIVENESS-WARN: MCP name registered AND bridge port reachable, OR CLI
    binary present — detail says exactly what was verified and that
    capability is unverified. This replaces the fake PASS.
  - FAIL: nothing registered/present (unchanged semantics, incl. the
    android pure-DEX WARN nuance).
- **jdwp liveness handshake (acceptance 2)**: new android check `jdwp_debug`
  — `adb shell su -c cat /sys/kernel/debug/binder/failed_transaction_log`-free
  discovery via `adb jdwp` (pid list), `adb forward tcp:<local> jdwp:<pid>`,
  then the RAW JDWP handshake: send the 14-byte ASCII `JDWP-Handshake`,
  expect the same 14 bytes echoed (2s timeout). `jdb -attach` is NOT used
  (attach has side effects on the target). jdb enters the android matrix
  documentation (kunglao-init os_section + golden fixture) as the
  interactive fallback driver.
- **Capability tier placement (acceptance 3)**: `check(ws, type, caps=False)`
  + CLI `--capability` flag. The periodic/init-default path runs
  presence+liveness only; capability trial runs never happen unless
  explicitly requested. Init's call orchestration is NOT touched (#478
  owns it) — this is supply-side only.

## Non-goals

- #449 env=f(task_spec) demand-side selection — not here.
- MCP session probing (spawn the bridge, `connect_instance`) — impossible
  from a Python probe without an MCP client; the honest ceiling is registry
  + bridge port (WARN).
- No changes to init's check-before-scaffold orchestration (#478's land).
