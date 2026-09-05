# kunglao-agent

**A Claude Code skill that runs a convergence-driven reverse-engineering loop — plans its own path, derives every fact from raw evidence, and converges under mechanical verification gates.**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](.) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](.) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](.) [English](README.md) · [简体中文](README.zh-CN.md)

Drop a target into a workspace, say what you need to know, and the skill drives the loop: specialist workers analyse (static first), an independent verifier re-derives every fact blind from raw evidence, and mechanical gates decide when the analysis is done. The deliverable is a fact base where every claim is byte-anchored, independently verified, and evidence-indexed — trust is enforced by machinery, not convention.

---

## Contents

- [What this is](#what-this-is)
- [Quick start](#quick-start)
- [A worked analysis case](#a-worked-analysis-case)
- [Scenario walkthroughs](#scenario-walkthroughs)
- [What you get](#what-you-get)
- [How the loop works](#how-the-loop-works)
- [Analysis principle](#analysis-principle)
- [Toolchain by target type](#toolchain-by-target-type)
- [Configuration](#configuration)
- [Bring your own analysis environment](#bring-your-own-analysis-environment)
- [Internals](#internals)
- [Real-world results](#real-world-results)
- [Development](#development)
- [Limitations](#limitations)
- [Safety](#safety)
- [License](#license)

---

## What this is

kunglao-agent is a Claude Code skill that behaves like a reverse-engineering expert across the full task spectrum — firmware emulation, risk-control countermeasures, web/JS reversing, protocol analysis, native-binary triage — not a single-domain tool. The Python modules in this repo are the skill's internal organs, called by hooks, agents, and CI. The only user interface is Claude Code itself: you talk to it and read its reports.

### Prerequisites (always required)

| Tool | Why | Install |
|---|---|---|
| **Claude Code** | the only UI | per Anthropic docs |
| **Python 3.10+** | plugin carries a pinned env via `uv`; you do not touch it | system or `uv`-managed |
| **`uv`** | locked env resolver | `pip install uv` or [astral.sh/uv](https://astral.sh/uv) |
| **Ghidra or IDA** | one static-analysis suite for decompilation | see [Internals](#internals) |

Additional tools depend on the target type — see [Toolchain by target type](#toolchain-by-target-type).

---

## Quick start

The shortest path from a sample on disk to a verdict.

### 1. Install the plugin

From any directory, in Claude Code:

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

(Alternative: `claude --plugin-dir /path/to/kunglao-agent` for development; legacy `git clone ~/.claude/skills/kunglao-agent` still works.)

### 2. Init a workspace

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` scaffolds the workspace, writes `CLAUDE.md`, probes the toolchain for your chosen `--type`, and scaffolds `.mcp.json`. **Init HARD-rejects** when a required tool for your type is missing — the fix guidance is in the error block.

### 3. State the task

```
/kunglao-agent
```

The orchestrator reads `task_spec.yaml` (one-shot intake: primary questions, scope, constraints, success criteria) and enters the convergence loop. The first tick dispatches a static worker; the next tick dispatches a BLIND verifier for the partial fact; the loop alternates dispatch / dispatch_verifier / saturated / blocked until every primary question reaches PROVEN and exit is 0.

### 4. Read the deliverable

```
claim-register.yaml   # every claim terminal with verifier sign-off
facts/F<NNN>.md       # byte-anchored, reproducible, frontmatter contract
evidence/_index.json  # every fact → raw artifact (sha256 + path)
runs/                 # session audit trail
```

---

## A worked analysis case

*The walkthrough below is a representative, synthetic session on a small, deliberately simple sample. It shows the shape of an engagement, not a measured result — for measured outcomes see [Real-world results](#real-world-results).*

**Setup.** A small Windows dropper lands in `~/cases/synth-dropper`. The operator initializes the workspace:

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` scaffolds the workspace, writes the workspace `CLAUDE.md`, probes the toolchain (Ghidra present, VM reachable), and scaffolds `.mcp.json`. The operator runs `/kunglao-agent` and states the task: *"what does this binary do, and where does it phone home?"*

**The loop.** The orchestrator opens `task_spec.yaml` with the primary questions (capability, persistence, network). Each tick is one mechanical decision:

1. `DISPATCH` — a static worker is dispatched first with an explicit contract (`[T1 tools=pe_analyze,strings-classify] claim C-001`). It writes facts: PE structure, imports mapped to capability classes, embedded strings, overlay scan.
2. `DISPATCH_VERIFIER` — for each fact, the redteam verifier re-derives the answer blind from the raw artifact (never reading the maker's conclusion) and signs off `CONFIRMED`; the fact reaches `PROVEN`.
3. `SATURATED` / `BLOCKED` ticks poll stuck workers or resolve blockers — the loop never idles with open claims.
4. `CONVERGED` — every primary question answered with byte-proof, zero orphan claims. The loop exits 0 and builds the report.

**Deliverables.** `claim-register.yaml` (every claim terminal), `facts/` (each fact byte-anchored, with provenance and a reproduce command), `evidence/_index.json` (every fact traceable to a raw artifact), and the final report. Every tick is recorded as a ledger line in `runs/` — the session's audit trail.

---

## Scenario walkthroughs

Three concrete end-to-end paths. Pick the one matching your target.

<details>
<summary><strong>Android APK — what the user types, what lands where</strong></summary>

```bash
# In Claude Code:
/kunglao-agent:init ~/cases/doubao.apk --type android
/kunglao-agent
> state the task: "capability / persistence / network entry points"
```

The orchestrator drives the standard Android flow:

```
APK → aapt/apktool unpack → jadx (DEX to Java)
  → gitnexus analyze (build the post-decompile knowledge graph)
  → static analysis (graph-assisted class / call-chain / entry-point location)
  → dynamic chain only when static stalls:
       ADB → root → debug flag → renamed frida-server (custom port) or android_server
  → last-resort hybrid: frida hook + unidbg
```

- **What lands where:** `bins/<sha256>` (the APK), `facts/F001..` (jvm classes graph), `facts/F050..` (native .so inventory if present), `evidence/` (capture logs, dumps). `claim-register.yaml` shows claims terminating into PROVEN.
- **What "done" looks like:** `convergence_check.py` returns 0; every primary question has at least one PROVEN fact; `task-oracle.yaml` is FAILED-closed.

</details>

<details>
<summary><strong>Web / JS — unpack → deobfuscate → signed-parameter replay</strong></summary>

```bash
# In Claude Code:
/kunglao-agent:init ~/cases/wonderflow.com --type web
/kunglao-agent
> state the task: "what does the XHR signing do, and how does it derive the nonce?"
```

The orchestrator drives the web-re flow:

```
site → camoufox-reverse (anti-detect Firefox: hooks / trace / network capture)
  → unpacking (wakaru / webcrack split routing)
  → deobfuscation (restore encoding layers / resolve opaque predicates)
  → index (skeleton of named functions / exposed endpoints)
  → signed-parameter tracing (five-step replay loop)
  → verify-by-replay: re-derive the signature from inputs only
```

- **What lands where:** `evidence/<capture>.har`, `evidence/<bundle>.js` (deobfuscated), `facts/F001..` (signing key), `facts/F050..` (nonce derivation). The verifier re-derives the signature blind from inputs + key, confirming the model.
- **Note:** web is a *labs* target — zero HARD items by design. The MCP `camoufox-reverse` is WARN; docker channel presence is WARN. Init will not block, but the loop will surface missing capability when it actually needs it.

</details>

<details>
<summary><strong>Local binary (Windows PE / Linux ELF) — DIE → ghidra-light → claims</strong></summary>

```bash
# In Claude Code:
/kunglao-agent:init ~/cases/synth-dropper --type windows
/kunglao-agent
> state the task: "capability / persistence / network"
```

The orchestrator drives the desktop-RE flow:

```
sample → pefile / die / floss (T0: capability / strings / packer family)
  → ghidra-light: analyzeHeadless postScripts
       (recon / decompile-functions / vtable-struct / scan-pointer / evidence-annotations)
  → static analysis on the decompiled tree
  → dynamic chain via vmr-shell / ssh / docker / adb channel
  → claim register builds until PROVEN
```

- **What lands where:** `evidence/die.json` (language / packer family), `evidence/floss-filtered.json` (decoded strings, per-category top-K), `evidence/static-ghidra.json` (functions / imports / xrefs), `facts/F001..` (imports mapped to capability classes), `facts/F050..` (decoded strings + indices).
- **When to escalate T2/T3:** when static cannot close the primary questions (e.g. opaque constants, anti-disasm, packed payload). The dispatch contract declares the static gap list it addresses.

</details>

---

## What you get

A claim register and fact base where trust is mechanical, not conventional:

- **Verified convergence** — `PROVEN` requires an independent BLIND verifier's exact-match sign-off; `CONVERGED` requires every primary question answered with byte-proof, zero orphan claims, no spinning.
- **Evidence integrity** — every fact traces through `evidence/_index.json` to a raw artifact (capture / trace / dump / binary). Derived summaries are excluded by design.
- **Maker-checker** — the worker (maker) writes facts; the redteam verifier (checker) re-derives the answer blind from raw evidence; they are different agents, always.

### Example fact

```yaml
id: F061
status: VERIFIED-BY-W01-static-byte-recheck
confidence: almost_certain        # ICD-203 7-tier
claim_id: C-401
provenance:
  - {role: sample, path: bins/<sha>}
  - {role: capture_log, path: runs/c329-inner-pe.bin}   # cited via evidence/_index.json
reproduce: |
  python -c "import struct; d=open('runs/c329-inner-pe.bin','rb').read(); ..."
verifier_sign_off:
  verifier: kunglao-redteam
  verdict: CONFIRMED
  derived_via: [struct.parse, pefile, capstone]
```

---

## How the loop works

Every tick is one mechanical decision:

| Decision | Exit | What happens |
|---|---|---|
| `DISPATCH` | 1 | rank open claims by VoI/cost, dispatch the top specialist worker |
| `DISPATCH_VERIFIER` | 2 | dispatch a BLIND verifier for a partial fact |
| `SATURATED` | 3 | poll stuck workers — never idle with open claims and free slots |
| `BLOCKED` | 4 | resolve blockers (self-recovery L1→L2→L3), re-check |
| `CONVERGED` | 0 | every primary question answered with byte-proof; build the report |

Dispatch carries an explicit contract — `[T1 tools=grep,xxd] claim C-007 <task>` — enforced by the `worker_budget` hook: ≤3 concurrent workers, per-claim cap, tier gate (T1 static / T2 emulation / T3 VM), live heartbeat, plan-with-content, a declared static-gap list for T2/T3 work.

### Convergence flow (text diagram)

```
        task_spec.yaml
              │
              ▼
   ┌── orchestrator (every round) ──┐
   │                                │
   ▼                                │
DISPATCH ─────► worker ──────┐       │
   ▲                          ▼       │
   │                     fact (PARTIAL)
   │                          │       │
   │                          ▼       │
   │                DISPATCH_VERIFIER  │
   │                          │       │
   │                          ▼       │
   │                  verifier signs   │
   │                  CONFIRMED / REFUTED
   │                          │       │
   │                  all PQs terminal?│
   │                          │  no   │
   └──────────────── SATURATED ◄──────┘
              │ yes
              ▼
        CONVERGED (exit 0)
```

---

## Analysis principle

Five layers, in order of preference — static first, escalate only when the layer above is genuinely insufficient:

1. **Static closure** — complete the analysis statically if at all possible; a task that closes statically never touches dynamic tooling.
2. **Deobfuscation via emulation** — emulated execution strips obfuscation (opaque predicates, indirect jumps, computed constants, encoded blobs) and feeds the result back into static analysis. This serves static; it is not a replacement.
3. **Debug to fill declared gaps** — dynamic debugging (x64dbg / gdbserver / frida) is a complement, not a default: each T2/T3 dispatch must declare the static gap it addresses.
4. **Emulation fallback** — when static + debug data are complete but the logic still resists (e.g. black-box crypto), a hybrid frida-hook + unidbg emulation is used, gated on all three: frida data collected, ida/ghidra decompilation done, still stuck.
5. **Environment construction** — the worst case: build/patch an environment (matching OS version, re-signed APK, sandbox, JNI environment) so the sample runs completely and is observable end to end.

---

## Toolchain by target type

The `kunglao-init --type` choice locks in which HARD-tier tools you must install. Install guidance is collapsed by default — expand the section matching your target.

<details>
<summary><strong>windows (PE32+ x86-64)</strong> — for native Windows binaries</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `pefile` (Python) | `pip install pefile` |
| HARD | `die` (Detect It Easy) | `KUNGLAO_DIE` env or on PATH — [ntinfo.com](https://ntinfo.com) |
| HARD | `floss` (FLARE FLOSS) | install per [flare-floss docs](https://github.com/mandiant/flare-floss) |
| HARD | Ghidra or IDA | one of them; see Internals |
| HARD (T2/T3) | VMware + vmr-shell | for dynamic — see [BYO env](#bring-your-own-analysis-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device-side binary, default port 1337 |
| HARD (T2/T3) | `x64dbg-automate-mcp` | MCP for x64dbg remote control |
| WARN | `volatility` MCP | memory forensics — optional |
| WARN | IDA-Pro MCP | only when IDA is the chosen provider |

Dynamic shortcuts: `ssh` / `docker` channels can substitute for `vmr` if you already have a Windows VM; `local` is **static-only by design** (no sample execution on host).

</details>

<details>
<summary><strong>linux (ELF)</strong> — for native Linux binaries / firmware / memory images</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `file`, `readelf`, `objdump` | `binutils` package |
| HARD | Ghidra or IDA | one of them |
| HARD (T2/T3) | VMware + vmr-shell, or ssh / docker control plane | see [BYO env](#bring-your-own-analysis-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device-side, port 1337 |
| WARN | `gdbserver` | host-side PATH lookup (VM-side binary verified via VM channel) |
| WARN | `strace`, `ltrace` | optional |
| WARN | eBPF (kernel ≥ 6.0 in target VM) | informational |

`ssh-mcp` MCP enables the ssh control plane for remote / cloud / docker hosts.

</details>

<details>
<summary><strong>android (APK / DEX / native .so)</strong> — the hardest target type, most HARD items</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `aapt` or `aapt2` (or `unzip` fallback) | Android SDK build-tools |
| HARD | `jadx` (DEX → Java decompiler) | [skylot/jadx](https://github.com/skylot/jadx) |
| HARD | `apktool` (APK resource decode/rebuild) | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| HARD | `gitnexus` (post-decompile graph) | `npm i -g gitnexus` |
| HARD | Ghidra or IDA | only if APK contains native `.so` |
| HARD | `adb` + **a rooted device** with `ro.debuggable=1` | platform-tools + custom frida on device |
| HARD | `frida-server` (renamed, custom port 1337) | device-side binary |
| HARD | `android_server` (IDA remote debugging) | device-side binary on port 23946 |
| WARN | `apkid` | `pip install apkid` |
| WARN | `baksmali` | from [smali releases](https://github.com/baksmali/smali/releases) |

MCP requirements (all HARD for android): `ghidra` and `sequential-thinking` (required, all types), `gitnexus` (required for Android graph building). Verified by `python scripts/mcp_probe.py <ws> --type android` — exit 1 = HARD missing, init refuses.

</details>

<details>
<summary><strong>web (labs)</strong> — minimal toolchain, no HARD items by design</summary>

| Tier | Tool | Install |
|---|---|---|
| WARN | `camoufox-reverse` MCP | anti-detect Firefox for hook / trace / network capture |
| WARN | `docker` (web channel default) | Docker Desktop, or set `KUNGLAO_CHANNEL=ssh` explicitly |

Web has **zero HARD items** because labs never FAIL-HARD — missing capability is surfaced by the loop when it actually needs it, not at init. If you plan to use the optional x64dbg path for browser-side debug, treat that as a Windows requirement and install the Windows toolchain above.

</details>

<details>
<summary><strong>macos (labs)</strong> — WARN-only, no HARD items by design</summary>

| Tier | Tool | Install |
|---|---|---|
| WARN | `lipo`, `otool`, `nm`, `codesign`, `xattr` | Xcode Command Line Tools |
| WARN | `ghidra` MCP | recommended — [bridge-mcp-ghidra](https://github.com/NationalSecurityAgency/ghidra) |

macOS is a labs target — no HARD items. Use the `ssh` channel (to a Mac host) for dynamic; `local` is static-only.

</details>

### Always required (any type)

| Tier | Tool | Install |
|---|---|---|
| HARD | `ghidra` MCP | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| HARD | `sequential-thinking` MCP | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |

A single manifest source governs all of the above: `python scripts/mcp_probe.py <ws> --type <windows\|linux\|android\|web\|macos>`.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `0` | MUST stay `0`/unset — truthy values route dispatches through the teammate channel (rejected by `env_check_gate`) |
| `KUNGLAO_VM_HOST` | unset | VM lease host for dynamic analysis (vmr-shell :9876 / Frida :1337) |
| `KUNGLAO_CHANNEL` | `vmr` | dynamic-analysis execution control plane: `vmr` \| `ssh` \| `docker` \| `adb` \| `local` (see [Bring your own analysis environment](#bring-your-own-analysis-environment)) |
| `KUNGLAO_DOCKER_CONTAINER` | unset | optional docker execution target for the `ssh`/`docker` channels (probe runs a real `docker exec <c> true`) |
| `GHIDRA_HOME` | unset | Ghidra install root (`support/analyzeHeadless.bat` under it) |
| `KUNGLAO_FRIDA_PORT` | `1337` | override the default custom frida-server port |
| `KUNGLAO_DIE` | unset | path to DIE executable (fallback to PATH) |
| `KUNGLAO_CLAUDE_JSON` | unset | override for user-level `~/.claude.json` MCP registry (tests) |

---

## Bring your own analysis environment

Dynamic debugging needs **an execution control plane the agent can drive**.
`KUNGLAO_CHANNEL` selects one of five equivalent first-class channels —
pick what your environment already has; nothing here is a degraded mode:

| Channel | What it drives | Prerequisites |
|---|---|---|
| `vmr` (default) | VMware-driven VM, **any guest OS**. Snapshot/revert workflows are its irreplaceable value — a Linux VM may be driven by `vmr` (snapshots) or `ssh` (lighter), your choice | vmr-shell skill; `KUNGLAO_VM_HOST` + ports 9876/1337 |
| `ssh` | Any ssh-reachable box: remote bare metal, cloud VM, mac, iOS host, or a remote docker host | `KUNGLAO_VM_HOST` + key auth (probe runs a real `ssh -o BatchMode=yes -p $KUNGLAO_VM_SHELL_PORT <host> true`; BatchMode) |
| `docker` | Local or remote docker daemon — `docker exec` is equivalent to any other control path | `docker version` green (`DOCKER_HOST` for remote); optional `KUNGLAO_DOCKER_CONTAINER` as the execution target |
| `adb` | Android emulator or real device | `adb devices` shows a device; `adb forward tcp:1337 tcp:1337` for frida |
| `local` | **Static-only analysis on the host.** The right choice when static tooling answers the primary questions, or when no dynamic infrastructure exists | none — red line below |

> **`local` red line:** local is a first-class channel for **static** work
> only — never execute, debug, or inject the sample on the host. Any
> dynamic requirement must switch `KUNGLAO_CHANNEL` to `vmr`/`ssh`/
> `docker`/`adb`; init HARD-rejects a dynamic task on `local`.

The channel probe runs only for dynamic tasks (static-only tasks skip all
probes and report a WARN note). Execution on the `ssh` channel flows
through the **ssh-mcp** control plane (`npm i -g ssh-mcp`, TOML profiles —
tools `run-command`, `sftp-upload`, `sftp-download`, session suite);
plain CLI ssh is the fallback. For remote docker over ssh, set
`KUNGLAO_DOCKER_CONTAINER` and the ssh probe additionally verifies
`docker exec` through the host.

---

## Internals

<details>
<summary><strong>Tool shelf (workers' reuse index)</strong></summary>

The tool shelf: reusable analysis logic is absorbed as **registered tools** (machine contract `tools/_INDEX.yaml`, validated by `tools/validate_index.py`; human indexes `tools/_index-<category>.md`). Workers must check the index before writing new scripts (`toolfirst` gate); `tools/tool-search.py` queries it by capability tag and cost budget.

| Category | Tools |
|---|---|
| `crypto` | `crypto-tool` — 8 algorithms, stdlib-only: `chacha` (RFC + non-RFC), `xor-add`, `rolling-xor`, `lzss`, `lzma-raw`, `rsa-unpad`, `go-byte-transform`, `va-to-off`; all support `--reproduce` |
| `ghidra` | 5 analyzeHeadless postScripts: recon / decompile-functions / vtable-struct / evidence-annotations / scan-pointer |
| `static` | disasm-constant-check + syscall / stack-strings / overlay / PE / shellcode scanning CLIs |
| `pipelines` | `build-evidence-index` — evidence index builder (evidence/_index.json + _INDEX.md) |
| `aux` | legacy-PROVEN audit / golden capture / blind-coverage / cold-start metrics |

Host emulation (T2) is deliberately NOT a shelf tool: qiling-based emulation is provided by the external `/malware-framework` skill, which kunglao workers invoke per the analysis principle instead of re-wrapping qiling.

</details>

<details>
<summary><strong>MCP supply (the full manifest)</strong></summary>

MCP supply: the single manifest source is `scripts/mcp_probe.py`; `kunglao-init` scaffolds a workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is never overwritten). Probe: `python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>` (exit 1 = HARD missing, 2 = WARN missing only; run inside the plugin env, e.g. via `uv run --project <skill_root>`, or in the workspace's Claude Code session).

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | required, all types | Ghidra decompilation/static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | required, all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 dynamic | dynamic debugging (VM remote) | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | memory forensics | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | when IDA chosen | remote IDA analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android graph building | post-decompile knowledge graph | `claude mcp add gitnexus -- gitnexus mcp` |
| `virustotal` | WARN | CTI | threat intel (family-attribution hypotheses) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `ssh-mcp` | WARN | channel | ssh execution control plane (KUNGLAO_CHANNEL=ssh dynamics; CLI ssh fallback) | `claude mcp add ssh-mcp -- ssh-mcp` |
| `camoufox-reverse` | WARN | web (labs) | browser JS reverse engineering (anti-detection Firefox: hooks/trace/network capture) | `claude mcp add camoufox-reverse -- python -m camoufox_reverse_mcp` |

</details>

<details>
<summary><strong>Trust gates (the components behind "verified")</strong></summary>

| Gate | Enforces |
|---|---|
| `blind_gate` | `PROVEN` requires independent BLIND verifier sign-off; self-sign rejected |
| `provenance_gate` | facts cite indexed raw artifacts, not derived summaries |
| `convergence_completeness` | `CONVERGED` requires all primary questions terminal + zero orphan claims |
| `convergence_health` | SPINNING flatline detection (count-based, cannot be flooded) |
| `handoff-check.py --anchors` | report anchors preserve the exact numeric counting basis of facts |
| `review_gate.py` | repo commits require ≥1 independent reviewer + HMAC-signed evidence |
| `env_check_gate` | hard-rejects dispatch while the agent-teams flag is truthy |

</details>

<details>
<summary><strong>Workspace layout</strong></summary>

One workspace per sample engagement:

```
<workspace>/
├── bins/<sha256>              # the sample (gitignored)
├── task_spec.yaml             # primary_questions / scope / constraints / success_criteria
├── claim-register.yaml        # claims C-NN with status (OPEN/PROVEN/STAMP/...)
├── claim_deps.yaml            # claim DAG
├── facts/                     # byte-anchored facts F-NNN.md + _INDEX.md
├── evidence/                  # raw artifacts + _index.json (eid → path + sha256)
├── runs/                      # worker-status, plans, ledgers, .heartbeat.json
├── blockers/                  # failure-attribution records per claim
└── CLAUDE.md                  # workspace rules, generated by kunglao-init
```

</details>

<details>
<summary><strong>Two settings levels</strong></summary>

kunglao hooks live at TWO levels (registry: `scripts/wire_up_settings.py`
`HOOK_DEPLOYMENT_TARGETS` — derive, don't copy):

| Level | File | Written by | Carries |
|---|---|---|---|
| workspace | `<ws>/.claude/settings.json` | `--wire-up` | the kunglao hook registrations |
| workspace-parent | `<ws>/../.claude/settings.json` | external_kicker (D2 recovery) | env secrets + mcpServers + block_malware_exec |

The user HOME (`~/.claude/settings.json`) is deliberately NEVER written
(kunglao-init.py:106-111) — production settings are untouchable.

</details>

---

## Real-world results

- **NewSteamValve CDK scam dropper (2026-06-10)** — 601 imports / 16 DLLs mapped to 18 capability classes; 7198 functions / 2144 callgraph edges; 6 sections (no RWX, no overlay); 4143 obfuscated strings decoded (`XOR key=index+0x4d`); 7-stage killchain; verdict **MALICIOUS (9/12)** on 19 independently-verified facts.
- **Numeric-fidelity enforcement (C-020 incident)** — a report collapsed a disassembly count's basis ("811 8-byte ELF slots / 774 Ghidra records, 37 LDDW folded" → "774") and mislabeled 70 `BPF_CALL` as 70 helper calls. The fix: every numeric fact declares its `unit:` basis; `handoff-check.py --anchors` and `manual_audit.py` reject anchors that drop it.
- **Tool-first enforcement (C-022 test)** — a worker given an encrypted blob with zero hints hand-rolled a decode script; after the `toolfirst` gate landed, the same-shaped worker discovered `crypto-tool` via `tools/_INDEX.yaml` during its plan phase and ran the registered CLIs, documenting negative results per algorithm.

---

## Development

SDD (OpenSpec) + TDD: one issue → one PR → one branch → one worktree, merged to `dev` then `master`. Every commit requires ≥1 independent reviewer sign-off minted through `review_gate.py` (HMAC).

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q                    # RED → GREEN → refactor
uv run python scripts/release_receipt.py --check
gh pr create --base dev
```

The `pytest` line above is the authoritative full-suite entry; matrix-style
scoped runs go through `scripts/run_test_matrix.py` (same environment, no
extra flags needed).

The release contract is revision-owned: `pyproject.toml` + `uv.lock` (pinned deps), `release-manifest.yaml` (declared asset inventory), `release_receipt.py` (observed inventory: per-asset sha256, CLI `--help` exit codes, test results). CI runs it on every PR. Depth lives in `docs/` (design, loop engineering), `specs/`, and `AGENTS.md`.

---

## Limitations

- 46 legacy `PROVEN` claims audited (10 have-raw / 18 derivation-only / 19 unverifiable) — re-verification is follow-up work
- ICD-203 conformance is partial (tradecraft #1/#2/#5/#8/#9; full certification out of scope)
- Dynamic analysis requires per-session authorization; sample execution is VM-only, host execution is blocked by a hook
- Type-aware init (Windows/Linux/Android toolchain matrix) and the remaining script-absorption batch are in development (issues)

---

## Safety

- Samples never execute on the host — `block_malware_exec` hook enforces; VM-only via `vmr-shell`
- Bins / settings / hooks never committed; secrets excluded
- Ground truth hierarchy: raw artifact > local tool > sandbox > CTI (CTI is falsifiable claim, never truth)
- Maker-checker: a worker never self-verifies; a verifier never reads the maker's conclusion

---

## License

Dual-licensed: **AGPL-3.0** for personal, academic, and internal use (free — see [LICENSE](LICENSE)); **commercial license** required for closed-source or SaaS commercial use — see [LICENSE-commercial.md](LICENSE-commercial.md).