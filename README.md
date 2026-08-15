# kunglao-agent

A Claude Code skill that runs a convergence-driven reverse-engineering loop: it takes a malware sample to a byte-proven, independently-verified fact base, enforced by mechanical gates.

[![release-check](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml/badge.svg)](https://github.com/amd2g2zz/kunglao-agent/actions/workflows/release-check.yml) [![python](https://img.shields.io/badge/python-3.11%2B-blue)](.) [![license](https://img.shields.io/badge/license-MIT-lightgrey)](.)

---

## Interface

**The only interface is Claude Code.** kunglao-agent is not a CLI with an agent wrapper — it is a skill. You do not type python commands; you talk to Claude Code and read its reports. Everything mechanical (convergence decisions, dispatch gates, verification, environment checks) runs inside the skill: hooks invoked by Claude Code, subagents dispatched by Claude Code, artifacts written to the workspace.

The python modules in this repo are the skill's internal organs — called by hooks, agents, and CI. They are documented under [Internals](#internals) for developers who extend the system, not as a user interface.

## Quick start

### 1. Install

Two paths ship with v0.1 (the repo carries `.claude-plugin/plugin.json`, version `0.1.0`, identity metadata only).

**(a) Plugin install** — load the repo directly as a Claude Code plugin:

```
claude --plugin-dir /path/to/kunglao-agent
```

The plugin manager lists `kunglao-agent` at version `0.1.0`. The manifest declares no components (skills/hooks/commands) yet — the full plugin migration, including marketplace distribution via `/plugin marketplace add amd2g2zz/kunglao-agent` (which additionally requires shipping `.claude-plugin/marketplace.json`), is tracked in #364.

**(b) Skill-dir install (legacy)** — in Claude Code:

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

A skills-dir clone that keeps `.claude-plugin/` loads as a skills-directory plugin (`kunglao-agent@skills-dir`) from the next session instead of a plain skill; bare `/kunglao-agent` still resolves via the loader fallback. Delete `.claude-plugin/` after cloning to keep the plain-skill identity.

### 2. Start analysis

In Claude Code, in a fresh workspace directory, either:

```
/kunglao-agent
```

or just describe the task — the skill auto-triggers on phrases like *"analyze this sample"* / *"分析这个样本"* / *"不收敛"*.

The skill then does the rest on its own:

1. **Initialize the workspace** — an init subagent confirms the project type (Windows / Linux / Android; explicit statement beats sample-magic sniffing beats interactive confirmation), scaffolds the workspace, writes the type-appropriate CLAUDE.md, and runs the per-type minimum toolchain probes (Android: ADB + rooted device + renamed frida-server on a custom port + GitNexus; Linux: Ghidra-or-IDA + remote debugger; Windows: Ghidra-or-IDA + VM). Hard failures are reported with root-cause guidance; a workspace that is not initialized is refused work.
2. **Run the convergence loop** — dispatch specialist workers (static first), verify their facts blind, loop until `CONVERGED`.
3. **Deliver the report** — a fact base where every claim is byte-anchored, independently verified, and evidence-indexed.

While it runs, you monitor through conversation — ask the skill for status, or let it report. Workers surface as status lines; the final deliverable is the verified fact base.

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

Dispatch carries an explicit contract — `[T1 tools=grep,xxd] claim C-007 <task>` — enforced by the `worker_budget` hook: ≤3 concurrent workers, per-claim cap, tier gate (T1 static / T2 emulation / T3 VM), live heartbeat, plan-with-content, `facts-snapshot:` marker, `tool-catalog:` marker when the task matches a registered tool, and a declared static-gap list for T2/T3 work. The agent-team channel is mechanically rejected.

## Analysis principle

Five layers, in order of preference — static first, and only escalate when the layer above is genuinely insufficient:

1. **Static closure** — complete the analysis statically if at all possible; a task that closes statically never touches dynamic tooling.
2. **Deobfuscation via emulation** — symbolic/emulated execution strips obfuscation layers (opaque predicates, indirect jumps, computed constants, encoded blobs) and feeds the result back into static analysis. This serves static; it is not a replacement.
3. **Debug to fill declared gaps** — dynamic debugging (x64dbg / gdbserver / frida) is a complement, not a default: it is used only for gaps static analysis (after deobfuscation) cannot close, and each T2/T3 dispatch must declare the static gap it addresses.
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

The tool shelf: reusable analysis logic is absorbed as **registered tools** (machine contract `tools/_INDEX.yaml`, validated by `tools/validate_index.py`; human indexes `tools/_index-<category>.md`).

| Category | Tools |
|---|---|
| `crypto` | `crypto-tool` — 8 algorithms, stdlib-only: `chacha` (RFC + non-RFC), `xor-add`, `rolling-xor`, `lzss`, `lzma-raw`, `rsa-unpad`, `go-byte-transform`, `va-to-off`; all support `--reproduce` |
| `ghidra` | 5 analyzeHeadless postScripts: recon / decompile-functions / vtable-struct / evidence-annotations / scan-pointer |
| `static` | disasm-constant-check + syscall / stack-strings / overlay / PE / shellcode scanning CLIs |
| `pipeline` | evidence-index builders + plan recipes (stage-unpack / crypto-decrypt / syscall-chain / iat-chain / go-recovery) |
| `aux` | legacy-PROVEN audit / golden capture / blind-coverage / cold-start metrics |

Host emulation (T2) is deliberately NOT a shelf tool: qiling-based emulation is provided by the external `/malware-framework` skill (90+ profile-driven stubs, verified on real x86/x64 samples) — kunglao workers invoke it per the analysis principle's emulation layers instead of re-wrapping qiling.

Tool selection is deterministic: `tools/tool-search.py` queries the machine index (`tools/_INDEX.yaml`) by capability tag and cost budget (zero-token catalog). Workers must check the index before writing new scripts (`toolfirst` gate, enforced by `worker_budget.py`).

MCP supply (#316): analysis correctness depends on registered MCP servers, so the skill manages its own supply manifest + probe + scaffold instead of relying on machine-scattered user config. The single manifest source is `scripts/mcp_probe.py`; `kunglao-init` scaffolds a workspace `.mcp.json` when missing (`--no-mcp` skips; an existing file is never overwritten). Probe: `python scripts/mcp_probe.py <ws> --type <windows|linux|android>` (exit 1 = HARD missing, 2 = WARN missing only).

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
# RED: failing test → GREEN: minimal implementation → refactor
python -m pytest -q
gh pr create --base dev
```

The release contract is revision-owned: `pyproject.toml` + `uv.lock` (pinned deps), `release-manifest.yaml` (declared asset inventory), `release_receipt.py` (observed inventory: per-asset sha256, CLI `--help` exit codes, test results). CI runs it on every PR:

```bash
uv sync --locked
uv run python scripts/release_receipt.py --check
uv run python -m pytest -q
```

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
