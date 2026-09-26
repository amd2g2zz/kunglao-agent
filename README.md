# kunglao-agent

**kunglao-agent is an RLVR-driven reverse-engineering agent: an autonomous system that plans its own route through binary analysis, works for hours or days unattended, recovers from failures, and converges only when every answer survives a mechanical oracle verdict — every claim machine-checked, every verdict reproducible, the loop measures itself.**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/amd2g2zz/kunglao-agent/pulls)

**English** · [Simplified Chinese](README.zh-CN.md)

## The RLVR route

kunglao-agent runs reinforcement learning from verifiable rewards (RLVR) over reverse-engineering work. No human grades the output: the **oracle verdict** — a machine-checked decision against a quantified verification contract — is the only trusted currency in the system. Everything else in the architecture exists to mint that currency honestly and to learn from it.

In plain terms, this is autonomous reverse engineering at engagement scale. Point it at a target and state the questions; it drives toward **binary vulnerability discovery, commercial algorithm recovery (ACE), and core-algorithm reproduction** — planning its own route, working for hours or days unattended, recovering from worker deaths, resuming after crashes, and stopping only when every answer is settled. The spectrum is the full one: Windows/Linux native binaries, Android APKs, web/JS, protocol recovery, firmware emulation — static-first by design, driving whichever execution channel you already have.

The loop, face by face:

| RLVR part | What kunglao does | Where |
|---|---|---|
| Reward | every claim is backed by oracle cases that are quantified verification contracts — a named artifact, a mechanical criterion (runnable with no LLM), a threshold. A semantic admission gate refuses fuzzy criteria and forces decomposition: "understood the protocol" bounces; "pair-match ≥ 11 of 14" banks | [`scripts/oracle_case_admission.py`](scripts/oracle_case_admission.py) |
| Policy surface | context: the evidence arrangement the model concludes from — claim DAG, case bank, instrument menu — assembled per dispatch | the workspace spine |
| Sampling | Thompson sampling: Beta posteriors per oracle case, one sample per dispatchable claim per tick; no phase switches, no count cliffs | [`scripts/priority_ratio.py`](scripts/priority_ratio.py) |
| State | format-stamped workspaces carry their scaffold version on disk; `upgrade` migrates old workspaces forward without touching user data | [`scripts/kunglao_upgrade.py`](scripts/kunglao_upgrade.py) |
| Terminal credit | at master-oracle-green closure, one settlement row back-references the enabling chain — which case-greens and claim settlements produced the closure — and case retrieval weights those lessons above mid-loop entries | [`scripts/terminal_settlement.py`](scripts/terminal_settlement.py) |
| Measurement | the replay ruler re-plays historical ledgers under alternative ranker configurations and reports deterministic time-to-converge | [`scripts/replay_ruler.py`](scripts/replay_ruler.py) |
| Settlement | every rollout banks through ONE append-only ledger; a deterministic rules table settles it and a validator enforces the walls — every cited evidence id must resolve (fail-closed), scores clamp to declared rails, and the oracle verdict is never overridable. Each settled row carries `rule_id` + evidence refs, so every reward answers "where did this number come from" | [`scripts/reward_settlement.py`](scripts/reward_settlement.py), [`scripts/scalar_settlement.py`](scripts/scalar_settlement.py) |
| Experience banking | per-round provenance credit (creator-attributed artifacts), tool-call journals, and state signatures — canonical discretized workspace states with a deterministic value anchor — extracted into experience triples `(s, a, r)` in a regenerable CSV, plus a read-only Q report of per-cell means | [`scripts/rollout_ledger.py`](scripts/rollout_ledger.py), [`scripts/experience_triples.py`](scripts/experience_triples.py), [`scripts/state_signature.py`](scripts/state_signature.py), [`scripts/tc_journal.py`](scripts/tc_journal.py) |
| Reflection | a FAIL settlement emits a structured gap-note (decoy walls hit, evidence gaps, cost overrun — derived from machine signals only, advisory-marked); the same-unit retry dispatch reads what its predecessors hit, so attempt N is not a repeat of attempt 1 | [`scripts/gap_notes.py`](scripts/gap_notes.py) |

Vocabulary anchor: a **step** is a tick of the convergence loop; a **rollout** is an engagement trajectory; an **episode** ends at master-green; an **option** is an investment arc across claims.

What makes it different, in one breath: every verdict is mechanical, every claim settles through machine-checked gates, and the loop measures itself — ordering quality, credit, and calibration are computed from ledgers, not asserted. Trust is enforced by machinery, not convention: no fact is `PROVEN` on its author's word (an independent verifier re-derives it blind from the raw artifact), every fact cites a sha256-indexed artifact through `evidence/_index.json`, and the worker who wrote a claim never checks it.

## Benchmarks and evaluation

The capability dataset lives in [`eval/`](eval/README.md): constructed targets with mechanical oracles and ground truth known by construction. A run emits a `METRIC`/`VERDICT` stream and archives evidence-bar results rows (schema `kunglao-eval-results/1`).

**Smoke tier — shipped today.** Three constructed families (`go-arx-v1`, `js-sign-v1`, `py-derive-v1`), minutes-scale:

```bash
python scripts/eval_smoke_runner.py --tier smoke               # self-check: the tier's reference candidates must green their oracles
python scripts/eval_smoke_runner.py --tier smoke --baselines   # append the 1/k-guessing floor rows
```

Results land under `runs/eval-smoke/`. `--tasks <id,id>` scopes a run; `--candidate-for <task_id>=<path>` plugs an external arm's artifacts into the same checker.

**Release tier — landing in v0.1.6** ([#332](https://github.com/amd2g2zz/kunglao-agent/issues/332)). Constructed families over the friction that matters — native (arm64/PE, stripped symbols, control-flow flattening), packed (genuine UPX), self-modifying code, network license verification, request signing — with seed-mutated modified-crypto (modified AES/SHA) as a cross-cutting core every family consumes. Difficulty rungs per family (L0 plain → L2, plus L2p UPX on Windows and an L3 VM-obfuscation rung on the web ladder). Same contract as the smoke tier (mechanical oracles, checker-minted probes, minutes-scale) and the same runner: it lands as the release tier of the eval ladder and runs through the same CLI surface.

**The control arm A/B** ([#236](https://github.com/amd2g2zz/kunglao-agent/issues/236)) — bare LLM vs. the framework, one command:

```bash
python scripts/eval_control_arm.py --ab --manifest bare-candidates.jsonl --framework-manifest framework-candidates.jsonl
```

Both arms read candidates from a `kunglao-eval-candidates/1` manifest (`--live` drives prompt-only `claude -p` runs instead). Five metrics decide it, per arm: `answer_rate`, `proven_with_evidence_rate`, `premature_closure_rate`, `false_proven_rate`, and `budget` (wall seconds, per-task TTC, tokens where the face provides them).

**The replay ruler** ([#294](https://github.com/amd2g2zz/kunglao-agent/issues/294)) — offline ordering-quality measurement. Point it at a completed workspace and it re-plays the historical ledger under alternative ranker configurations, reporting deterministic time-to-converge per configuration:

```bash
python scripts/replay_ruler.py ~/cases/finished-engagement
```

The source workspace opens read-only; writes land in a sandbox. `--configs-json` supplies the configuration set; `--with-events` adds the λ epistemology check over historical rank events.

**Anti-memorization by design.** Targets are constructed and seed-mutated; checkers mint held-out probes the candidate never saw, so digest-table copying fails; and the eval corpus is contractually excluded from any distillation source — the discipline lives in [`eval/README.md`](eval/README.md).

## Benchmarks

Measured on the built-in 12-unit L1 eval matrix: static reverse-engineering targets across JS, x86/ARM64 ELF, and Windows PE; oracle-graded with a strict checker — byte-anchored deliverables only, no partial credit, per-session caps of $15 / 3600s, pass@1.

| Runtime | pass@1 | Session cost |
|---|---|---|
| kunglao v0.1.5.post2 | 5/12 | ~$135 total (13 sessions) |
| **kunglao v0.1.6 (this release)** | **11/12** | ~$120 total across 4 governed iteration rounds |
| plain Claude Code (default harness, no plugin) | 12/12 | ~$11.4 total |

Reading the table honestly:

- v0.1.6 vs v0.1.5.post2 is a measured +6 units on identical harness, units, and caps (same runner, same checker, same oracle).
- The 12 units are single-session-tractable: a frontier model with default tools saturates them, and plain Claude Code does so at the lowest cost. kunglao's loop does not beat that ceiling on static single-session units — the remaining unit is budget-bound in loop mode, not capability-bound (documented).
- At a labeled higher cap ($30, wall unchanged), the remaining budget-bound unit passes: pass@1 = 12/12 with labeled higher-cap — the gap is an efficiency gap (cost per unit), documented as a v0.2 target.
- Where kunglao differentiates is not static single-session units. It is long-horizon layered work — the chain tier (2-6 nested protection layers) where both runtimes pass but kunglao's L3 passes were authored by specialist workers through claim decomposition — plus verification discipline (oracle + blind red-team on every claim) and the dynamic lanes (Android/Windows/Linux VM work) opening in v0.2.
- The reward path is banked end-to-end as of this release: settlement, validation, provenance credit, and experience recording are live on every run (see the Settlement / Experience banking / Reflection faces above). The consumption path — the Q-table read feeding dispatch decisions — is deliberately NOT wired in v0.1.6: benchmarks must measure frozen behavior, and the online loop lands as the v0.2 opening item with its own eval campaign. The banking means that data accrues from day one either way.

Methodology: identical harness for all rows (same runner, same checker, same units); pass@1, k=1; exhausted counts as fail; harness-surface integrity gate active; no runtime patching during measurement.

## Road to v0.2: the pi-agent migration

The headline direction: **v0.2 migrates kunglao fully onto the [pi agent stack](https://github.com/earendil-works/pi)** — the embeddable `pi-ai` (unified LLM API) and `pi-agent` core libraries — and kunglao ships as an **independent application**, not a Claude Code plugin. The full design lives in card [#319](https://github.com/amd2g2zz/kunglao-agent/issues/319).

**Why.** The harness is a first-order capability variable, not a shell around the real system. Claude Code carried v0.1.x and is retired at v0.1.6 — the last Claude Code release — on three counts:

- **Capability.** kunglao's dispatch loop pins a thin adapter surface — `run_session(model, system, context, tools) -> transcript + result` — so harnesses become pluggable backends and the loop is insulated from upstream churn.
- **Telemetry independence.** pi carries none.
- **Application independence.** kunglao is the application; users choose models through pi-ai providers.

**Adoption is measured, not asserted.** The migration lands only when the numbers clear:

| Gate | What counts |
|---|---|
| Smoke-tier equivalence | both harnesses on the same #299 tasks; a gap over 10 points fails |
| Replay equivalence | #294 TTC and order digests match across harnesses |
| Token footprint | beats the measured Claude Code baseline (~13.5K tokens/session) |
| Model freedom | a full run on a non-DeepSeek provider |

**Falsifiers are pre-committed.** If the pi footprint lands worse than Claude Code's, or the smoke-equivalence gap exceeds 10 points, or upstream churn breaks the adapter twice inside the window — the dsh/codex fallback re-opens. The gates are the smoke tier and the replay ruler documented above; you can run them yourself.

**v0.2 also ships the workbench** ([#320](https://github.com/amd2g2zz/kunglao-agent/issues/320)): web and TUI over one shared view-model contract. The JSONL ledger/event spine already exists, so one model layer renders twice — TUI first (pi-tui, zero-dependency reach into analysis VMs), web second (claim DAG graphs, TTC curves, fleet view).

What carries over untouched: the oracle machinery, the ledgers, the gates-as-CLI, and the workspace spine are harness-neutral files and CLIs by construction.

## Quick start

kunglao-agent runs inside Claude Code. From a sample on disk to a verdict:

| Tool | Why | Install |
|---|---|---|
| **Claude Code** | where kunglao-agent runs | per Anthropic docs |
| **Python 3.10+** (Python 2 is not supported) | the plugin carries a pinned env via `uv`; you do not touch it | system or `uv`-managed |
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

Write the brief so an independent reviewer could judge the result: **analysis goal** (what you need to know), **verification logic** (what makes an answer trustworthy — e.g. "the signature must be reproducible from the same inputs"), **constraints** (e.g. "no execution on the host"). Everything is recorded in `task_spec.yaml`; from there the loop drives itself. For how the common asks turn into well-formed statements, see [Stating the task](#stating-the-task).

### 4. Read the deliverable

```
claim-register.yaml   # every claim terminal, with verifier sign-off
facts/F<NNN>.md       # byte-anchored, reproducible, frontmatter contract
evidence/_index.json  # every fact → raw artifact (sha256 + path)
runs/                 # session audit trail
```

## Stating the task

The loop derives its completion criterion — the **oracle** — mechanically from the end-state you state. A vague statement yields a vague oracle, and the analysis drifts toward whatever can be proven instead of what you needed. Four phrasings cover most of that drift:

| You say | It usually means | The oracle anchors on |
|---|---|---|
| "我要纯算" — just the pure algorithm | offline reproduction of the signing/crypto routine (a unidbg harness or a rewrite) — not "analyze the app"; the app is only where the algorithm lives | byte-exact replay of every captured (input → sign) pair, including withheld ones, with no device or app at run time |
| "我要解密" — I want decryption | say which: (a) decrypt one captured body, or (b) a reusable decryption capability — algorithm + key | (a) the plaintext validates against what the app renders; (b) a canary round-trip byte-identical to device-produced ciphertext |
| "帮我分析这个协议" — analyze this protocol | wire-format recovery: framing, field semantics, a runnable codec | the codec round-trips every captured frame byte-exact, and a held-out frame decodes to fields matching observed app behavior |
| "这个 sign 在哪算的" — where is `sign` computed? | a location with proof | a named class/method/native function, plus a hook at that point reproducing the captured values |

A well-formed statement for the first case:

```
> Sample: the v7.2 APK; behavior: the signer producing the `sign`
>   header on api.example.com/v2/* requests.
> Criterion: a standalone reproduction (unidbg or rewrite) replays
>   every captured (input → sign) pair byte-exact — including the
>   withheld pairs — with no device or app at run time.
> Attach: captures/sign-pairs.jsonl — 20 input/output pairs captured
>   from a live session; 10 of them withheld from the analysis.
```

What these have in common:

- **Name the sample and the behavior** — which parameter, entry, or flow — not the category. "我要纯算" is a category; "the signer producing the `sign` header on api.example.com/v2/*" is a target.
- **Success must be data.** Attach captured input/output pairs; the withheld pairs are what make the check honest — a reproduction cannot overfit data it never saw.
- **The oracle is derived from your stated end-state.** Vague statement, vague verification, drifting analysis.
- **Constraints change the plan.** Static-only? A device available? Which channel? Say so up front — it decides the route before work starts (see [Bring your own environment](#bring-your-own-environment)).

## What a run looks like

*The shape of an engagement — what you type, what comes back, where to look.* A synthetic example: a small Windows dropper lands in `~/cases/synth-dropper`:

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # probes Ghidra, VM reachability
/kunglao-agent:analysis ~/cases/synth-dropper
> "What does this binary do, and where does it phone home?"
```

From there the loop runs itself — the route adapts to what the sample turns out to be. You can walk away; dead workers are replaced and their questions re-queued, and `/kunglao-agent:resume` rebuilds the picture from on-disk state after any interruption. When it converges, read the deliverable below.

## Subcommands

| Command | Use when | What it does |
|---|---|---|
| `/kunglao-agent:init <workspace> [--type windows\|linux\|android\|web\|macos] [--lane malware\|algorithm\|protocol\|web\|data\|app]` | starting an engagement, first | scaffolds the workspace, probes the toolchain for the type, writes `CLAUDE.md` and `.mcp.json`; HARD-rejects with fix guidance when a required tool is missing |
| `/kunglao-agent:analysis <workspace>` (alias `analyze`) | after init — state the task and start | collects your goal / verification logic / constraints once, then runs the convergence loop: dispatch / verify cycles until the report |
| `/kunglao-agent:resume <workspace>` | after a crash, reboot, or any "where was I?" | read-only breakpoint brief (health, open claims, in-flight workers, crash timeline) plus the next action from the state machine |
| `/kunglao-agent:upgrade <workspace> [--dry-run]` | after a plugin update, on an older workspace (or when the upgrade prompt says the stamp is behind) | migrates the workspace scaffold (hooks, templates, event vocab) to the current plugin version; `--dry-run` previews; user data (claims, facts, evidence) is never touched — byte drift refuses with RC=4 |
| `/kunglao-agent:help` | anything else | prints the usage list |

Typical order: `init` creates the workspace → `analysis` states the task and starts → (`resume` to pick the thread back up any time) → read the report at convergence → `upgrade` old workspaces after plugin updates.

## Reading the deliverable

A claim register and fact base where trust is mechanical, not conventional:

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

No claim reaches `PROVEN` on its author's word: an independent verifier must re-derive it blind, and a set of mechanical gates must pass. The full gate design lives in [`docs/design/loop-engineering.md`](docs/design/loop-engineering.md).

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
<summary><strong>web &amp; macos</strong> — lightweight toolchains by design</summary>

| Tier | Tool | Install |
|---|---|---|
| WARN | `camoufox-reverse` MCP (web) | anti-detect Firefox for hook / trace / network capture |
| WARN | `docker` (web channel default) | Docker Desktop, or set `KUNGLAO_CHANNEL=ssh` explicitly |
| WARN | `lipo`, `otool`, `nm`, `codesign`, `xattr` (macOS) | Xcode Command Line Tools |
| WARN | `ghidra` MCP (macOS) | recommended — see the manifest under [Internals](#internals) |

Init probes only the essentials for these types; heavier capabilities engage when the target calls for them. macOS dynamic work uses the `ssh` channel (to a Mac host); for the optional x64dbg browser-debug path, install the Windows toolchain above.

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

The authoritative full-suite entry is `python -m pytest -q` (see .github/workflows/release-check.yml).

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
| `camoufox-reverse` | WARN | web | browser JS reversing (hooks / trace / network capture) | `claude mcp add camoufox-reverse -- python -m camoufox_reverse_mcp` |

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
