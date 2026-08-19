# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace type

Kunglao-agent malware RE workspace — not a software project. The "code" is state files, facts, and worker runs analyzing a malware sample.

## Sample under analysis

| Field | Value |
|-------|-------|
| SHA1 (filename) | `sample.exe` |
| SHA256 | `a200cb881c3739ce4c6d854e189c608b6f8a41e364769b96bafda8d5a1a9d229` |
| Type | `(detected at analysis time)` |
| Path | `bins/sample.exe` |

## Skill & orchestrator

Analysis is driven by `/kunglao-agent` (skill at `/kunglao/skill-sentinel`).

**Key scripts** (invoke from workspace root with `.venv` activated):
```bash
source .venv/Scripts/activate
python /kunglao/skill-sentinel/scripts/convergence_check.py .
python /kunglao/skill-sentinel/scripts/priority.py .
python /kunglao/skill-sentinel/scripts/convergence_health.py .
python /kunglao/skill-sentinel/scripts/failure_analysis_gate.py . <C-NN>
```

**Hook activation** (30-min TTL, renew via `/loop`):
```bash
python /kunglao/skill-sentinel/scripts/hook_activation.py . --renew
```

**Environment readiness**: `python /kunglao/skill-sentinel/scripts/env_check.py .` (PASS/FAIL per check; exit 0 = all pass).

## State files (read every turn, disk is truth)

| File | Purpose |
|------|---------|
| `claim-register.yaml` | All claims + status (OPEN/PARTIALLY-VERIFIED/PROVEN/DEFERRED) |
| `claim_deps.yaml` | Claim dependency graph |
| `task_spec.yaml` | Analysis contract (depth, scope, constraints, success criteria) |
| `analysis_state.txt` | Cognition baseline (venv, sample hash, toolchain, worker list) |
| `global_plan.txt` | High-level analysis plan |
| `facts/_INDEX.md` | Fact index with PARTIAL/PROVEN markers |
| `blockers/` | Active blocker files |
| `runs/` | Worker status files + `.heartbeat.json` |

**Facts** go in `facts/F<NNN>.md` with byte-anchored, reproducible evidence.

## Five-layer analysis principle

1. **Static-first closed loop** — Complete the full static analysis before introducing dynamic tools. If static analysis can fully answer the claim, stop there. Never introduce dynamic tools for a claim that static analysis can close.
2. **Deobfuscation for efficiency** — Use symbolic execution / emulation to strip obfuscation layers (opaque predicates, indirect jump resolution, constant concretization, decoding-layer restoration). Feed products back to static analysis. Deobfuscation counts as a static-support action, not a layer skip; declare any gap it leaves.
3. **Debug to fill gaps** — Only use debugging when static analysis (including post-deobfuscation) remains incomplete. Dispatch must carry a "static gap list" explaining what static could not resolve.
4. **Simulation as fallback** — When static + debug data still cannot resolve, use unidbg hybrid (frida live args feed simulation, per-function verification). AND gate: frida data sufficient + ida/ghidra decompilation done + still stuck.
5. **Last resort: environment repair** — When layers 1-4 all fail: build/repair the environment (version matching, APK repackaging+signing, emulator/sandbox setup, JNI environment completion). Goal = full-flow observability.

## Hard constraints (common)

- **Dynamic tools VM-only**: x64dbg, Frida, sample execution must run on VM. Never launch/debug/inject on host.
- **Orchestrator does not analyze**: the orchestrator monitors/dispatches/verifies only. Decompile, strings, grep, emulation, debugging go to workers.
- **Maker-checker**: worker=maker, orchestrator=checker. Facts must be independently verified before promotion to PROVEN.
- **No stopping for self-answerable questions**: within the analysis loop, do not halt for questions you can answer yourself — attempt self-repair for environment failures and record the decision for decidable items. Schema ambiguity and directional choices (which change what the user asked for) must still be surfaced to the user.

## Hard constraints (android)

- **ADB required (root dependency)**: `adb devices` must show at least one device. ADB missing means frida-server/android_server discovery impossible; all downstream dynamic checks cascade from ADB.
- **Device root required**: `adb shell su -c id` must return uid=0. Non-rooted devices cannot run frida-server or perform dynamic analysis. This is a HARD gate.
- **Debug flag (HARD, init-enforced)**: manifest debuggable or `am set-debug-app` / setprop. Must be set and read back for verification — kunglao-init's toolchain check verifies `adb shell getprop ro.debuggable` returns 1; if not settable, init refuses (exit 4) with fix guidance.
- **frida-server (HARD, init-enforced; renamed + custom port)**: Device-side binary must NOT use the default name; custom port (default convention: 1337). kunglao-init verifies it via `adb forward tcp:<port>` + TCP connect; unreachable means init refuses with deployment guidance.
- **GitNexus required**: `gitnexus --version` must succeed. Post-decompile graph building is a mandatory step in the Android flow.
- **IDA android_server (HARD, init-enforced)**: Must be present on device for IDA remote debugging. kunglao-init verifies it via `adb forward tcp:23946` + TCP connect; unreachable means init refuses with deployment guidance.
- **JDWP debugging (WARN, informational; #474 follow-up 2026-08-19)**: NOT a hard requirement — static-only and frida-driven flows never touch jdb. kunglao-init reports JDWP agent reachability via the raw 14-byte `JDWP-Handshake` echo (`adb forward tcp:8700 jdwp:<pid>` then handshake — side-effect-free, never `jdb -attach`). A miss is surfaced to the orchestrator as a capability-absence signal; whether to repair it (start the debuggable app / `am set-debug-app`) is the orchestrator's per-task decision, not an init gate. jdb remains the interactive driver for the analyst (`jdb -connect com.sun.jdi.SocketAttach:...`).
- **eBPF tracing (WARN)**: Requires Android SDK >= 31 (getprop ro.build.version.sdk). SDK < 31 means eBPF unavailable (not blocking).
- **unidbg (WARN, fallback)**: Requires java + unidbg library. Only used when static+debug+frida all fail. AND-gated: frida data sufficient + decompilation done + still stuck.

## Android analysis flow

```
APK -> aapt/apktool unpack -> jadx DEX->Java
    -> gitnexus analyze(decompiled output dir, build knowledge graph; serve/graph data as analysis artifact)
    -> static analysis(graph-assisted class/call-chain/malicious-logic-entry location)
    -> dynamic needed: ADB -> root -> debug flag -> frida(renamed+port) or android_server
    -> stuck fallback: frida hook + unidbg hybrid (AND three conditions)
```


## Success criteria

Key behaviors are verifiable, not aspirational. Each check names where the proof lives:

- A fact may only be promoted to PROVEN with an independent verifier sign-off record — provable via `facts/_INDEX.md` (verifier column) and the fact file's verify section.
- Every numeric fact declares its counting unit; multi-basis numbers are never collapsed — provable by reading any `facts/F*.md` numeric claim.
- Every claim in `claim-register.yaml` has a status and evidence tier — provable by `python /kunglao/skill-sentinel/scripts/lint_facts.py <ws>` returning zero errors.
- Environment failures are self-repaired before analysis dispatch — provable via `runs/.env-check.json` showing overall PASS (or a blocker file explaining why not).
- Tool selection goes through `tools/_INDEX.yaml` (capability + description) before writing a new script — provable by the `tool-catalog:` marker in worker dispatch records.

## MCP servers (supply manifest — #316)

Analysis correctness depends on registered MCP servers — a fresh machine deployed per kunglao docs must register these (user-level `claude mcp add ...`, or fill real entries in the workspace `.mcp.json` scaffold). Mechanical check: `python /kunglao/skill-sentinel/scripts/mcp_probe.py . --type android` (exit 1 = HARD missing).

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | all types | Ghidra decompile/static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 | dynamic debugging (VM remote) | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | memory forensics | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | when IDA chosen | IDA remote analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android graph flow | post-decompile knowledge graph | `claude mcp add gitnexus -- gitnexus mcp` |
| `virustotal` | WARN | CTI | intelligence (family attribution) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |

Workspace `.mcp.json` scaffold is generated by `kunglao-init` when missing (`--no-mcp` skips; an existing file is never overwritten). Keep this table in sync with the single manifest source `scripts/mcp_probe.py` (pinned by `tests/test_mcp_supply.py`).

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `0` (default disabled) | Agent-team dispatch channel. MUST stay `0`/unset — truthy values (1/true/yes/on) route subagent dispatches through the teammate channel (2026-08-12 incident). `kunglao-init` sets it to `0` in the session and in your PowerShell profile(s); `scripts/shell_defaults.py` manages profile default lines. |
| `KUNGLAO_VM_HOST` | unset | VM lease host for dynamic analysis (vmr-shell / Frida ports). Unset = dynamic analysis (T3) blocked; static analysis may proceed. |
| `KUNGLAO_VM_SHELL_PORT` | `9876` | vmr-shell TCP port on the VM. |
| `KUNGLAO_FRIDA_PORT` | `1337` | Custom Frida port (renamed frida-server convention). |
| `GHIDRA_HOME` | unset | Ghidra install root; `support/analyzeHeadless.bat` must exist under it for decompilation. |
| `KUNGLAO_DIE` | unset | Path to the DIE (Detect It Easy) executable; fallback to PATH. |
| `KUNGLAO_CLAUDE_JSON` | unset | Override for the user-level `~/.claude.json` MCP registry (tests). |

Deployment variables live in the workspace `.env` (see `.env.example` for the annotated list; `scripts/env_check.py` reads it — real environment wins, `.env` is the fallback).

## Tool script discipline

Any reusable analysis logic must land as a parameterized CLI script under `/kunglao/skill-sentinel/scripts/` (no hardcoded paths, reusable across workspaces). ad-hoc inline execution (`python -c` / heredoc) is forbidden; prefer reusing an existing CLI (e.g. `scripts/shell_defaults.py` for shell environment default lines, `scripts/env_check.py` for environment readiness). One-off commands may run via Bash, but any logic you might reuse must first become a script.

## Python venv

Path: `.venv/`. Key deps: `cryptography`, `pyyaml`. Activate before running scripts. Python 3.11.0.
