# kunglao-agent

**An autonomous reverse-engineering agent that runs for hours unattended, verifies every conclusion independently, and converges only when every answer survives a mechanical oracle verdict.**

[![release](https://img.shields.io/github/v/release/amd2g2zz/kunglao-agent?sort=semver)](https://github.com/amd2g2zz/kunglao-agent/releases)
[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![runtime](https://img.shields.io/badge/runtime-Claude%20Code%20plugin-7aa2f7)](https://claude.com/claude-code)
[![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

**🧠 plans its own route** · **🔬 every claim machine-checked** · **⚖️ blind verification on everything** · **📈 the loop measures itself**

🚀 Quick Start · ✨ Core Tech · 🧠 kunglao × Claude Code · 🎛️ How RL Works · 🖥️ Showcase · 📖 Case Studies · 🧪 Evaluation · 🏗️ Architecture · 🗓️ Roadmap

**English** · [简体中文](README.zh-CN.md)

> [!WARNING]
> **v0.1.6 is the last Claude Code-native release line.** The next
> milestone (v0.2) migrates the runtime wholesale to the PI Agent base —
> same loop, same ledgers, new engine substrate. See the roadmap.

---

## 📖 Introduction

You point kunglao-agent at a target and state the questions; it plans the
route, dispatches specialist workers, verifies every conclusion independently,
and stops only when each answer is settled by a mechanical check instead of a
model's say-so.

The target spectrum is the full one — Windows/Linux native binaries, Android
APKs (including native `.so` layers), web/JS, protocol recovery, firmware —
static-first by design, driving whichever execution channel your environment
already has (VMware, ssh, docker, adb, or none at all for static-only work).

It runs inside [Claude Code](https://claude.com/claude-code) as a plugin:
Claude Code is the conversation surface; the product is the loop and the fact
base it produces.

> [!NOTE]
> Every number the loop reports — win rates, posteriors, budgets — traces to a
> row on an append-only ledger. Nothing is self-declared.

---

## 🖥️ Showcase

**The orchestrator at work** — a convergence decision, a budgeted worker
dispatch with live facts landing, and a blind red-team verdict promoting a
claim to `PROVEN`; the statusline HUD keeps the whole engagement readable at
a glance:

![kunglao-agent orchestrator session: convergence check, worker dispatch, blind red-team verification, statusline HUD](docs/assets/showcase-orchestrator.svg)

**The loop measuring itself** — the round strategy composed from settlements,
the discounted-Thompson posterior store with censored-outcome tiebreaking,
the discovery layer admitting a genuinely novel arm (and refusing a renamed
retry), and the win-rate curve:

![kunglao-agent learning faces: round strategy, posterior store, expansion receipt, win-rate curve](docs/assets/showcase-learning.svg)

---

## ✨ Core technology

kunglao-agent is an **act-level RL controller around Claude Code**: Claude
Code reasons inside each act; kunglao decides the next act, verifies it,
prices it, learns from it. Deep design: [`docs/design/`](docs/design/).

- **Mechanical oracle.** The completion criterion derives from your task
  statement as runnable checks (byte-exact replay, held-out probes). Reward
  is priced in oracle verdicts — lying about progress earns nothing.
- **Blind verification.** An independent verifier re-derives every claim
  without seeing the maker's reasoning; worker self-sign-off caps at
  `STAMP`, never `PROVEN`. Facts cite artifacts (sha256) and carry
  `reproduce:` commands.
- **The loop learns, the model stays frozen.** Every act lands on an
  append-only ledger; a Thompson-sampling policy reorders method families
  by measured cost-adjusted success per feature-keyed state.
- **Unattended, resumable.** Hours-long runs, dead workers replaced, full
  state on disk, every reported number traces to a ledger row.

---

## 🧠 kunglao × Claude Code

Claude Code is the engine; kunglao is the gearbox, dashboard, and flight
computer — next act, verification, budget, and where experience goes.

| | bare Claude Code | + kunglao |
|---|---|---|
| Next step | improvised in-session | learned act-level policy, posteriors persist across tasks |
| Verification | self-report | mechanical oracle + blind red-team |
| Duration | one session, human watching | hours unattended, resume from disk |
| Experience | evaporates at session end | ledger → posteriors → sharper opening bet |

![The controller picks each act, Claude Code executes it, the ledger remembers](docs/assets/rl-drive.gif)

Honest boundary: for a simple single-session task, bare Claude Code wins —
the evaluation table says so. kunglao pays off on long horizons,
verification discipline, and cross-task compounding.

---

## 🎛️ Online RL: the loop gets better while it works

The first task of a new kind pays full price: the loop tries a method,
watches it fail, tries another. But every attempt is written down — and
the next task of the same kind opens from those notes, not from zero.

![One task pays full price; the loop remembers; the second runs cheaper](docs/assets/rl-loop.gif)

That is the whole idea of online reinforcement learning here: **the loop
updates itself between acts, on the job** — no training dataset, no model
retraining, no offline phase. Each task's experience is banked before the
next decision is made.

### What the loop actually learns

**1. The right first move, per kind of target.** A plain script and a
hardened app should not open the same way. The loop keeps separate notes
per kind of target — what the target looks like decides which playbook
applies.

![Two targets route to two different playbooks](docs/assets/rl-features.gif)

**2. Which methods are dead.** A method that keeps failing gets benched —
it stops eating budget (but is never deleted; if the target changes, it
can come back). And when *nothing* works, the loop tries to invent a way
in: a discovery act proposes a genuinely new approach, checked against the
failed tries — the same idea renamed is refused.

![Dead ends get benched; a genuinely new idea gets admitted](docs/assets/rl-death-discovery.gif)

**3. Where to double-check.** States where verifiers keep getting refuted
learn to schedule verification more tightly there — and relax when the
streak turns honest.
**4. Which tools to route.** Tool and provider choices are learned too: a tool that fails gets demoted for a while and is reinstated the moment it works again - routing follows the recorded outcomes, not the registry order.

### How the learning works

```mermaid
flowchart LR
    A["target state<br>(what it looks like)"] --> B["pick a method<br>(sample from the notes)"]
    B --> C["act<br>(a worker runs it)"]
    C --> D["checker verdict<br>(proof or no proof)"]
    D --> E["one ledger row<br>(what happened, what it cost)"]
    E --> F["update the notes<br>for this kind of target"]
    F --> B
```

The notes are simple success/failure tallies per method per state, with a
bias toward trying anything not yet ruled out — exploration fades exactly
as fast as evidence accumulates. Reward is `progress x weight - cost`, so
an expensive habit that barely moves the needle loses money on simple
targets, and every number traces to an append-only ledger row.

### What this buys - and what it deliberately does not

- **Cost drops on familiar work.** The second task of a kind is cheaper
  than the first; the notes persist across tasks in the deployment.
- **Budget stops bleeding.** Dead methods are benched before they drain
  the clock; the discovery layer replaces vocabulary nobody wrote.
![Win rate rises, steps to solve falls - the loop's own ledger is the evidence](docs/assets/rl-curves.gif)

- **The model is frozen.** Capability does not grow - scheduling does:
  the right method, in the right order, at the right moment.
- **Honesty is not learned - it is enforced.** The checker pays only for
  results it can re-verify; a worker's own words never count as proof.
  RL optimizes efficiency on top of that honest currency; it can never
  mint credit by fiction.

![The checker pays only for verifiable results](docs/assets/rl-pricing.gif)

### How this differs from the common approaches

Knowledge routing (a manual the LLM improvises against), bounded pipelines
(fixed stages, fixed rounds), single-verdict triage - all decide with fixed
logic: last task's experience never changes next task's plan. The loop's
control law is learned from its own measured history:

![Side by side: three systems repeat their price on the second task; kunglao's second task opens cheaper](docs/assets/rl-comparison.gif)

## 📋 Requirements

| Component | Requirement | Notes |
|---|---|---|
| Claude Code | current | the runtime — install as a plugin |
| Python 3.10 | 3.10+ floor (Python 2 is not supported) | the plugin carries a pinned env via `uv` |
| `uv` | any recent | `pip install uv` or [astral.sh/uv](https://astral.sh/uv) |
| Ghidra or IDA | one of them | decompilation for native targets |
| MCP servers | 2 required | `ghidra` + `sequential-thinking` — see [Toolchain](#-toolchain-by-target) |

> [!WARNING]
> Analysis acts run real tools and may execute target-derived inputs. Use
> isolated VMs/devices for dynamic work and only analyze targets you are
> authorized to.

---

## Quick start

From a sample on disk to a verdict:

### 1. Install the plugin

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

(Development alternative: `claude --plugin-dir /path/to/kunglao-agent`.)

### 2. Init a workspace

```
/kunglao-agent:init ~/cases/synth-dropper --type windows
```

`kunglao-init` scaffolds the workspace, probes the toolchain for your
`--type`, and HARD-rejects with fix guidance when a required tool is
missing.

### 3. State the task and start

```
/kunglao-agent:analysis ~/cases/synth-dropper
> Goal: confirm this dropper's persistence mechanism and network endpoints;
>   every conclusion must be reproducible from raw evidence.
> Verification: key findings count only if an independent verifier re-derives
>   them blind and reaches the same answer.
> Constraints: static-first; never execute the sample on the host.
```

Write the brief so an independent reviewer could judge the result: analysis
goal, verification logic, constraints. Everything is recorded in
`task_spec.yaml`; from there the loop drives itself — walk away, dead
workers are replaced and their questions re-queued, and
`/kunglao-agent:resume` rebuilds the picture after any interruption.

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
| `/kunglao-agent:init <workspace> [--type windows\|linux\|android\|web\|macos] [--lane malware\|algorithm\|protocol\|web\|data\|app]` | starting an engagement, first | scaffolds the workspace, probes the toolchain, writes `CLAUDE.md` and `.mcp.json` (`--no-mcp` skips); HARD-rejects with fix guidance when a required tool is missing |
| `/kunglao-agent:analysis <workspace>` (alias `analyze`) | after init — state the task and start | collects goal / verification logic / constraints once, then runs the convergence loop |
| `/kunglao-agent:resume <workspace>` | after a crash, reboot, or any "where was I?" | read-only breakpoint brief (health, open claims, in-flight workers) plus the next action |
| `/kunglao-agent:upgrade <workspace> [--dry-run]` | after a plugin update | migrates the workspace scaffold; user data never touched — byte drift refuses |
| `/kunglao-agent:help` | anything else | prints the usage list |

`uv sync` registers the router as the `kunglao` console script —
`kunglao --help` lists all subcommands (`decide`, `tick`, `verify`,
`record`, `health`, `resume`, `check-stale`, `upgrade`, `analysis`).
Dedicated entries: `kunglao-init`, `kunglao-verify`, `kunglao-upgrade`,
`heartbeat-tick`, `convergence-check`.

---

## What a run looks like

A synthetic example (representative, not a real measured engagement): a
small Windows dropper lands in `~/cases/synth-dropper`:

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # probes Ghidra, VM reachability
/kunglao-agent:analysis ~/cases/synth-dropper
> "What does this binary do, and where does it phone home?"
```

From there the loop runs itself — the route adapts to what the sample
turns out to be. You can walk away; dead workers are replaced and their
questions re-queued, and `/kunglao-agent:resume` rebuilds the picture
from on-disk state after any interruption.

---

## 📖 Stating the task

The loop derives its oracle mechanically from the end-state you state. Four
phrasings cover most of the drift:

| You say | It usually means | The oracle anchors on |
|---|---|---|
| "I want the pure algorithm" | offline reproduction of the signing/crypto routine | byte-exact replay of every captured pair, including withheld ones |
| "I want decryption" | one captured body, or a reusable capability? | plaintext validates / canary round-trips byte-identical |
| "analyze this protocol" | wire-format recovery + a runnable codec | the codec round-trips every captured frame byte-exact |
| "where is `sign` computed?" | a location with proof | a named function + a hook there reproducing captured values |

Name the sample and the behavior (not the category), make success be data
(captured pairs — the withheld ones keep it honest), and state constraints
up front (static-only? a device? which channel?).

---

## 🧰 The run you watch

Two live faces turn a run into something observable:

**The statusline** — a one-line HUD while the agent runs: the semantic state
glyph (`◈ analyzing` / `✖ DOWN`), claim progress `C 6/8`, current win rate,
the sampler's top-ranked arm and its age, health dots, the active task chip,
and a value sparkline. Stale-but-within-policy renders idle (truthful);
beyond policy it renders DOWN.

**The win-rate curve** — rolling pass rate over the settlement stream:

```bash
uv run python scripts/winrate_curve.py <workspace> [--window 5] [--html curve.html]
```

A healthy run trends upward as the loop learns which methods pay; a flat
zero line says the ranker is spending budget on arms that never settle —
check the obstacle registry before adding budget.

---

## 📚 Case studies

Evidence-first case studies rewritten from real, fully converged run artifacts
(EN + 简体中文) — the transcript, the dead ends, the two named verification
methods, and the mechanical verdict:

- [kvm8-isa: a private VM decoded from its reference interpreter](docs/cases/kvm8-isa.md) — KVM-8 ISA recovered (container, 10-op nibble map, guard bytes, `mix()` machine); 44/44 words decoded, four digests byte-exact against a rustc build of the reference interpreter; decoy `fold8` control caught emitting one constant wrong line for all four payloads.
- [web-token-v1: a signing SDK reversed to a one-line HMAC](docs/cases/web-token-v1.md) — key reassembled from scrambled base64 table parts, pad placement settled by falsification, `client.py` mints tokens for 4/4 fresh sessions; a captured token dies on replay across server instances.
- [apk-webview-attest-v2: two attestation layers bound](docs/cases/apk-webview-attest-v2.md) — JS PoW/mix challenge feeds the seed into a native `sha256(seed‖nonce)[:8] ^ NATIVE_MASK` check; 8-byte mask re-derived from raw ELF bytes, 4/4 sessions through both layers, negative control rejected with 403.

Each case has a Chinese version alongside the English one under `docs/cases/`.

---

## 🧪 Evaluation and measured results

Constructed targets with mechanical oracles and ground truth known by
construction; checkers mint held-out probes the candidate never saw. The
built-in 12-unit L1 matrix (static RE targets across JS, x86/ARM64 ELF,
Windows PE; byte-anchored deliverables only, no partial credit, pass@1,
per-session caps):

| Runtime | pass@1 | Session cost |
|---|---|---|
| kunglao v0.1.5.post2 | 5/12 | ~$135 total (13 sessions) |
| kunglao v0.1.6 | **11/12** | ~$120 total (4 governed rounds) |
| plain Claude Code | 12/12 | ~$11.4 total |

Read honestly: these 12 units are single-session-tractable and a frontier
model with default tools saturates them cheapest — kunglao's differentiation
is **long-horizon layered work, verification discipline (oracle + blind
red-team on every claim), and the dynamic lanes**, not single-session speed.
The measured long-horizon matrices and the five-arm comparison (bare CC /
CC+warm-context / kunglao cold / kunglao warm / no-recall ablation) land
with the current release train.

Control-arm A/B and the replay ruler (offline ranker-quality measurement)
ship as commands: `scripts/eval_control_arm.py --ab`, `scripts/replay_ruler.py <ws>`.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    Task[task_spec.yaml — you state the goal] --> Oracle[mechanical oracle — quantified contracts]
    Oracle --> Loop{convergence loop}
    Loop -->|dispatch| Workers[workers — byte-anchored facts]
    Loop -->|verify| Verifier[blind verifier / red-team]
    Workers --> Facts[(facts + evidence index)]
    Verifier --> Gates[mechanical gates — settlements]
    Gates --> Ledger[(append-only ledgers)]
    Ledger --> Policy[external policy: DTS posteriors + discovery]
    Policy --> Loop
    Ledger --> Report[claim register — every claim terminal]
```

One workspace per engagement — scaffolded by init; hooks are wired at workspace level and your global `~/.claude/settings.json` is never written:

<details>
<summary><strong>Workspace layout</strong></summary>

```
<workspace>/
├── bins/<sha256>        # the sample (gitignored)
├── task_spec.yaml       # goal / verification logic / constraints
├── claim-register.yaml  # claims C-NN with status
├── facts/               # byte-anchored facts F-NNN.md + _INDEX.md
├── evidence/            # raw artifacts + _index.json (path + sha256)
├── runs/                # ledgers, worker status, heartbeat
├── blockers/            # failure-attribution records
└── CLAUDE.md            # workspace rules (generated)
```

</details>

<details>
<summary><strong>Toolchain by target</strong> — the `--type` you pick at init locks the HARD tier</summary>

**All types require the two HARD MCP servers** (`ghidra` +
`sequential-thinking` — commands in the MCP section below). Expand your
target:

<details>
<summary><strong>windows (PE32+ x86-64)</strong> — native Windows binaries</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `pefile` (Python) | `uv pip install pefile` |
| HARD | `die` (Detect It Easy) | `KUNGLAO_DIE` env or on PATH — [ntinfo.com](https://ntinfo.com) |
| HARD | `floss` (FLARE FLOSS) | per [flare-floss docs](https://github.com/mandiant/flare-floss) |
| HARD | Ghidra or IDA | one of them; see the MCP section below |
| HARD (T2/T3) | VMware + vmr-shell, or an ssh/docker channel | see [Bring your own environment](#bring-your-own-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device/VM-side binary, default port 1337 |

Windows T3 dynamic also uses the `x64dbg` MCP; `volatility` (memory
forensics) and the IDA-Pro MCP are optional — see the MCP manifest below.

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
| WARN | `apkid` | `uv pip install apkid` |
| WARN | `baksmali` | from [smali releases](https://github.com/baksmali/smali/releases) |

</details>

<details>
<summary><strong>web &amp; macos</strong> — lightweight toolchains by design</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `camoufox-reverse` MCP (web) | anti-detect Firefox for hook / trace / network capture (REQUIRED on web) |
| WARN | `docker` (web channel default) | Docker Desktop, or set `KUNGLAO_CHANNEL=ssh` explicitly |
| WARN | `lipo`, `otool`, `nm`, `codesign`, `xattr` (macOS) | Xcode Command Line Tools |
| WARN | `ghidra` MCP (macOS) | recommended — see the manifest below |

</details>

Dynamic work needs one execution channel (`KUNGLAO_CHANNEL`): `vmr`
(VMware — any guest OS, snapshot/revert is the irreplaceable value),
`ssh` (any ssh-reachable box), `docker`, `adb` — or `local` for
**static-only** work (the red line: never execute the sample on the host;
a dynamic task HARD-rejects on `local`).

</details>

---

## Bring your own environment

Dynamic debugging needs an execution control plane the agent can drive.
`KUNGLAO_CHANNEL` selects one of five first-class channels — use what your
environment already has; none is a degraded mode:

| Channel | What it drives | Prerequisites |
|---|---|---|
| `vmr` (default) | VMware VM, **any guest OS** — snapshot/revert workflows | vmr-shell skill; `KUNGLAO_VM_HOST` + ports 9876/1337 |
| `ssh` | Any ssh-reachable box: bare metal, cloud VM, Mac, remote docker host | key auth — the probe runs a real BatchMode `ssh ... true` |
| `docker` | Local or remote docker daemon | `docker version` green; optional `KUNGLAO_DOCKER_CONTAINER` |
| `adb` | Android emulator or real device | `adb devices` shows it; `adb forward tcp:1337 tcp:1337` for frida |
| `local` | **Static-only analysis on the host** | none — the red line below |

> **`local` red line:** local is for **static** work only — never execute,
> debug, or inject the sample on the host. Any dynamic requirement switches
> to `vmr`/`ssh`/`docker`/`adb`; init HARD-rejects a dynamic task on
> `local`.

Channel probes run only for dynamic tasks; ssh-channel execution flows
through the **ssh-mcp** control plane (`npm i -g ssh-mcp`), plain CLI ssh
as fallback.

---

## MCP servers

Single source of truth: `scripts/mcp_probe.py`; `kunglao-init` scaffolds a
workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is
never overwritten). Probe any time:

```bash
uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>
```

(exit 1 = HARD missing, 2 = WARN-only missing.) The full manifest:

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | required, all types | decompilation / static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | required, all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 dynamic | dynamic debugging (VM remote) | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | memory forensics | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | when IDA chosen | remote IDA analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android graph building | post-decompile knowledge graph | `claude mcp add gitnexus -- gitnexus mcp` |
| `ssh-mcp` | WARN | channel | ssh execution control plane | `claude mcp add ssh-mcp -- ssh-mcp` |
| `virustotal` | WARN | CTI | threat intel (family-attribution hypotheses) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `camoufox-reverse` | HARD | web | browser JS reversing (hooks / trace / network capture) — REQUIRED on web | ships with the plugin (`.claude-plugin/plugin.json mcpServers`) — enable the plugin; dep: `uv pip install camoufox-reverse-mcp` |

Workspace `.mcp.json` is generated by `kunglao-init` when missing; user
registrations above are for machines deployed per the kunglao docs.

---

## 🗓️ Roadmap

- Five-arm capability matrix (bare CC vs CC+warm-context vs kunglao cold/warm/no-recall) on the held-out corpus
- Registry admission for discovered arms — making novel methods dispatchable
- Cross-workspace memory: what works where, feature-keyed
- The blocked-path measurement corpus — quantifying discovery beyond history

---

## ❓ FAQ

**When does it stop?**
`CONVERGED` (exit 0): every primary question in `task_spec.yaml` has an
answer backed by a `PROVEN` fact, zero global contradictions, and the
completion transaction recomputes clean. Budget and wall-clock caps bound
the run; exhaustion counts as fail, never as silent success.

**What do the claim statuses mean?**
`OPEN` (not yet settled), `PARTIALLY-VERIFIED` (facts exist, no blind
sign-off yet), `PROVEN` (an independent verifier re-derived it blind and
the gates passed), `STAMP` (self-declared — never trusted as evidence). A
worker's own sign-off can only ever produce `STAMP`.

**What does the oracle verdict mean?**
A machine-checked decision against a quantified verification contract — a
named artifact, a mechanical criterion runnable with no LLM, and a
threshold. It is the only trusted currency in the system; the settlement
validator refuses to override it.

**How do I read a FAIL settlement?**
A FAIL emits a structured gap-note (decoy walls hit, evidence gaps, cost
overrun — machine signals only) next to the settled row. The same-unit
retry reads its predecessors' notes, so the next attempt attacks the named
gap instead of repeating attempt 1.

**What is PARK?**
The option-death estimator learns, per (obstacle-kind, method-family),
whether an investment arc is dead. A dead option is PARKed — down-weighted
out of sampling — never deleted; it revives when the state changes.

**The loop says BLOCKED — is it stuck?**
`BLOCKED` (exit 4) means every open claim is blocked. The loop runs
self-recovery on blockers; a SUSPECT/stale premise is auto-invalidated and
re-derived. Persistent blockers land in `blockers/` with failure
attribution — **read those records before adding budget**: the remedy for
a tooling gap (register the missing server / install the missing binary)
and for a dead method (the sampler already down-weights it) is cheaper
than more wall-clock.

**init HARD-rejected on a missing tool — what now?**
The error block names each missing item with its install line. Install,
then re-run the same init command (idempotent — it re-probes and
scaffolds only on PASS). For MCP servers the registration commands are in
the table above; verify with `mcp_probe.py` before re-running.

**A worker keeps timing out (TIMEOUT rows on the ledger).**
First read the act's artifacts: a TIMEOUT with facts banked is progress
(credit carries them) — usually the act just needs to be split smaller;
state the sub-goal so one claim ≈ one bounded attempt. A TIMEOUT with
zero artifacts on the same family repeatedly means the obstacle registry
should show the cause — fix the environment (VM reachability, frida
port, MCP server) rather than retrying.

**How do I see what the loop has learned?**
`uv run python scripts/winrate_curve.py <ws>` for the trend;
`runs/round-strategy.json` for the current strategy in force (method
lead, anti-hints, budget); `runs/posterior-store.jsonl` for the raw
posterior rows; `runs/q-cell-log.jsonl` for per-arm observations.

**How do I resume after a crash?**
`/kunglao-agent:resume <workspace>` (or `kunglao resume <workspace>`): a
read-only breakpoint brief — health, open claims, in-flight workers, crash
timeline — plus the next action. All state is on disk; no session context
required.

**Do I need a VM or MCP servers?**
Static-only tasks need no execution plane at all (`KUNGLAO_CHANNEL=local`).
Dynamic tasks require one of vmr/ssh/docker/adb. MCP-wise, all types
require `ghidra` + `sequential-thinking`; web additionally requires
`camoufox-reverse` (ships with the plugin). Probe:
`uv run python scripts/mcp_probe.py <ws> --type <type>`.

**My workspace predates a plugin update.**
`/kunglao-agent:upgrade <workspace>` migrates the scaffold (hooks,
templates, event vocab) forward; user data is never touched and byte
drift refuses with RC=4. A version mismatch refuses analysis until
upgraded.

**Where do facts and evidence live — can I trust them?**
`facts/F<NNN>.md` (byte-anchored, frontmatter contract) mapped to claims
by `claim-register.yaml`; every fact cites raw artifacts through
`evidence/_index.json` (path + sha256) and carries a `reproduce:`
command. `verifier_sign_off` on the fact names the independent check.

---

## 🔐 Safety

Authorized analysis only. You are responsible for defining and enforcing
the allowed scope; sandbox boundaries reduce risk but never replace host
isolation; the software is provided "AS IS".

---

## 🧪 Development

```bash
uv sync --locked        # locked env
uv run pytest -n 4      # local face; CI's integration tier is the authoritative full-suite entry
uv run ruff check .     # lint
```

CI gates every PR: hygiene ledgers (comment / silent-except / formal-code
markers), deploy-manifest consistency, unit + integration tiers — the
release-check workflow is the source of truth for every claim here.

---

## 📝 License

Dual-licensed: **AGPL-3.0** for personal, academic, and internal use (see
[LICENSE](LICENSE)); a commercial license is available for closed
distribution — contact the maintainer.
