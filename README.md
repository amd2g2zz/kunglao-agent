# kunglao-agent

A Claude Code skill that runs a convergence-driven reverse-engineering loop: it takes a malware sample to a byte-proven, independently-verified fact base, enforced by mechanical gates.

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.10%2B-blue)](.) [![license](https://img.shields.io/badge/license-MIT-lightgrey)](.)

---

## What this is

kunglao-agent is a Claude Code skill for malware reverse engineering. You drop a sample into a workspace, say what you need to know, and the skill runs a convergence loop: specialist workers analyze (static first), an independent verifier re-derives every fact blind from raw evidence, and mechanical gates decide when the analysis is done. The deliverable is a fact base where every claim is byte-anchored, independently verified, and evidence-indexed — trust is enforced by machinery, not convention.

The only interface is Claude Code: you talk to it and read its reports. The Python modules in this repo are the skill's internal organs, called by hooks, agents, and CI — documented under [Internals](#internals) for developers who extend the system, not as a user interface.

## Prerequisites

- **Python 3.10+ and [uv](https://docs.astral.sh/uv)** — hooks never invoke bare `python`: on machines where `python` resolves to Python 2.x every registered hook dies with the interpreter (#389). All hook commands run via `uv run --project <skill_root>`. **Python 2 is not supported.**
- **`uv sync --locked`** — restore the pinned project venv before anything else (see [Quick start](#quick-start)).
- **Ghidra or IDA** — one static-analysis suite for decompilation.
- **A VM** — required for T3 dynamic analysis (Windows / Linux / Android guest, matching the sample's project type). Samples never run on the host.
- **MCP servers** — registered by `kunglao-init` (ghidra, sequential-thinking, x64dbg, ...); see the MCP supply table under [Internals](#internals).

## Quick start

### 1. Install

kunglao-agent is a **single-skill plugin**: the skill's `SKILL.md` lives at the repository root (the single-skill plugin layout), so installing the plugin IS installing the skill — invoked as `/kunglao-agent`. The repo carries `.claude-plugin/plugin.json` (identity manifest: name, description, version `0.1`). The per-workspace machinery (hooks, gates, router CLIs) is wired by `kunglao-init` into each analysis workspace during initialization, not by plugin component wiring (that migration is tracked in #364).

**Recommended — marketplace install** (v0.1 ships `.claude-plugin/marketplace.json`; the marketplace resolves the repo's default branch, so the release tag must exist there). From any directory, in Claude Code:

```
/plugin marketplace add amd2g2zz/kunglao-agent
/plugin install kunglao-agent@kunglao-agent
```

**Alternative A — direct plugin load** (development, testing, or no marketplace):

```
claude --plugin-dir /path/to/kunglao-agent
```

The plugin manager lists `kunglao-agent` at version `0.1`.

**Alternative B — skills-directory clone** (legacy path; plain-skill identity, no plugin manager). In Claude Code:

```
/install-github-repo amd2g2zz/kunglao-agent
```

or, manually:

```bash
git clone https://github.com/amd2g2zz/kunglao-agent.git ~/.claude/skills/kunglao-agent
cd ~/.claude/skills/kunglao-agent
uv sync --locked
cp agents/kunglao-worker.md agents/kunglao-redteam.md ~/.claude/agents/
```

### 2. Initialize a workspace

One fresh workspace per sample engagement:

```bash
uv run --project <repo> <repo>/scripts/kunglao-init.py <workspace> --type windows   # or linux | android
```

Options: `--skip-toolchain` (skip the toolchain preflight — test/ops escape hatch), `--no-mcp` (skip the workspace `.mcp.json` scaffold), `--install-git-hooks` (install the review-gate pre-commit hook), `--force` (re-init after backing up the claim register).

Init exit codes (documented RC contract, #414): `0` success/resume, `1` generic error (usage error / template defect), `2` post-init idempotency verify failed, `3` agent-teams flag reject (unset `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` and restart the session), `4` toolchain HARD FAIL — human must install the missing tools, `5` no sample in `bins/`. Branch on the exit code, never on stderr text.

Init confirms the project type, scaffolds the workspace, writes the type-appropriate `CLAUDE.md`, and runs per-type toolchain probes (Android: ADB + rooted device + renamed frida-server on a custom port; Linux: Ghidra-or-IDA + remote debugger; Windows: Ghidra-or-IDA + VM). Hard failures are reported with root-cause guidance; a workspace that is not initialized is refused work.

### 3. Start the session

In Claude Code, in the workspace directory:

```
/kunglao-agent
```

`/kunglao-agent` with no arguments prints the command menu and waits for a
subcommand — it never silently runs. The subcommands are documented in the
[Command Reference](#command-reference) below. Alternatively, just describe
the task — the skill auto-triggers on phrases like *"analyze this sample"* /
*"分析这个样本"* / *"不收敛"*. The skill then runs the loop and delivers the
report; you monitor through conversation.

## Command Reference

Every `/kunglao-agent` command, its arguments, and an example:

| Command | Arguments | Purpose | Example |
|---|---|---|---|
| `/kunglao-agent` | `init <ws>` / `analysis <ws>` / `help` | command menu — with no args prints the menu and waits; unknown subcommands print the menu + `unknown: <x>` | `/kunglao-agent` |
| `/kunglao-agent:init` | `<workspace> [--type windows\|linux\|android]` | initialize a workspace (scaffold + CLAUDE.md + sample mount + task_spec intake + hooks) | `/kunglao-agent:init ~/cases/synth-dropper --type windows` |
| `/kunglao-agent:analysis` | `<workspace>` | enter the convergence loop on an initialized workspace | `/kunglao-agent:analysis ~/cases/synth-dropper` |
| `/kunglao-agent:help` | none | print the subcommand usage list | `/kunglao-agent:help` |

The namespaced form (`/kunglao-agent:init`) is the plugin-manager surface;
the main skill also accepts the subcommand form (`/kunglao-agent init <ws>`).

## A worked analysis case

*The walkthrough below is a representative, synthetic session on a small, deliberately simple sample. It shows the shape of an engagement, not a measured result — for measured outcomes see [Real-world results](#real-world-results).*

**Setup.** A small Windows dropper lands in `~/cases/synth-dropper`. The operator initializes the workspace:

```
uv run --project ~/kunglao-agent ~/kunglao-agent/scripts/kunglao-init.py ~/cases/synth-dropper --type windows
```

`kunglao-init` scaffolds the workspace, writes the workspace `CLAUDE.md`, probes the toolchain (Ghidra present, VM reachable), and scaffolds `.mcp.json`. The operator runs `/kunglao-agent` and states the task: *"what does this binary do, and where does it phone home?"*

**The loop.** The orchestrator opens `task_spec.yaml` with the primary questions (capability, persistence, network). Each tick is one mechanical decision:

1. `DISPATCH` — a static worker is dispatched first with an explicit contract (`[T1 tools=pe_analyze,strings-classify] claim C-001`). It writes facts: PE structure, imports mapped to capability classes, embedded strings, overlay scan.
2. `DISPATCH_VERIFIER` — for each fact, the redteam verifier re-derives the answer blind from the raw artifact (never reading the maker's conclusion) and signs off `CONFIRMED`; the fact reaches `PROVEN`.
3. `SATURATED` / `BLOCKED` ticks poll stuck workers or resolve blockers — the loop never idles with open claims.
4. `CONVERGED` — every primary question answered with byte-proof, zero orphan claims. The loop exits 0 and builds the report.

**Deliverables.** `claim-register.yaml` (every claim terminal), `facts/` (each fact byte-anchored, with provenance and a reproduce command), `evidence/_index.json` (every fact traceable to a raw artifact), and the final report. Every tick is recorded as a ledger line in `runs/` — the session's audit trail.

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

## Analysis principle

Five layers, in order of preference — static first, escalate only when the layer above is genuinely insufficient:

1. **Static closure** — complete the analysis statically if at all possible; a task that closes statically never touches dynamic tooling.
2. **Deobfuscation via emulation** — emulated execution strips obfuscation (opaque predicates, indirect jumps, computed constants, encoded blobs) and feeds the result back into static analysis. This serves static; it is not a replacement.
3. **Debug to fill declared gaps** — dynamic debugging (x64dbg / gdbserver / frida) is a complement, not a default: each T2/T3 dispatch must declare the static gap it addresses.
4. **Emulation fallback** — when static + debug data are complete but the logic still resists (e.g. black-box crypto), a hybrid frida-hook + unidbg emulation is used, gated on all three: frida data collected, ida/ghidra decompilation done, still stuck.
5. **Environment construction** — the worst case: build/patch an environment (matching OS version, re-signed APK, sandbox, JNI environment) so the sample runs completely and is observable end to end.

## Real-world results

- **NewSteamValve CDK scam dropper (2026-06-10)** — 601 imports / 16 DLLs mapped to 18 capability classes; 7198 functions / 2144 callgraph edges; 6 sections (no RWX, no overlay); 4143 obfuscated strings decoded (`XOR key=index+0x4d`); 7-stage killchain; verdict **MALICIOUS (9/12)** on 19 independently-verified facts.
- **Numeric-fidelity enforcement (C-020 incident)** — a report collapsed a disassembly count's basis ("811 8-byte ELF slots / 774 Ghidra records, 37 LDDW folded" → "774") and mislabeled 70 `BPF_CALL` as 70 helper calls. The fix: every numeric fact declares its `unit:` basis; `handoff-check.py --anchors` and `manual_audit.py` reject anchors that drop it.
- **Tool-first enforcement (C-022 test)** — a worker given an encrypted blob with zero hints hand-rolled a decode script; after the `toolfirst` gate landed, the same-shaped worker discovered `crypto-tool` via `tools/_INDEX.yaml` during its plan phase and ran the registered CLIs, documenting negative results per algorithm.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `0` | MUST stay `0`/unset — truthy values route dispatches through the teammate channel (rejected by `env_check_gate`) |
| `KUNGLAO_VM_HOST` | unset | VM lease host for dynamic analysis (vmr-shell :9876 / Frida :1337) |
| `GHIDRA_HOME` | unset | Ghidra install root (`support/analyzeHeadless.bat` under it) |

## Internals

The tool shelf: reusable analysis logic is absorbed as **registered tools** (machine contract `tools/_INDEX.yaml`, validated by `tools/validate_index.py`; human indexes `tools/_index-<category>.md`). Workers must check the index before writing new scripts (`toolfirst` gate); `tools/tool-search.py` queries it by capability tag and cost budget.

| Category | Tools |
|---|---|
| `crypto` | `crypto-tool` — 8 algorithms, stdlib-only: `chacha` (RFC + non-RFC), `xor-add`, `rolling-xor`, `lzss`, `lzma-raw`, `rsa-unpad`, `go-byte-transform`, `va-to-off`; all support `--reproduce` |
| `ghidra` | 5 analyzeHeadless postScripts: recon / decompile-functions / vtable-struct / evidence-annotations / scan-pointer |
| `static` | disasm-constant-check + syscall / stack-strings / overlay / PE / shellcode scanning CLIs |
| `pipelines` | `build-evidence-index` — evidence index builder (evidence/_index.json + _INDEX.md) |
| `aux` | legacy-PROVEN audit / golden capture / blind-coverage / cold-start metrics |

Host emulation (T2) is deliberately NOT a shelf tool: qiling-based emulation is provided by the external `/malware-framework` skill, which kunglao workers invoke per the analysis principle instead of re-wrapping qiling.

MCP supply: the single manifest source is `scripts/mcp_probe.py`; `kunglao-init` scaffolds a workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is never overwritten). Probe: `uv run python scripts/mcp_probe.py <ws> --type <windows|linux|android>` (exit 1 = HARD missing, 2 = WARN missing only).

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | required, all types | Ghidra decompilation/static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | required, all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `x64dbg` | HARD | Windows T3 dynamic | dynamic debugging (VM remote) | `claude mcp add x64dbg -- x64dbg-automate-mcp` |
| `volatility` | WARN | Windows T3 | memory forensics | `claude mcp add volatility -- python <path>/volatility_mcp_server.py` |
| `ida-pro-vm` | WARN | when IDA chosen | remote IDA analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `gitnexus` | HARD | Android graph building | post-decompile knowledge graph | `claude mcp add gitnexus -- gitnexus mcp` |
| `virustotal` | WARN | CTI | threat intel (family-attribution hypotheses) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |

Trust gates (the components behind "verified"):

| Gate | Enforces |
|---|---|
| `blind_gate` | `PROVEN` requires independent BLIND verifier sign-off; self-sign rejected |
| `provenance_gate` | facts cite indexed raw artifacts, not derived summaries |
| `convergence_completeness` | `CONVERGED` requires all primary questions terminal + zero orphan claims |
| `convergence_health` | SPINNING flatline detection (count-based, cannot be flooded) |
| `handoff-check.py --anchors` | report anchors preserve the exact numeric counting basis of facts |
| `review_gate.py` | repo commits require ≥1 independent reviewer + HMAC-signed evidence |
| `env_check_gate` | hard-rejects dispatch while the agent-teams flag is truthy |

Workspace layout (one workspace per sample engagement):

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

## Development

SDD (OpenSpec) + TDD: one issue → one PR → one branch → one worktree, merged to `dev` then `master`. Every commit requires ≥1 independent reviewer sign-off minted through `review_gate.py` (HMAC).

```bash
git worktree add .worktrees/<name> -b <name> dev
uv sync --locked
uv run python -m pytest -q                    # RED → GREEN → refactor
uv run python scripts/release_receipt.py --check
gh pr create --base dev
```

The release contract is revision-owned: `pyproject.toml` + `uv.lock` (pinned deps), `release-manifest.yaml` (declared asset inventory), `release_receipt.py` (observed inventory: per-asset sha256, CLI `--help` exit codes, test results). CI runs it on every PR. Depth lives in `docs/` (design, loop engineering), `specs/`, and `AGENTS.md`.

## Limitations

- 46 legacy `PROVEN` claims audited (10 have-raw / 18 derivation-only / 19 unverifiable) — re-verification is follow-up work
- ICD-203 conformance is partial (tradecraft #1/#2/#5/#8/#9; full certification out of scope)
- Dynamic analysis requires per-session authorization; sample execution is VM-only, host execution is blocked by a hook
- Type-aware init (Windows/Linux/Android toolchain matrix) and the remaining script-absorption batch are in development (issues #304, #278)

## Safety

- Samples never execute on the host — `block_malware_exec` hook enforces; VM-only via `vmr-shell`
- Bins / settings / hooks never committed; secrets excluded
- Ground truth hierarchy: raw artifact > local tool > sandbox > CTI (CTI is falsifiable claim, never truth)
- Maker-checker: a worker never self-verifies; a verifier never reads the maker's conclusion

## License

MIT
