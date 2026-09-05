# kunglao-agent

**kunglao-agent is an autonomous reverse-engineering system. You hand it a target and the questions you need answered; it works the problem for hours or days on its own — planning its own path, recovering from worker deaths, resuming after crashes — and converges only when every answer is derived from raw evidence and survives mechanical verification gates.**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](.) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](.) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](.)

**English** · [Simplified Chinese](README.zh-CN.md)

It currently ships as a Claude Code plugin — Claude Code is the interface you talk to, not what the product is. The product is the loop: specialist workers analyse (static first), an independent verifier re-derives every fact blind from the raw evidence, and mechanical gates decide when the work is done. The deliverable is a fact base where every claim is byte-anchored, independently verified, and evidence-indexed — trust is enforced by machinery, not convention.

## Why kunglao-agent

- **Long-horizon by design.** Engagements run unattended across hours and days: a scheduled heartbeat keeps the loop alive, dead workers are reconciled and their claims re-queued, crashes resume from on-disk state, blocked claims self-recover. You read the verdict when it converges — you don't babysit each step. See [Long-horizon autonomy](#long-horizon-autonomy).
- **Answers you can trust.** No fact is `PROVEN` until an independent verifier re-derives it blind from the raw artifact; every fact cites a sha256-indexed raw artifact through `evidence/_index.json`.
- **The full reverse-engineering spectrum.** Windows/Linux native binaries, Android APKs, web/JS, protocol analysis, firmware emulation, risk-control countermeasures — one system, not a single-domain tool.
- **Static-first economics.** A task that closes statically never touches dynamic tooling; every escalation is declared, gated, and audited.
- **It reuses knowledge instead of re-deriving it.** A growing catalog of registered analysis tools (crypto decoders, disassembly pipelines, graph queries) means the system reaches for proven tooling before writing one-off scripts — and every run leaves behind reusable facts, not a chat transcript that evaporates.
- **It recovers instead of dying.** Worker deaths, API disconnects, and crashes are first-class events: the loop detects them, snapshots what was already produced, and re-dispatches to continue from where things stopped — not from zero.
- **Your environment, your rules.** VMware, ssh, docker, adb, or plain static-only — the system drives whichever execution channel you already have. Nothing is a degraded mode; a task that never needs execution never asks for a VM.

## Quick start

kunglao-agent runs inside Claude Code. From a sample on disk to a verdict:

| Tool | Why | Install |
|---|---|---|
| **Claude Code** | where kunglao-agent runs | per Anthropic docs |
| **Python 3.10+** | the plugin carries a pinned env via `uv`; you do not touch it | system or `uv`-managed |
| **`uv`** | locked env resolver | `pip install uv` or [astral.sh/uv](https://astral.sh/uv) |
| **Ghidra or IDA** | one static-analysis suite for decompilation | see [Toolchain by target](#toolchain-by-target) |

### 1. Install the plugin

From any directory, in Claude Code:

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

(Alternative: `claude --plugin-dir /path/to/kunglao-agent` for development.)

### 2. Init a workspace

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` scaffolds the workspace, writes `CLAUDE.md`, probes the toolchain for your `--type`, and scaffolds `.mcp.json`. It **HARD-rejects** when a required tool for your type is missing — the fix guidance is in the error block.

### 3. State the task and start the analysis

```
/kunglao-agent:analysis ~/cases/synth-dropper
> Goal: confirm this dropper's persistence mechanism and network endpoints;
>   every conclusion must be reproducible from raw evidence.
> Verification: key findings count only if an independent verifier re-derives
>   them blind and reaches the same answer.
> Constraints: static-first; never execute the sample on the host.
```

Write the brief so an independent reviewer could judge the result: **analysis goal** (what you need to know), **verification logic** (what makes an answer trustworthy — e.g. "the signature must be reproducible from the same inputs"), **constraints** (e.g. "no execution on the host"). Everything is recorded in `task_spec.yaml`; from there the loop drives itself.

### 4. Read the deliverable

```
claim-register.yaml   # every claim terminal, with verifier sign-off
facts/F<NNN>.md       # byte-anchored, reproducible, frontmatter contract
evidence/_index.json  # every fact → raw artifact (sha256 + path)
runs/                 # session audit trail
```

## Subcommands

| Command | Use when | What it does |
|---|---|---|
| `/kunglao-agent:init <path> --type <windows\|linux\|android\|web\|macos>` | starting an engagement, first | scaffolds the workspace, probes the toolchain for the type, writes `CLAUDE.md` and `.mcp.json`; HARD-rejects with fix guidance when a required tool is missing |
| `/kunglao-agent:analysis <path>` (alias `analyze`) | after init — state the task and start | collects your goal / verification logic / constraints once, then runs the convergence loop: dispatch / verify cycles until the report |
| `/kunglao-agent:resume <path>` | after a crash, reboot, or any "where was I?" | read-only breakpoint brief (health, open claims, in-flight workers, crash timeline) plus the next action from the state machine |
| `/kunglao-agent:upgrade <path> [--dry-run]` | after a plugin update, on an older workspace (or when the upgrade prompt says the stamp is behind) | migrates the workspace scaffold (hooks, templates, event vocab) to the current plugin version; `--dry-run` previews; user data (claims, facts, evidence) is never touched — byte drift refuses with RC=4 |
| `/kunglao-agent:help` | anything else | prints the usage list |

Typical order: `init` creates the workspace → `analysis` states the task and starts → (`resume` if anything goes sideways) → read the report at convergence → `upgrade` old workspaces after plugin updates.

## What a run looks like

*The shape of an engagement — what you type, what comes back, where to look.* A small Windows dropper lands in `~/cases/synth-dropper`:

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # probes Ghidra, VM reachability
/kunglao-agent:analysis ~/cases/synth-dropper
> "What does this binary do, and where does it phone home?"
```

From there the loop runs itself — the route adapts to what the sample turns out to be. You can walk away (see [Long-horizon autonomy](#long-horizon-autonomy)). When it converges, read the deliverable below.

## Scenarios

Two more end-to-end paths — pick the one matching your target (for a plain Windows PE / Linux ELF binary, the worked case above is the path).

<details>
<summary><strong>Android APK — what the user types, what lands where</strong></summary>

```bash
/kunglao-agent:init ~/cases/sample.apk --type android
/kunglao-agent:analysis ~/cases/sample.apk
> "Does this APK load code dynamically or fight debugging? If so, where is
>   the hidden logic and what does it do?"
```

- **Lands in:** `bins/<sha256>` (the APK), `facts/` (class graph, native `.so` inventory), `evidence/` (captures, dumps).
- **Done looks like:** every question backed by reproducible evidence.
- **The route adapts.** Some APKs close with pure static DEX work; others need on-device debugging — the loop decides from what the sample actually is.

</details>

<details>
<summary><strong>Web / JS — unpack → deobfuscate → signed-parameter replay</strong></summary>

```bash
/kunglao-agent:init ~/cases/example-site.com --type web
/kunglao-agent:analysis ~/cases/example-site.com
> "how is the XHR request signed, and where does the nonce come from?"
```

- **Lands in:** `evidence/` (captures, deobfuscated code), `facts/` (signing key, nonce derivation).
- **Note:** `web` is a beta-stage target — the toolchain bar is deliberately light; missing capability surfaces when the loop actually needs it, not at init.

</details>

## What you get

A claim register and fact base where trust is mechanical, not conventional:

- **Verified convergence** — `PROVEN` requires an independent blind verifier's exact-match sign-off; `CONVERGED` requires every primary question answered with byte-proof, zero orphan claims, no spinning.
- **Evidence integrity** — every fact traces through `evidence/_index.json` to a raw artifact (capture / trace / dump / binary). Derived summaries are excluded by design.
- **Maker-checker** — the worker (maker) writes facts; the redteam verifier (checker) re-derives them blind. Different agents, always.

No claim reaches `PROVEN` on its author's word: an independent verifier must re-derive it blind, and a set of mechanical gates must pass. The full gate design lives in [`docs/design/loop-engineering.md`](docs/design/loop-engineering.md).

After the run, the files answer different questions:

| Question | Where |
|---|---|
| Is it done? | the loop's exit code — `CONVERGED` (0) means every primary question has a verified answer; per-claim status in `claim-register.yaml` |
| What did it find? | `facts/F<NNN>.md` — one byte-anchored fact per file, mapped to claims by `claim-register.yaml` |
| How do I reproduce it? | `evidence/_index.json` — fact → raw artifact (path + sha256); each fact carries a `reproduce:` command |
| What exactly happened? | `runs/` — the tick-by-tick ledger and worker status |

Example fact:

```yaml
id: F061
status: VERIFIED-BY-W01-static-byte-recheck
claim_id: C-401
provenance:
  - {role: sample, path: bins/<sha>}
  - {role: capture_log, path: runs/c329-inner-pe.bin}   # via evidence/_index.json
reproduce: python -c "import struct; ..."               # runs against the cited artifact
verifier_sign_off: {verifier: kunglao-redteam, verdict: CONFIRMED}
```

## Long-horizon autonomy

Real engagements are not a twenty-minute chat. kunglao-agent stays on the problem without a human shepherding every step:

- **Runs for hours or days, unattended** — a scheduled heartbeat keeps the loop working between your visits, and a stalled loop is flagged instead of silently dying.
- **Recovers from failure** — dead or stuck workers are replaced and their questions re-queued; blocked work self-recovers instead of idling.
- **Survives crashes and reboots** — `/kunglao-agent:resume <workspace>` rebuilds where things stood from on-disk state and names the next action.
- **Remembers on disk, not in chat** — claims, facts, evidence, and a full audit trail live in the workspace, so any session can pick the engagement back up.

You give it a target and the questions; it works the problem for hours or days, recovers from failures, and you read the verdict when it converges.

## Getting good results

- **Feed it static-accessible targets.** The loop is static-first: an unpacked APK, an unobfuscated bundle, or an unstripped binary converges far faster than one that forces dynamic work.
- **Set up the dynamic leg before you need it.** If your primary questions will require execution, pick a channel first (see [Bring your own environment](#bring-your-own-environment)) — init HARD-rejects a dynamic task on `local`.
- **Telling "working" from "stuck"** — fresh entries in `runs/` mean the loop is alive; a dead heartbeat or the same decision repeating with no new facts means it is not — `/kunglao-agent:resume <workspace>` diagnoses and names the next move.

## Toolchain by target

The `--type` you pick at init locks which HARD-tier tools must be installed. Guidance is collapsed — expand your target. **All types require two MCP servers:** `ghidra` (`claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe`) and `sequential-thinking` (`claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking`).

<details>
<summary><strong>windows (PE32+ x86-64)</strong> — native Windows binaries</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `pefile` (Python) | `pip install pefile` |
| HARD | `die` (Detect It Easy) | `KUNGLAO_DIE` env or on PATH — [ntinfo.com](https://ntinfo.com) |
| HARD | `floss` (FLARE FLOSS) | per [flare-floss docs](https://github.com/mandiant/flare-floss) |
| HARD | Ghidra or IDA | one of them; see [Internals](#internals) |
| HARD (T2/T3) | VMware + vmr-shell, or an ssh/docker channel | see [Bring your own environment](#bring-your-own-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device/VM-side binary, default port 1337 |

Windows T3 dynamic also uses the `x64dbg` MCP; `volatility` (memory forensics) and IDA-Pro MCP are optional — see the MCP manifest under [Internals](#internals).

</details>

<details>
<summary><strong>linux (ELF)</strong> — native Linux binaries / firmware / memory images</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `file`, `readelf`, `objdump` | `binutils` package |
| HARD | Ghidra or IDA | one of them |
| HARD (T2/T3) | VMware + vmr-shell, or an ssh/docker control plane | see [Bring your own environment](#bring-your-own-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device-side binary, port 1337 |
| WARN | `gdbserver` (host-side PATH), `strace`, `ltrace` | optional extras |

`ssh-mcp` enables the ssh control plane for remote / cloud / docker hosts.

</details>

<details>
<summary><strong>android (APK / DEX / native .so)</strong> — the hardest target type, most HARD items</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `aapt` or `aapt2` (or `unzip` fallback) | Android SDK build-tools |
| HARD | `jadx` (DEX → Java decompiler) | [skylot/jadx](https://github.com/skylot/jadx) |
| HARD | `apktool` (APK resource decode/rebuild) | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) |
| HARD | `gitnexus` (post-decompile graph) | `npm i -g gitnexus` |
| HARD | Ghidra or IDA | only if the APK contains native `.so` |
| HARD | `adb` + **a rooted device** with `ro.debuggable=1` | platform-tools + custom frida on device |
| HARD | `frida-server` (renamed, custom port 1337) | device-side binary |
| HARD | `android_server` (IDA remote debugging) | device-side binary, port 23946 |
| WARN | `apkid` | `pip install apkid` |
| WARN | `baksmali` | from [smali releases](https://github.com/baksmali/smali/releases) |

</details>

<details>
<summary><strong>web &amp; macos (beta)</strong> — minimal toolchains, no HARD items by design</summary>

| Tier | Tool | Install |
|---|---|---|
| WARN | `camoufox-reverse` MCP (web) | anti-detect Firefox for hook / trace / network capture |
| WARN | `docker` (web channel default) | Docker Desktop, or set `KUNGLAO_CHANNEL=ssh` explicitly |
| WARN | `lipo`, `otool`, `nm`, `codesign`, `xattr` (macOS) | Xcode Command Line Tools |
| WARN | `ghidra` MCP (macOS) | recommended — see the manifest under [Internals](#internals) |

Both are beta-stage targets: missing capability surfaces when the loop actually needs it, not at init. macOS dynamic work uses the `ssh` channel (to a Mac host); for the optional x64dbg browser-debug path, install the Windows toolchain above.

</details>

Single manifest source for everything above — probe it any time: `python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>` (exit 1 = HARD missing).

## Bring your own environment

Dynamic debugging needs an execution control plane the agent can drive. `KUNGLAO_CHANNEL` selects one of five first-class channels — use what your environment already has; none is a degraded mode:

| Channel | What it drives | Prerequisites |
|---|---|---|
| `vmr` (default) | VMware VM, **any guest OS** — snapshot/revert workflows are its irreplaceable value | vmr-shell skill; `KUNGLAO_VM_HOST` + ports 9876/1337 |
| `ssh` | Any ssh-reachable box: bare metal, cloud VM, Mac, remote docker host | key auth — the probe runs a real BatchMode `ssh ... true` |
| `docker` | Local or remote docker daemon — `docker exec` is equivalent to any control path | `docker version` green; optional `KUNGLAO_DOCKER_CONTAINER` |
| `adb` | Android emulator or real device | `adb devices` shows it; `adb forward tcp:1337 tcp:1337` for frida |
| `local` | **Static-only analysis on the host** | none — see the red line |

> **`local` red line:** local is for **static** work only — never execute, debug, or inject the sample on the host. Any dynamic requirement switches `KUNGLAO_CHANNEL` to `vmr`/`ssh`/`docker`/`adb`; init HARD-rejects a dynamic task on `local`.

Channel probes run only for dynamic tasks (static-only tasks skip them). `ssh`-channel execution flows through the **ssh-mcp** control plane (`npm i -g ssh-mcp`); plain CLI ssh is the fallback. For remote docker over ssh, set `KUNGLAO_DOCKER_CONTAINER`.

## Configuration

Four variables cover most setups:

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | unset | must stay unset or `0` — truthy values route dispatches through the teammate channel and are rejected |
| `KUNGLAO_CHANNEL` | `vmr` | dynamic execution control plane: `vmr` \| `ssh` \| `docker` \| `adb` \| `local` — see [Bring your own environment](#bring-your-own-environment) |
| `KUNGLAO_VM_HOST` | unset | VM/host for dynamic analysis (vmr-shell :9876, Frida :1337) |
| `GHIDRA_HOME` | unset | Ghidra install root (must contain `support/analyzeHeadless.bat`) |

Rarely needed: `KUNGLAO_DOCKER_CONTAINER` (docker execution target for the `ssh`/`docker` channels), `KUNGLAO_FRIDA_PORT` (default 1337), `KUNGLAO_DIE` (DIE path, falls back to PATH), `KUNGLAO_CLAUDE_JSON` (test override for the user-level MCP registry).

## Safety

- Samples never execute on the host — the `block_malware_exec` hook enforces it; dynamic work runs VM/container/device-only and requires per-session authorization.
- Ground truth hierarchy: raw artifact > local tool > sandbox > threat intel (CTI is a falsifiable hypothesis, never truth).
- Maker-checker: a worker never self-verifies; a verifier never reads the maker's conclusion.
- Bins, settings, and hooks are never committed; secrets are excluded from workspaces and the repo.

## Development

Contributions are welcome. Workflow: branch from `dev`, one branch per change, PR back to `dev`.

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q
gh pr create --base dev
```

Design documentation lives in `docs/` and `specs/`. See [License](#license).

## Internals

<details>
<summary><strong>MCP supply (the full manifest)</strong></summary>

Single source of truth: `scripts/mcp_probe.py`; `kunglao-init` scaffolds a workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is never overwritten). Probe: `python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>` — exit 1 = HARD missing, 2 = WARN missing only.

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | required, all types | decompilation / static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | required, all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 dynamic | dynamic debugging (VM remote) | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | memory forensics | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | when IDA chosen | remote IDA analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android graph building | post-decompile knowledge graph | `claude mcp add gitnexus -- gitnexus mcp` |
| `virustotal` | WARN | CTI | threat intel (family-attribution hypotheses) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `ssh-mcp` | WARN | channel | ssh execution control plane | `claude mcp add ssh-mcp -- ssh-mcp` |
| `camoufox-reverse` | WARN | web (beta) | browser JS reversing (hooks / trace / network capture) | `claude mcp add camoufox-reverse -- python -m camoufox_reverse_mcp` |

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

kunglao hooks are wired at workspace level; your global `~/.claude/settings.json` is never written.

</details>

---

## License

Dual-licensed: **AGPL-3.0** for personal, academic, and internal use (free — see [LICENSE](LICENSE)); a **commercial license** is required for closed-source or SaaS commercial use — see [LICENSE-commercial.md](LICENSE-commercial.md).
