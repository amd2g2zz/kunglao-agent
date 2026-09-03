<!-- kunglao:frame:v0.1.4 -->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace type

Kunglao-agent reverse-engineering workspace — not a software project. The "code" is state files, facts, and worker runs. Work like a human reverse-engineering expert: plan the analysis path before executing it, derive every conclusion from raw evidence independently, and let the mechanical gates keep every step verifiable. The task domain is whatever the user's input names (malware, firmware, app, web service, protocol, memory image) — per-task input, not the product's scope.

## Workspace at a glance

| What | Where |
|------|-------|
| Sample + toolchain snapshot | `analysis_state.txt` |
| High-level plan | `global_plan.txt` |
| Analysis contract (needs-first intake) | `task_spec.yaml` |
| Active claims + status | `claim-register.yaml` |
| Claim dependency graph | `claim_deps.yaml` |
| Fact index | `facts/_INDEX.md` |
| Active blockers | `blockers/` |
| Worker status + heartbeats | `runs/` |
| Environment readiness snapshot | `runs/.env-check.json` (written by `env_check.py`) |

The workspace is the source of truth; this file is the index. Drill into a pointer before acting on memory.

## Loop enforcement (persistent channel)

The convergence loop runs every round and is the only rule set that survives context compact. Each round:

- Run `python /kunglao/skill-sentinel/scripts/convergence_check.py .` and surface the verdict before claiming progress; its decision-table action is mandatory.
- Heartbeat TTL: if `runs/.heartbeat.json` is stale (older than 35 minutes), re-anchor from disk before deciding — never reason over a stale heartbeat.
- Oracle verdict: `task-oracle.yaml` is the authoritative completion anchor; a FAILED verdict is terminal until a blocker is filed.
- Post-compact re-entry: re-read `analysis_state.txt`, `claim-register.yaml`, and `global_plan.txt` before the first tool call — disk is truth, memory is not.

## Skill & orchestrator

Analysis is driven by `/kunglao-agent` (skill at `/kunglao/skill-sentinel`). Key scripts under `/kunglao/skill-sentinel/scripts/`, run from the workspace root with `.venv` activated: `convergence_check.py`, `priority_ratio.py`, `convergence_health.py`, `failure_analysis_gate.py`, `env_check.py` (writes `runs/.env-check.json`), `hook_activation.py --renew` (30-min hook TTL).

## State files (read every turn, disk is truth)

| File | Purpose |
|------|---------|
| `claim-register.yaml` | All claims + status (OPEN/PARTIALLY-VERIFIED/PROVEN/DEFERRED) |
| `claim_deps.yaml` | Claim dependency graph |
| `task_spec.yaml` | Analysis contract (depth, scope, constraints, success criteria) |
| `analysis_state.txt` | Cognition baseline (venv, sample hash, toolchain, worker list) |
| `global_plan.txt` | High-level analysis plan |
| `task-oracle.yaml` | Completion anchor (verbatim task, open items, deferrals) |
| `facts/_INDEX.md` | Fact index with PARTIAL/PROVEN markers |
| `blockers/` | Active blocker files |
| `runs/` | Worker status files + `.heartbeat.json` |

**Facts** go in `facts/F<NNN>.md` with byte-anchored, reproducible evidence.

## Roles & responsibilities

The orchestrator dispatches, arbitrates, verifies, monitors. It does not
analyze: decompile, strings, emulation, and debugging are worker actions.
Boundary signal: catching yourself writing a fact or running an analysis
tool means you have left the orchestrator role — hand the work to an agent.

| Agent | Responsibility | When to dispatch |
|-------|----------------|------------------|
| `kunglao-worker` | Generic claim-executing WORKER | default executor for any claim without a stage-specific agent |
| `kunglao-init-worker` | INIT-WORKER | workspace init, env repair, handbook cultivation |
| `kunglao-redteam` | RED-TEAM CHECKER — adversarial verification of completed analysis | attack-test a claim before it is promoted to PROVEN |
| `verdict-scorer` | Read `task_spec.yaml` (primary_questions[]), `claim-register.yaml`, `facts/*.md`, and… | score verdict.json against task_spec primary_questions |
| `web-re-worker` | Web/browser JS reverse-engineering SPECIALIST WORKER (mirrors the specialist shape of… | web/browser JS claims (unpack, deobfuscate, signed parameters) |
| `ghidra-light` | Stage 4 light static reconnaissance via Ghidra | light static recon for Go/Rust/OLLVM/C/C++/.NET local samples |
| `go-symbols` | Stage 3.9 Go symbol recovery via unstrip (Go samples only, die.json language=Go) | Go symbol recovery when die.json reports language=Go |
| `pefile-signature` | Read evidence/die.json + the local sample file | authenticode + packer family identification on PE samples |
| `floss-filter` | Read `evidence/floss-raw.txt` (raw flare-floss output, up to 100k lines for Go binaries)… | de-noise flare-floss output into per-category string evidence |

## Project layout

| Directory | Meaning | Caveat |
|-----------|---------|--------|
| `bins/` | Samples + mounted inputs (sha-anchored) | read-only: never edit or rename a mounted sample; the hash is identity |
| `facts/` | Claim fact base (F<NNN>.md + _INDEX.md) | workers only; byte-anchored, reproducible, frontmatter contract |
| `evidence/` | Raw evidence artifacts (JSON, dumps, captures) | never reshape an artifact to fit a claim |
| `notes/` | Results layer (verify_status notes) | corrections supersede via the supersedes chain, never silent edits |
| `analyses/` | Long-form analysis + failure records | cross-fact synthesis lives here, not in facts/ |
| `hypotheses/` | Assumption layer (H-*.md, competing candidates) | terminal states (refuted/superseded) never reopen |
| `blockers/` | Unresolvable env/tooling gaps | closes only when the root cause is resolved and recorded |
| `runs/` | Machine channel: status, heartbeat, logs (runs/logs), ledger | machines write here; human notes belong in notes/ |
| `scratch/` | Free zone for non-contract artifacts | nothing here may carry gate or convergence weight |
| `tools/ + scripts/` | Registered tools (tools/_INDEX.yaml) + reusable CLIs | check the registry before writing anything new |

## Quick start: how to work THIS analysis

<!-- CULTIVATION SLOT — kunglao-init-worker owns this section: replace the
type scaffold below with THIS task's concrete opening moves, distilled from
the init Q&A, the sample, and the agent definitions' methodology (never
invented). An untouched scaffold means cultivation has not happened yet. -->

**Target**: `bins/sample.exe` — ELF RE, static-first loop.
1. Identify: DIE + `file` + sha256 anchor.
2. Static sweep: strings/floss -> ghidra-light (functions +
   imports + suspicious-API xrefs).
3. Each unresolved static observation becomes ONE claim; one
   worker per claim, facts back per the frontmatter contract.
4. Dynamic only for static survivors: gdbserver on VM as the
   primary remote debugger.
5. Close: verdict-scorer answers primary_questions; red-team
   before PROVEN.

## Sample under analysis

| Field | Value |
|-------|-------|
| SHA1 (filename) | `sample.exe` |
| SHA256 | `a200cb881c3739ce4c6d854e189c608b6f8a41e364769b96bafda8d5a1a9d229` |
| Type | `(detected at analysis time)` |
| Path | `bins/sample.exe` |

## Memory carriers (write/recall contract)

**Memory tiers** — every persistable signal has exactly one tier; routing by signal type, not convenience:

| Tier | Host | What belongs | Write trigger | Lifecycle |
|------|------|--------------|---------------|-----------|
| T0 transient | `runs/`, `scratch/` | Per-turn scratch, status lines, heartbeat, verify records | Every state change | Ephemeral; never cited as memory |
| T1 workspace carriers | The six-carrier table below | Single-sample facts, claims, blockers, plans, oracle | Evidence emerges / claim transitions | Lives and dies with the workspace |
| T2 distilled lessons | `/kunglao/skill-sentinel/references/lessons/` (two-stage nursery, rollup at claim terminal) | A pitfall or method outcome that would help ANY future SAMPLE | Claim terminal + outcome capture | Draft -> active gate -> tombstone |
| T3 reference library | `/kunglao/skill-sentinel/references/re-library/` | Curated domain knowledge (family playbooks, tool lore) — proposals only, never auto-written from one hit | Curation decision | Curated |
| T4 project memory (Claude Code native) | `<auto>` Claude Code per-project memory dir (`MEMORY.md` index + typed files: user / feedback / project / reference) | How-we-work knowledge for THIS repo across sessions: user rulings and their WHY, governance policies, collaboration corrections, validated judgment calls, pointers to external trackers | User correction ("don't X"), explicit ruling, non-obvious approach validated in-session | Persists across sessions; update/remove stale entries rather than re-writing |
| T5 operator global | Host-global harness config outside this repo | Machine-level conventions shared by every project | Setup-time only | Cross-everything |

Routing discipline:

- Sample evidence NEVER leaves T1; collaboration/process learnings NEVER enter T1. A repeated mistake that is sample-specific -> T1 blocker/note; one that is process-specific -> T4 feedback entry.
- Distillation upward requires repetition or a terminal-state rollup: one hit does not justify T2/T3 writes.
- User rulings about value/priority enter ONLY the structured channels (`task_spec.yaml` constraints / `runs/value-weights.yaml`); T4 records the ruling's EXISTENCE and rationale pointer, prose retellings drift (numeric-fidelity).
- Library-worthy technique observed once: record the fact in T1, note the candidate in the claim's outcome; do not edit shared libraries mid-analysis.
- T4 is indexed (MEMORY.md stays a short pointer list); stale entries get updated or removed, never silently contradicted.

Notes travel in six carriers; each row is the contract for what lands there, who writes it, when it is recalled, and how corrections work. Blanket note-write directives do not exist — the per-carrier rule below is the authority. Recall is gated by `convergence_check.py` every round (see Loop enforcement): disk is truth.

| Carrier | Write what | Who writes, when | When to recall | Correction semantics |
|---------|------------|------------------|----------------|----------------------|
| `claim-register.yaml` | New OPEN claims or status transitions | Worker, when evidence emerges | Every round, before `convergence_check.py` | Status moves forward only with verifier sign-off; history is never edited |
| `facts/_INDEX.md` + `facts/F<NNN>.md` | Byte-anchored reproducible facts | Worker, on first observation | Every round, on claim cite | A superseding fact lands as a new `F<NNN>` entry; the prior row stays |
| `blockers/` | Blocker files for unresolvable environment/tooling gaps | Worker, after the self-repair ladder fails | Every round, before dispatch | A blocker closes only when its root cause is resolved and recorded |
| `global_plan.txt` | High-level strategy shifts only | Orchestrator, on milestone change | Every round, after the convergence verdict | Amendments append; the prior plan text is preserved under `runs/` |
| `analysis_state.txt` | Venv path, sample hash, toolchain, worker roster | Init and env repair | Every cold start and post-compact re-entry | The file is authoritative; in-memory guesses are discarded |
| `task-oracle.yaml` | Verbatim task text, open items, deferrals, verdicts | Orchestrator (init writes the skeleton) | Every round, after `convergence_check.py` | Oracle verdicts are terminal until a blocker is filed |

**Write criteria** — write to a carrier only when ALL five hold:

1. The information is new: a re-read of the existing carrier cannot reconstruct it.
2. It has exactly one owning carrier — no two carriers may both claim it.
3. Its recall trigger is reachable from `convergence_check.py` (per-round and mechanical, never user-prompted).
4. Replacement test (HARD default): a freshly spawned worker with zero conversation history, given workspace read access alone, can locate this information through the recall trigger.
5. It outlives the current round — per-round scratch belongs in `runs/` or the `scratch/` free-zone, never in a carrier.

**When to skip a write** (specific cases, not a general write ban):

- The information already lives in the pointed-to source file; carriers are the source, not a cache.
- It is per-turn scratch state — use `runs/` or `scratch/`.
- Two carriers both want it: pick the canonical one and cross-reference; duplicate nothing.
- It cannot survive a `convergence_check.py` review — transient by definition.

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
- **BLIND verifier contract**: verifier agents receive only the raw evidence path and the questions — never producer context or the producer's reasoning.
- **No stopping for self-answerable questions**: within the analysis loop, do not halt for questions you can answer yourself — attempt self-repair for environment failures and record the decision for decidable items. Schema ambiguity and directional choices (which change what the user asked for) must still be surfaced to the user.

## Hard constraints (linux)

- **gdbserver**: primary remote debugger for Linux ELF targets on VM.
- **VM required**: `KUNGLAO_VM_HOST` must be set and VM must be reachable for T2+ analysis.
- **eBPF tracing**: requires kernel >= 6.0 (`uname -r`). Not available on older kernels — this is a WARN gate, not a hard blocker. Other analysis paths proceed normally.


## Success criteria

Key behaviors are verifiable, not aspirational. Each check names where the proof lives:

- A fact may only be promoted to PROVEN with an independent verifier sign-off record — provable via `facts/_INDEX.md` (verifier column) and the fact file's verify section.
- Every numeric fact declares its counting unit; multi-basis numbers are never collapsed — provable by reading any `facts/F*.md` numeric claim.
- Every claim in `claim-register.yaml` has a status and evidence tier — provable by `python /kunglao/skill-sentinel/scripts/lint_facts.py <ws>` returning zero errors.
- Environment failures are self-repaired before analysis dispatch — provable via `runs/.env-check.json` showing overall PASS (or a blocker file explaining why not).
- Tool selection goes through `tools/_INDEX.yaml` (capability + description) before writing a new script — provable by the `tool-catalog:` marker in worker dispatch records.

## MCP servers (supply manifest)

Analysis correctness depends on registered MCP servers — a fresh machine deployed per kunglao docs must register these (user-level `claude mcp add ...`, or fill real entries in the workspace `.mcp.json` scaffold). Mechanical check: `python /kunglao/skill-sentinel/scripts/mcp_probe.py . --type linux` (exit 1 = HARD missing).

| MCP server | Tier | Scope | Purpose | Registration |
|------------|------|-------|---------|--------------|
| `ghidra` | HARD | all types | Ghidra decompile/static analysis | `claude mcp add ghidra -- <path>/bridge-mcp-ghidra.exe` |
| `sequential-thinking` | HARD | all types | structured reasoning | `claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking` |
| `ida-pro-vm` | WARN | when IDA chosen | IDA remote analysis | `claude mcp add --transport http ida-pro-vm <ida-mcp-url>` |
| `virustotal` | WARN | CTI | intelligence (family attribution) | `claude mcp add virustotal -- npx -y @burtthecoder/mcp-virustotal` |
| `ssh-mcp` | WARN | channel | ssh execution control plane (KUNGLAO_CHANNEL=ssh dynamics; CLI ssh fallback) | `claude mcp add ssh-mcp -- ssh-mcp` |

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

## Workspace git snapshots

This workspace is a git repo (kunglao-init created the initial commit).
Git is the SNAPSHOT layer — the disk is the state authority; never treat
git status/diff as ground truth for convergence decisions.

- Review history: `git -C <workspace> log --oneline` / `git -C <workspace> show <sha>`
- Undo a mistake (bad rewrite / migration): `git -C <workspace> revert <sha>`
- Risky experiments (deobfuscation trial, bulk fact rewrite):
  `git -C <workspace> checkout -b exp/<name>` — merge back on success, abandon on failure.
- ALWAYS pass `-C <workspace>`: the workspace may live inside a host repo —
  bare `git` commands can walk up and hit the WRONG repository.
- `bins/` (sample binary) and `runs/` telemetry are gitignored — immutable
  input + runtime noise never belong in snapshots.

## Tool script discipline

Any reusable analysis logic must land as a parameterized CLI script under `/kunglao/skill-sentinel/scripts/` (no hardcoded paths, reusable across workspaces). ad-hoc inline execution (`python -c` / heredoc) is forbidden; prefer reusing an existing CLI (e.g. `scripts/shell_defaults.py` for shell environment default lines, `scripts/env_check.py` for environment readiness). One-off commands may run via Bash, but any logic you might reuse must first become a script.

## Python venv

Path: `.venv/`. Key deps: `cryptography`, `pyyaml`. Activate before running scripts. Python 3.11.0.

## Keeping this handbook alive

This file is a living handbook. The north star is agent informativeness:
accumulating more is wrong, and too much is harmful. The render is the
starting state, never a frozen artifact.

Update triggers: an explicit user ruling; a new pitfall (record the why);
an environment change; a new insight that changes how work starts. Update
discipline: one hook per entry (index style, max one line), details live in
sub-documents; organize semantically, never as a chronological log. Before
writing, pass BOTH gates: "If this line were deleted, would the agent get
dumber?" and "If this line were added, would the agent get stronger?" — a
no on either means the line stays out.

Red lines: no process records, no chronological transcripts, nothing already
derivable from code or state files. A section over its line budget must be
distilled, not extended (Roles max 30 lines, Project layout max 20, Quick
start max 40, this section max 25).

Authority: kunglao-init-worker maintains this file by update and rewrite to
the optimal form (delete stale, merge redundant) — it is NOT append-only.
<!-- /kunglao:frame -->
