# kunglao-agent

**kunglao-agent is an RLVR-driven reverse-engineering agent: an autonomous system that plans its own route through binary analysis, works for hours or days unattended, recovers from failures, and converges only when every answer survives a mechanical oracle verdict — every claim machine-checked, every verdict reproducible, the loop measures itself.**

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org) [![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/amd2g2zz/kunglao-agent/pulls)

**English** · [Simplified Chinese](README.zh-CN.md)

## What it is

kunglao-agent is an autonomous reverse-engineering system. You point it at a
target and state the questions; it plans its own route, dispatches specialist
workers, verifies every conclusion independently, and stops only when each
answer is settled by a mechanical check instead of a model's say-so.

The target spectrum is the full one: Windows/Linux native binaries, Android
APKs (including native `.so` layers), web/JS, protocol recovery, firmware —
static-first by design, driving whichever execution channel your environment
already has (VMware, ssh, docker, adb, or none at all for static-only work).

It currently runs inside [Claude Code](https://claude.com/claude-code) as a
plugin. Claude Code is the conversation surface; the product is the loop and
the fact base it produces.

## How it works

### The loop in plain terms

1. **You state the task.** Goal, verification logic, constraints — recorded in
   `task_spec.yaml`. The completion criterion (the **oracle**) is derived
   mechanically from what you state, so a vague task yields a vague oracle.
2. **The loop decomposes the goal into claims** (`C-NN`, a dependency DAG).
   Each tick runs a convergence check that decides the next action:
   dispatch a worker, dispatch a verifier, wait, self-recover, or stop.
3. **Specialist workers gather evidence** — byte-anchored facts written as
   `facts/F<NNN>.md`, each citing raw artifacts through
   `evidence/_index.json` (path + sha256) with a `reproduce:` command.
4. **An independent verifier re-derives every claim blind** (maker-checker):
   the verifier sees the raw evidence and the question, never the maker's
   conclusion. No sign-off, no `PROVEN`.
5. **Mechanical gates settle each claim.** The oracle verdict — a
   machine-checked decision against a quantified verification contract — is
   the only trusted currency. Settlements land on one append-only ledger
   with `rule_id` + evidence refs: every reward answers "where did this
   number come from".
6. **The loop learns from settlements** (RLVR — reinforcement learning from
   verifiable rewards, below) and **converges**: `CONVERGED` (exit 0) means
   every primary question has a verified answer, zero open contradictions,
   and a clean completion transaction — recomputed mechanically, never
   self-declared.

Long-horizon operation is a design goal: a heartbeat keeps the loop alive,
dead workers are replaced and their claims re-queued, crashes resume from
on-disk state (`resume`), and old workspaces migrate forward (`upgrade`).

### The learning loop (RLVR)

No human grades the output — the oracle verdict is the reward. The
statistical engine is **DTS (Discounted Thompson Sampling)**: Beta
posteriors per arm, discounted by a decay factor γ so recent outcomes weigh
more than old ones, with adaptive γ schedules. Sampling decides which claim
and which method family to try next; settlements fold back into the
posteriors. The package surface is [`scripts/rlvr/`](scripts/rlvr/) — one
import point, one export map.

| RLVR part | What kunglao does | Where |
|---|---|---|
| Reward | every claim is backed by oracle cases that are quantified verification contracts — a named artifact, a mechanical criterion (runnable with no LLM), a threshold. A semantic admission gate refuses fuzzy criteria and forces decomposition: "understood the protocol" bounces; "pair-match ≥ 11 of 14" banks | [`scripts/oracle_case_admission.py`](scripts/oracle_case_admission.py) |
| Sampling | DTS: adaptive-γ Beta posteriors per arm, one sample per dispatchable claim per tick; the case face ranks claims, the Q-cell face ranks (state, method) pairs | [`scripts/rlvr/posteriors.py`](scripts/rlvr/posteriors.py), [`scripts/rlvr/q_cells.py`](scripts/rlvr/q_cells.py), [`scripts/priority_ratio.py`](scripts/priority_ratio.py) |
| Kernel actuation | settlements fold into the posterior store; the learned state is composed into ONE round-strategy object per tick whose four outlets feed dispatch (method lead / anti-hints / budget), loop monitoring, hook cards, and parameter amendments — template sentences filled from named ledger rows, no model calls | [`scripts/rlvr/compose.py`](scripts/rlvr/compose.py), [`scripts/rlvr/strategy_store.py`](scripts/rlvr/strategy_store.py) |
| State | canonical discretized workspace states with a deterministic value anchor feed the Q cells; format-stamped workspaces carry their scaffold version on disk and `upgrade` migrates them forward without touching user data | [`scripts/rlvr/state.py`](scripts/rlvr/state.py), [`scripts/kunglao_upgrade.py`](scripts/kunglao_upgrade.py) |
| Obstacle attribution | intervention-born failure causes are recorded as obstacle objects (`runs/obstacles/`) and read into the state signature — attribution is evidence, never a verdict | [`scripts/rlvr/obstacles.py`](scripts/rlvr/obstacles.py) |
| Option-death termination | a learned "when to quit": Beta per (obstacle-kind, method-family) estimates whether an investment arc is dead; dead options are PARKed (down-weighted), never deleted | [`scripts/rlvr/termination.py`](scripts/rlvr/termination.py) |
| Terminal credit | at master-oracle-green closure, one settlement row back-references the enabling chain — which case-greens and claim settlements produced the closure — and case retrieval weights those lessons above mid-loop entries | [`scripts/terminal_settlement.py`](scripts/terminal_settlement.py) |
| Measurement | the replay ruler re-plays historical ledgers under alternative ranker configurations and reports deterministic time-to-converge | [`scripts/replay_ruler.py`](scripts/replay_ruler.py) |
| Settlement | every rollout banks through ONE append-only ledger; a deterministic rules table settles it and a validator enforces the walls — every cited evidence id must resolve (fail-closed), scores clamp to declared rails, and the oracle verdict is never overridable | [`scripts/rlvr/ledger.py`](scripts/rlvr/ledger.py), [`scripts/rlvr/reward.py`](scripts/rlvr/reward.py), [`scripts/rlvr/scalar.py`](scripts/rlvr/scalar.py) |
| Experience banking | per-round provenance credit (creator-attributed artifacts), tool-call journals, and state signatures extracted into experience triples `(s, a, r)` in a regenerable CSV, plus a read-only Q report of per-cell means | [`scripts/rlvr/triples.py`](scripts/rlvr/triples.py), [`scripts/tc_journal.py`](scripts/tc_journal.py) |
| Verification ladder | three verification tiers: on-write guards (T0), mid-round oracle probe batches debounced off the verified-write stream (T1), and a round-close priority queue over sides ordered by unblocking value (T2) | [`scripts/verification_ladder.py`](scripts/verification_ladder.py), [`scripts/oracle_cadence.py`](scripts/oracle_cadence.py) |
| Mainline decisions | every mainline decision lands on the rollout ledger as a `(s_M, A_M, ΔV)` row — state signature, closed action vocabulary, value delta from the deterministic anchor — recorded mechanically, idempotent | [`scripts/rlvr/state.py`](scripts/rlvr/state.py), [`scripts/verification_ladder.py`](scripts/verification_ladder.py) |
| Reflection | a FAIL settlement emits a structured gap-note (decoy walls hit, evidence gaps, cost overrun — derived from machine signals only); the same-unit retry dispatch reads what its predecessors hit, so attempt N is not a repeat of attempt 1 | [`scripts/gap_notes.py`](scripts/gap_notes.py) |
| Online distillation | a runtime shelf-miss triggers ONE budgeted distillation act: re-library retrieval first, then the web face; candidates run against the anchored sample bytes and land run-local; frequency is budget-governed, never prohibited | [`scripts/online_distill.py`](scripts/online_distill.py) |
| Distillation spine | all distilled knowledge banks through one spine pass with a source-trust gate — a product that skips a stage is refused loudly; reusable scripts harvested from workspaces join the library through the same discipline | [`scripts/distill_spine.py`](scripts/distill_spine.py), [`scripts/script_harvest.py`](scripts/script_harvest.py) |
| Feature-conditioned prior | an optional (flag-off) prior that conditions initial posteriors on workspace feature similarity — activation is gated on its own A/B replay evidence | [`scripts/rlvr/feature_prior.py`](scripts/rlvr/feature_prior.py) |

Vocabulary anchor: a **step** is a tick of the convergence loop; a **rollout**
is an engagement trajectory; an **episode** ends at master-green; an **option**
is an investment arc across claims.

## Case studies

Sanitized one-page battle reports — what the agent took on, the defense
surface it met, the route it walked, and the mechanical verdict:

- [Hardened Android native crackme](docs/cases/hardened-android-crackme.md) — 14 protection layers (CFF, self-modifying code, anti-hook/anti-emulation, encrypted constants, decoy lane); unattended run, 3/3 constants, 18/18 byte-exact replays.
- [Web request-signing recovery](docs/cases/web-request-signing.md) — a production signing scheme characterized end-to-end under obfuscation and anti-bot defenses, reproduced byte-exact including withheld exchanges.
- [Desktop agent license protocol](docs/cases/desktop-agent-license.md) — a challenge/response license handshake fully characterized and replayed byte-exact, with independent blind verification on every claim.

Each case also has a Chinese version alongside the English one under `docs/cases/`.

## Quick start

From a sample on disk to a verdict:

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

`kunglao-init` scaffolds the workspace, writes `CLAUDE.md`, probes the
toolchain for your `--type`, and scaffolds `.mcp.json`. It **HARD-rejects**
when a required tool for your type is missing — the fix guidance is in the
error block.

### 3. State the task and start the analysis

```
/kunglao-agent:analysis ~/cases/synth-dropper
> Goal: confirm this dropper's persistence mechanism and network endpoints;
>   every conclusion must be reproducible from raw evidence.
> Verification: key findings count only if an independent verifier re-derives
>   them blind and reaches the same answer.
> Constraints: static-first; never execute the sample on the host.
```

Write the brief so an independent reviewer could judge the result: **analysis
goal** (what you need to know), **verification logic** (what makes an answer
trustworthy), **constraints** (e.g. "no execution on the host"). Everything is
recorded in `task_spec.yaml`; from there the loop drives itself. For how the
common asks turn into well-formed statements, see
[Stating the task](#stating-the-task).

### 4. Read the deliverable

```
claim-register.yaml   # every claim terminal, with verifier sign-off
facts/F<NNN>.md       # byte-anchored, reproducible, frontmatter contract
evidence/_index.json  # every fact → raw artifact (sha256 + path)
runs/                 # session audit trail
```

## Stating the task

The loop derives its completion criterion — the **oracle** — mechanically
from the end-state you state. A vague statement yields a vague oracle, and
the analysis drifts toward whatever can be proven instead of what you
needed. Four phrasings cover most of that drift:

| You say | It usually means | The oracle anchors on |
|---|---|---|
| "我要纯算" — just the pure algorithm | offline reproduction of the signing/crypto routine (a unidbg harness or a rewrite) — not "analyze the app"; the app is only where the algorithm lives | byte-exact replay of every captured (input → sign) pair, including withheld ones, with no device or app at run time |
| "我要解密" — I want decryption | say which: (a) decrypt one captured body, or (b) a reusable decryption capability — algorithm + key | (a) the plaintext validates against what the app renders; (b) a canary round-trip byte-identical to device-produced ciphertext |
| "帮我分析这个协议" — analyze this protocol | wire-format recovery: framing, field semantics, a runnable codec | the codec round-trips every captured frame byte-exact, and a held-out frame decodes to fields matching observed app behavior |
| "这个 sign 在哪算的" — where is `sign` computed? | a location with proof | a named class/method/native function, plus a hook at that point reproducing the captured values |

What these have in common:

- **Name the sample and the behavior** — which parameter, entry, or flow —
  not the category. "我要纯算" is a category; "the signer producing the
  `sign` header on api.example.com/v2/*" is a target.
- **Success must be data.** Attach captured input/output pairs; the
  withheld pairs are what make the check honest — a reproduction cannot
  overfit data it never saw.
- **Constraints change the plan.** Static-only? A device available? Which
  channel? Say so up front — it decides the route before work starts (see
  [Bring your own environment](#bring-your-own-environment)).

## What a run looks like

A synthetic example: a small Windows dropper lands in `~/cases/synth-dropper`:

```bash
/kunglao-agent:init ~/cases/synth-dropper --type windows   # probes Ghidra, VM reachability
/kunglao-agent:analysis ~/cases/synth-dropper
> "What does this binary do, and where does it phone home?"
```

From there the loop runs itself — the route adapts to what the sample turns
out to be. You can walk away; dead workers are replaced and their questions
re-queued, and `/kunglao-agent:resume` rebuilds the picture from on-disk
state after any interruption. When it converges, read the deliverable above.

## Subcommands

| Command | Use when | What it does |
|---|---|---|
| `/kunglao-agent:init <workspace> [--type windows\|linux\|android\|web\|macos] [--lane malware\|algorithm\|protocol\|web\|data\|app]` | starting an engagement, first | scaffolds the workspace, probes the toolchain for the type, writes `CLAUDE.md` and `.mcp.json`; HARD-rejects with fix guidance when a required tool is missing |
| `/kunglao-agent:analysis <workspace>` (alias `analyze`) | after init — state the task and start | collects your goal / verification logic / constraints once, then runs the convergence loop: dispatch / verify cycles until the report |
| `/kunglao-agent:resume <workspace>` | after a crash, reboot, or any "where was I?" | read-only breakpoint brief (health, open claims, in-flight workers, crash timeline) plus the next action from the state machine |
| `/kunglao-agent:upgrade <workspace> [--dry-run]` | after a plugin update, on an older workspace | migrates the workspace scaffold (hooks, templates, event vocab) to the current plugin version; `--dry-run` previews; user data (claims, facts, evidence) is never touched — byte drift refuses with RC=4 |
| `/kunglao-agent:help` | anything else | prints the usage list |

Typical order: `init` creates the workspace → `analysis` states the task and
starts → (`resume` to pick the thread back up any time) → read the report at
convergence → `upgrade` old workspaces after plugin updates.

## CLI console scripts

`uv sync` in the repo root registers the router as the `kunglao` console
script: `kunglao --help` lists all nine subcommands — `decide`, `tick`,
`verify`, `record`, `health`, `resume`, `check-stale`, `upgrade`,
`analysis` — so every `kunglao <sub> <workspace>` invocation taught by the
skills works on PATH. Dedicated entries: `kunglao-init`, `kunglao-verify`,
`kunglao-upgrade`, `heartbeat-tick`, `convergence-check` (see
`[project.scripts]` in pyproject.toml; wrappers in `kunglao_agent_cli/` are
registration-only — targets stay `scripts/<file>.py`).

The reference end-to-end invocation (the gold-standard acceptance harness —
init → analysis → open loop → oracle on an eval unit, with every event
streamed to one unified audit trail at `<ws>/runs/logs/e2e-audit.jsonl`):

```bash
uv run --project . python scripts/e2e/run.py --unit py-derive-v1 --dry-llm
```

`--auto-llm` switches to real headless LLM execution; `--resume <run-id>`
picks up a partial run.

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
reproduce: uv run python -c "import struct; ..."               # runs against the cited artifact
verifier_sign_off: {verifier: kunglao-redteam, verdict: CONFIRMED}
```

No claim reaches `PROVEN` on its author's word: an independent verifier must
re-derive it blind, and a set of mechanical gates must pass. The full gate
design lives in [`docs/design/loop-engineering.md`](docs/design/loop-engineering.md).

Workers never hand-edit workspace YAML: registers and ledgers are edited
through [`scripts/ws_yaml.py`](scripts/ws_yaml.py) (dotted-path get/set/del
with round-trip validation — a write that does not round-trip is refused).

## Understanding the visuals

Two live faces turn a run into something you can watch.

**The win-rate curve** — rolling success rate over the settlement stream:

```bash
uv run python scripts/winrate_curve.py <workspace> [--window 5] [--html curve.html]
```

The x-axis is settlement order on the append-only ledger; the y-axis is the
pass rate over the rolling window (default 5). `--json` emits the
machine-readable face; `--html` writes a single-file chart. A healthy run
trends upward as the loop learns which cases and methods pay; a flat line at
zero says the ranker is spending budget on arms that never settle — check
the obstacle registry before adding budget.

**The statusline** — the live one-line HUD while the agent runs.
`scripts/statusline_snapshot.py` writes one snapshot
(`<ws>/runs/.kunglao-statusline.json`) per semantic event, and the renderer
(`statusline_render.mjs`, wired by kunglao-init) displays it with zero
spawning. What you see:

| Segment | Meaning |
|---|---|
| state glyph (`◈ analyzing` / `◇ tossing` / `○ idle` / `◌ stall` / `✖ DOWN` / `◉ flawless`) | the semantic state machine, precedence down > flawless > stall > toss > analyzing > idle; probe short codes (`[ledger]` `[hook]` `[stall]` `[audit]`) overlay which file to look at |
| `C<closed>/<total>` | claim progress (closed over total) |
| `wr` | current win rate |
| `R:` rank chip | which action the DTS sampler puts first right now, and how old that ranking is |
| health dots (×3) | oracle power / retro lag / detector liveness at a glance |
| task chip | who is working on what right now (`claim` + task phrase) |
| `v` sparkline | the last value-anchor points — is the workspace measurably progressing |

A stale-but-within-policy snapshot renders as idle (truthful: nothing
happened); beyond the liveness policy it renders DOWN.

## Evaluation and measured results

The capability dataset lives in [`eval/`](eval/README.md): constructed
targets with mechanical oracles and ground truth known by construction. A
run emits a `METRIC`/`VERDICT` stream and archives evidence-bar results rows.
Anti-memorization is by design: targets are constructed and seed-mutated;
checkers mint held-out probes the candidate never saw; and the eval corpus
is contractually excluded from any distillation source.

**Tiers.** The smoke tier (three constructed families, minutes-scale), the
release tier (native arm64/PE/x86-64, packed UPX, self-modifying code,
network license verification, request signing, web packing — difficulty
rungs L0 → L2(+L2p/L3)), the chain tier (2–6 nested protection layers), the
misdirection tier, and the tool-flex tier:

```bash
uv run python scripts/eval_smoke_runner.py --tier smoke               # self-check: reference candidates must green their oracles
uv run python scripts/eval_smoke_runner.py --tier smoke --baselines   # append the 1/k-guessing floor rows
```

Results land under `runs/eval-smoke/`. `--tasks <id,id>` scopes a run;
`--candidate-for <task_id>=<path>` plugs an external arm's artifacts into
the same checker.

**Control arm A/B** — bare LLM vs. the framework, one command:

```bash
uv run python scripts/eval_control_arm.py --ab --manifest bare-candidates.jsonl --framework-manifest framework-candidates.jsonl
```

Both arms read candidates from a `kunglao-eval-candidates/1` manifest
(`--live` drives prompt-only `claude -p` runs instead). Five metrics decide
it, per arm: `answer_rate`, `proven_with_evidence_rate`,
`premature_closure_rate`, `false_proven_rate`, and `budget`.

**Replay ruler** — offline ordering-quality measurement. Point it at a
completed workspace and it re-plays the historical ledger under alternative
ranker configurations, reporting deterministic time-to-converge per
configuration:

```bash
uv run python scripts/replay_ruler.py ~/cases/finished-engagement
```

The source workspace opens read-only; writes land in a sandbox.
`--configs-json` supplies the configuration set; `--with-events` adds the
λ epistemology check over historical rank events.

**Measured results** — the built-in 12-unit L1 eval matrix (static
reverse-engineering targets across JS, x86/ARM64 ELF, and Windows PE;
oracle-graded with a strict checker — byte-anchored deliverables only, no
partial credit, per-session caps of $15 / 3600s, pass@1):

| Runtime | pass@1 | Session cost |
|---|---|---|
| kunglao v0.1.5.post2 | 5/12 | ~$135 total (13 sessions) |
| kunglao v0.1.6 | **11/12** | ~$120 total across 4 governed iteration rounds |
| plain Claude Code (default harness, no plugin) | 12/12 | ~$11.4 total |

Methodology: identical harness for all rows (same runner, same checker, same
units); pass@1, k=1; exhausted counts as fail; harness-surface integrity
gate active; no runtime patching during measurement. Read honestly: the 12
units are single-session-tractable, and a frontier model with default tools
saturates them at the lowest cost — kunglao's differentiation is long-horizon
layered work, verification discipline (oracle + blind red-team on every
claim), and the dynamic lanes, not static single-session speed. The reward
path (settlement, validation, provenance credit, experience recording) is
live on every run; the learned-policy consumption path is gated behind its
own eval campaign so benchmarks keep measuring frozen behavior.

## Toolchain by target

The `--type` you pick at init locks which HARD-tier tools must be installed.
Guidance is collapsed — expand your target. **All types require two MCP
servers:** `ghidra`
(`claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe`) and
`sequential-thinking`
(`claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking`).

<details>
<summary><strong>windows (PE32+ x86-64)</strong> — native Windows binaries</summary>

| Tier | Tool | Install |
|---|---|---|
| HARD | `pefile` (Python) | `uv pip install pefile` |
| HARD | `die` (Detect It Easy) | `KUNGLAO_DIE` env or on PATH — [ntinfo.com](https://ntinfo.com) |
| HARD | `floss` (FLARE FLOSS) | per [flare-floss docs](https://github.com/mandiant/flare-floss) |
| HARD | Ghidra or IDA | one of them; see [Internals](#internals) |
| HARD (T2/T3) | VMware + vmr-shell, or an ssh/docker channel | see [Bring your own environment](#bring-your-own-environment) |
| HARD (T2/T3) | `frida-server` (renamed, custom port) | device/VM-side binary, default port 1337 |

Windows T3 dynamic also uses the `x64dbg` MCP; `volatility` (memory
forensics) and the IDA-Pro MCP are optional — see the MCP manifest under
[Internals](#internals).

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
| WARN | `ghidra` MCP (macOS) | recommended — see the manifest under [Internals](#internals) |

Init probes only the essentials for these types; heavier capabilities engage
when the target calls for them. macOS dynamic work uses the `ssh` channel
(to a Mac host); for the optional x64dbg browser-debug path, install the
Windows toolchain above.

</details>

Single manifest source for everything above — probe it any time:
`uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>`
(exit 1 = HARD missing).

## Bring your own environment

Dynamic debugging needs an execution control plane the agent can drive.
`KUNGLAO_CHANNEL` selects one of five first-class channels — use what your
environment already has; none is a degraded mode:

| Channel | What it drives | Prerequisites |
|---|---|---|
| `vmr` (default) | VMware VM, **any guest OS** — snapshot/revert workflows are its irreplaceable value | vmr-shell skill; `KUNGLAO_VM_HOST` + ports 9876/1337 |
| `ssh` | Any ssh-reachable box: bare metal, cloud VM, Mac, remote docker host | key auth — the probe runs a real BatchMode `ssh ... true` |
| `docker` | Local or remote docker daemon — `docker exec` is equivalent to any control path | `docker version` green; optional `KUNGLAO_DOCKER_CONTAINER` |
| `adb` | Android emulator or real device | `adb devices` shows it; `adb forward tcp:1337 tcp:1337` for frida |
| `local` | **Static-only analysis on the host** | none — see the red line |

> **`local` red line:** local is for **static** work only — never execute,
> debug, or inject the sample on the host. Any dynamic requirement switches
> `KUNGLAO_CHANNEL` to `vmr`/`ssh`/`docker`/`adb`; init HARD-rejects a
> dynamic task on `local`.

Channel probes run only for dynamic tasks (static-only tasks skip them).
`ssh`-channel execution flows through the **ssh-mcp** control plane
(`npm i -g ssh-mcp`); plain CLI ssh is the fallback. For remote docker over
ssh, set `KUNGLAO_DOCKER_CONTAINER`.

## Configuration

Four variables cover most setups:

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | unset | must stay unset or `0` — truthy values route dispatches through the teammate channel and are rejected |
| `KUNGLAO_CHANNEL` | `vmr` | dynamic execution control plane: `vmr` \| `ssh` \| `docker` \| `adb` \| `local` — see [Bring your own environment](#bring-your-own-environment) |
| `KUNGLAO_VM_HOST` | unset | VM/host for dynamic analysis (vmr-shell :9876, Frida :1337) |
| `GHIDRA_HOME` | unset | Ghidra install root (must contain `support/analyzeHeadless.bat`) |

Rarely needed: `KUNGLAO_DOCKER_CONTAINER` (docker execution target for the
`ssh`/`docker` channels), `KUNGLAO_FRIDA_PORT` (default 1337), `KUNGLAO_DIE`
(DIE path, falls back to PATH), `KUNGLAO_CLAUDE_JSON` (test override for the
user-level MCP registry).

## FAQ

**When does it stop?**
`CONVERGED` (exit 0): every primary question in `task_spec.yaml` has an
answer backed by a `PROVEN` fact, zero global contradictions, and the
completion transaction recomputes clean. Budget and wall-clock caps bound
the run; exhaustion counts as fail, never as silent success.

**What do the claim statuses mean?**
`OPEN` (not yet settled), `PARTIALLY-VERIFIED` (facts exist, no blind
sign-off yet), `PROVEN` (an independent verifier re-derived it blind and the
gates passed), `STAMP` (self-declared — never trusted as evidence). A
worker's own sign-off can only ever produce `STAMP`.

**What does the oracle verdict mean?**
A machine-checked decision against a quantified verification contract — a
named artifact, a mechanical criterion runnable with no LLM, and a
threshold. It is the only trusted currency in the system; the settlement
validator refuses to override it.

**How do I read a FAIL settlement?**
A FAIL emits a structured gap-note (decoy walls hit, evidence gaps, cost
overrun — machine signals only, advisory-marked) next to the settled row.
The same-unit retry reads its predecessors' notes, so the next attempt
attacks the named gap instead of repeating attempt 1.

**What is PARK?**
The option-death estimator learns, per (obstacle-kind, method-family),
whether an investment arc is dead. A dead option is PARKed — down-weighted
out of sampling — never deleted; its history stays on the ledger and it can
be revived when the state changes.

**The loop says BLOCKED — is it stuck?**
`BLOCKED` (exit 4) means every open claim is blocked. The loop runs
self-recovery on blockers; a SUSPECT/stale premise is auto-invalidated and
re-derived. Persistent blockers land in `blockers/` with failure attribution
— read those records before adding budget.

**How do I resume after a crash?**
`/kunglao-agent:resume <workspace>` (or `kunglao resume <workspace>`): a
read-only breakpoint brief — health, open claims, in-flight workers, crash
timeline — plus the next action from the state machine. All state is on
disk; no session context is required.

**Do I need a VM or MCP servers?**
Static-only tasks need no execution plane at all (`KUNGLAO_CHANNEL=local`).
Dynamic tasks require one of vmr/ssh/docker/adb. MCP-wise, all types require
`ghidra` + `sequential-thinking`; web additionally requires `camoufox-reverse`
(which ships with the plugin). Probe any time:
`uv run python scripts/mcp_probe.py <ws> --type <type>`.

**My workspace predates a plugin update.**
`/kunglao-agent:upgrade <workspace>` migrates the scaffold (hooks,
templates, event vocab) forward; user data is never touched and byte drift
refuses with RC=4. A version mismatch refuses to run analysis until
upgraded.

**How do I add an eval family?**
Create `eval/v1/tasks/<tier>/<family>/` with the four contract files:
`task.yaml` (schema `kunglao-eval-task/1`, with the three oracle anchors —
goal verbatim, success criterion, verification method), the constructed
`target/`, `ground_truth.json`, and a standalone `checker.py`. Any churn to
a used version mints a new version dir + changelog entry — never a silent
in-place mutation. The eval corpus is contractually excluded from
distillation sources (see [`eval/README.md`](eval/README.md)).

## Safety

- Samples never execute on the host — the `block_malware_exec` hook enforces
  it; dynamic work runs VM/container/device-only and requires per-session
  authorization.
- Ground truth hierarchy: raw artifact > local tool > sandbox > threat intel
  (CTI is a falsifiable hypothesis, never truth).
- Maker-checker: a worker never self-verifies; a verifier never reads the
  maker's conclusion.
- Bins, settings, and hooks are never committed; secrets are excluded from
  workspaces and the repo.

## Development

Contributions are welcome. Workflow: branch from `dev`, one branch per
change, PR back to `dev`.

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q
gh pr create --base dev
```

The authoritative full-suite entry is `uv run python -m pytest -q` (see
.github/workflows/release-check.yml).

Design documentation lives in `docs/` and `specs/`. See
[License](#license).

## Internals

<details>
<summary><strong>MCP supply (the full manifest)</strong></summary>

Single source of truth: `scripts/mcp_probe.py`; `kunglao-init` scaffolds a
workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is
never overwritten). Probe:
`uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android|web|macos>`
— exit 1 = HARD missing, 2 = WARN missing only.

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
| `camoufox-reverse` | HARD | web | browser JS reversing (hooks / trace / network capture) — REQUIRED on web | ships with the kunglao-agent plugin (`.claude-plugin/plugin.json mcpServers`) — enable the plugin; install dep: `uv pip install camoufox-reverse-mcp` |

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

kunglao hooks are wired at workspace level; your global
`~/.claude/settings.json` is never written.

</details>

---

## License

Dual-licensed: **AGPL-3.0** for personal, academic, and internal use (free —
see [LICENSE](LICENSE)); a **commercial license** is required for
closed-source or SaaS commercial use — see
[LICENSE-commercial.md](LICENSE-commercial.md).
