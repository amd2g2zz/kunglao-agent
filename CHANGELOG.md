# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog 1.1](https://keepachangelog.com/en/1.1.0/), and the
versioning follows PEP 440. The internal iteration markers (v1.9.0–v1.9.38)
used before v0.1 are development-era labels, folded into the v0.1 first
release (see the mapping table at the end).

## [Unreleased]

### Removed (plan-template dead end, #352)

- 5 plan-generation templates under tools/pipelines/ — crypto-decrypt /
  go-recovery / iat-chain / stage-unpack / syscall-chain — plus the
  route_capability plan-catalog CLI surface and their contract test.
  Audit: zero runtime consumers (read only by tests + an unreachable CLI
  path); worker dispatch uses recommend_agent_type only (#352)

### Fixed (router runtime + decide INVALID enum, #370/#371)

- kunglao.py router runtime fixes for 3 of 5 subcommands (#370) — `tick`
  ignores the workspace (bare `hbt.main()` treats the sys.argv[1] literal
  "tick" as the workspace path); replaced with explicit argv injection
  `hbt.main([str(ws)])` (backward-compatible optional argument, aligned with
  the kunglao_verify/kunglao_record router pattern); `decide` human mode and
  `health` re-parsed router argv through nested argparse causing SystemExit 2
  — now they compose the `cc.decide/_human` and
  `ch._read_ledger/assess/_human` module functions directly. Added
  tests/test_router_runtime.py (6 tests, RED first then GREEN): tick writes
  `runs/.heartbeat-tick.json` into the caller's workspace and no longer
  creates a bogus tick/ directory next to cwd; decide prints the real
  decision table; health prints the health line (exit 3 NO_DATA when there is
  no ledger).
- decide-output.json enum gains INVALID (#371) — when task_spec
  primary_questions is non-empty but malformed (#77 fail-closed),
  convergence_check.decide() legitimately returns INVALID and kunglao-decide
  passes it through verbatim (L134), yet the frozen enum lacked that value →
  the CLI would emit contract-violating output. INVALID reuses exit 4 (the
  frozen 0-4 exit surface); frozen-enum ritual (RED test + schema revision +
  specs/phase-4/contract.md and module-design.md M1.3 write-back, in the same
  commit). The "never INVALID" assertion in openspec/archive/fix-97 only
  covered the exception → BLOCKED path; the archive stays untouched.
### Fixed (pre-release security batch, #367)

- Review-gate pre-commit key path no longer hardcodes the author's machine —
  the tracked template `.claude/git-hooks/pre-commit` carries the
  `__KUNGLAO_REVIEW_KEY__` placeholder; the human-run installer
  `kunglao-init --install-git-hooks` stamps the installing user's absolute
  key path into `.git/hooks/pre-commit` once at install time (#147
  anti-forgery preserved: the stamped path is a literal, never env-resolved
  at commit time); an unstamped copy fail-closes with install guidance;
  missing key guides `review_gate.py key-init`; hardcode scan extended to
  the whole tracked tree (git grep, allowlisted historical references only)
  (#367)

### Fixed (hook registry single-source, #372)

- env_check hook mirror drift — HOOK_FILES (6) hand-copied from
  wire_up_settings registrations (8 distinct files); recall_inject (#268)
  and completion_gate were invisible to the env_check deployment gate. Now
  env_check.HOOK_FILES IS wire_up_settings.WIRE_UP_HOOK_FILES (frozenset,
  single source) and check_hooks scans the Stop section too (completion_gate
  is a Stop hook); set-equality + Stop-scan tests added; SKILL.md count
  corrected 6 → 8 (#372)

### Changed (renderer unification, #362)

- CLAUDE.md rendering engine unified — scripts/template_render.py becomes
  the single engine for {{param}} one-pass substitution + residual
  placeholder detection; template_gen.py (CLI/dirs/exit codes unchanged) and
  kunglao-init write_claudemd share the same primitives; CLAUDE.md.base.tmpl
  placeholders migrated `<UPPERCASE>` → `{{lowercase}}` (rendered output
  byte-identical, golden-verified for all three workspace types) (#362)

### Fixed (renderer + env wiring, #362)

- Unfilled placeholders are no longer silent — residual `{{...}}` after
  rendering raises TemplateRenderError (run() converts to stderr + exit 1 +
  cleanup of this scaffold round), eliminating half-rendered CLAUDE.md (#362)
- .env port wiring — KUNGLAO_VM_SHELL_PORT / KUNGLAO_FRIDA_PORT feed into
  the env_check stdlib parser (os.environ first, .env as fallback), VM_PORTS
  derived from the parsed values (the previous hardcodes [9876, 1337]
  disagreed with the toolchain); KUNGLAO_CLAUDE_JSON / KUNGLAO_DIE noted in
  .env.example as "shell export only, .env is not read" (#362)
- Dead code — kunglao-init.py template_for_type() had zero callers, deleted (#362)
- Residual assertion generalized —
  test_init_injected_claudemd_has_no_placeholder_residue switched from
  enumerating 7 placeholders to a regex scan (catches both legacy `<>` and
  new `{{}}` forms) (#362)

### Fixed (pre-release defect batch, #356)

- W1 every tools/_INDEX.yaml tool entry (28) gained a one-line description
  (English, 15-40 chars: what it does + when to pick it, distilled from the
  existing input_output/when_not); validate_index.py gained a
  description-required non-empty assertion (#356)
- W2 CLAUDE.md template single-sourcing — 4 templates (.tmpl/.windows/
  .linux/.android) converged into CLAUDE.md.base.tmpl + kunglao-init
  injecting per-OS diff sections; the five-layer analysis principle folded
  back into the single source; hallucinated reference section
  (~/.claude/rules/common/) removed; a success-criteria section (verifiable
  checks) added; mixed Chinese/English cleaned up (all English) (#356)
- W3 hardcoded-path removal — C:/Users/hr paths in migrate_facts/
  wire_up_settings relativized or replaced with <HOME> placeholders;
  toolchain.py VM_SHELL_PORT bare constant 9876 made configurable via the
  KUNGLAO_VM_SHELL_PORT environment variable (default 9876 unchanged) (#356)
- W4 .env deployment surface — added .env.example (6 deployment variables,
  one-line English comment each); env_check.py now parses .env with pure
  stdlib at startup (os.environ first, workspace .env as fallback, zero new
  dependencies); .gitignore gains .env (#356)
- W5 cfg-hook.js.tmpl Frida 17 fix — Module.getExportByName(mod, name)
  (16-only) → Process.getModuleByName(mod).getExportByName(name), header
  comment notes Requires: frida >= 17 (#356)

## [0.1] - 2026-08-16

First public release: a convergence-driven reverse-engineering orchestration
skill — with Claude Code as the only interface, it drives a malicious sample
to a fact library of byte-level, independently verified proofs, enforced
throughout by mechanical gates.

### Added

- Convergence-loop core — decide/tick/verify/record/health five-subcommand router; the dispatch→blind-verify→CONVERGED loop is adjudicated mechanically by the completion gate (#93)
- Three-type toolchain matrix + type-aware init — per-type minimal toolchain probing for Windows/Linux/Android and workspace rejection when uninitialized (#304)
- Five-layer analysis ladder — L1-L5 depth commitments fixed at init, preventing workers from spinning past their layer (#304)
- Evidence integrity — evidence/_index.json full index, every fact traceable to the original artifact, derived summaries excluded by design (#140)
- ICD-203 alignment — kunglao facts fully aligned with the malware-veri-notes schema + fact frontmatter template (#336)
- Fact reference graph — graph validation of fact-to-fact references; orphans/broken links intercepted in CI (#140)
- OPERATOR_ACTION ledger line — audit trail covering manual interventions (#142)
- Write-side gates — maker-checker stamp re-verification + independent anchors + defer references re-checkable (#236)
- Heartbeat trio — touch/tick/selfcheck: liveness is judged by heartbeat (timestamps do not count), dispatch pre-checks heartbeat aliveness (#287)
- Claim retraction chain — RETRACTED terminal state + claim_deps blast-radius reopening (#331)
- Calibration gate — delivery requires confidence + falsifier, calibration/oracle templates persistently anchored (#204)
- plan-to-execute and tool-first gates — claim dispatch must carry an executable plan; text hitting tool capability keywords forces the tool path (#294)
- specialist-first dispatch gate — agenttype mechanical validation, specialists before generalists (#310)
- Executable oracle contract — verifier verification records must contain a machine_check (#332)
- tools/_INDEX per-domain index — tool home directory, validate_index, per-domain registration and structural-integrity CI (#283)
- Static analysis toolset, 12 tools — binary-sweep/disasm-dump/stack-strings/go-buildinfo-carve/pe_analyze etc. (#278)
- Ghidra toolset — 5 Java scripts + postScript wrappers absorbed into tools/ghidra/ (#293)
- Ghidra async job protocol + binary diff — long tasks moved to background jobs + Bindiff (#308)
- Ghidra runtime recon — Recon/ScanPointer/ExportVtableStruct/EvidenceAnnotations (#320)
- Crypto algorithm library, 8 algorithms + CLI — deduplicated 15+ scattered algorithm-identification logic (#285)
- yara-scan / yara-gen — rule-based scanning and detection-rule generation (#313)
- Frida dynamic templates + script generation templates — cfg-analyze/cfg-hook + decryption/disasm/stage-unpack, Windows path escaping made executable (#335)
- capability router + deterministic tool lookup — sample feature probing routes to tools (#302)
- Decompilation-artifact post-processing — C normalizer + z3 opaque-predicate resolution (#306)
- Runtime knowledge recall — recall_inject hook injects references by claim features (#268)
- references retrieval tool — scene/category/filename matching + progressive-disclosure output (#229)
- Structured event log + TUI status panel — disk-rendered monitoring view (#287)
- 9 standalone CLIs + unified router — kunglao{,-decide,-verify,-record,-monitor,-init,-eval,-digest} + mcp_probe (#316)
- MCP provisioning mechanized — probe + .mcp.json scaffold + per-type provisioning table (#316)
- Release contract — release-manifest + release receipt validating the asset/CLI inventory and binding the knowledge-base revision (#80)
- Evaluation system — evals.json 3 evals + oracle selfcheck in CI (#117)
- Observability — outcome_capture history feeds priority ranking (#122)
- Prompt-injection sanitize — sample-content threat classification built in-house (#307)
- Documentation system — LICENSE/AGENTS.md/README/DESIGN/references layered navigation (#116)

### Changed

- CLI consolidation 31→9 — standalone entrances compressed to 9, the rest folded into router subcommands (#230)
- scripts governance — 70-script audit (0 orphans/0 broken links) + smoke launcher (#230)
- tools/ directory normalization — root-level tools returned home + dual common merged + category ids aligned (#340)
- SKILL.md contract rewrite — 8-section sequential workflow + imperative voice + placeholderization (#226)
- SKILL.md progressive-disclosure fix — DESIGN/issue-number/version references removed, indexes unified on _INDEX.md (#261)
- CTF→RE identity unification — 13 files, 228 occurrences handled, zero knowledge deleted (#250)
- Verification simplified to L1 scripts + unified redteam — verdict-redteam/doubt_checker deleted (#240)
- Documentation reorganization — docs/ (design+devlog) + references archive + openspec archived (#263)
- Tool contract alignment — existing tools unified on the contract + disasm_constant_check core extracted (#284)
- AGENT_TEAMS defaults to 0 — folded into init settings (#276)
- review gate downgraded to 1-reviewer (#323)
- Declaration system reverse scan — undeclared assets registered + index consistency (#320)

### Fixed

- Documentation drift fix batch — subcommand table/aux path/scripts references/old names/version labels (#321)
- Windows paths and platform awareness — frida template path escaping, fixture POSIX-executable (#335)
- UTF-8 stdout contract enforced + Windows reserved-name guard (#317)
- De-hardcoding — workspace detection/agent tool path placeholders/VM IP+port environment discovery (#228)
- digest manifest full re-pin + LF normalization (#271)
- Engineering-grade hook deployment — wire_up_settings writes workspace-level settings (#258)
- Heartbeat tick bound to convergence actions + --heartbeat-off validated on both ends (#237)
- Monitoring closed loop — drift reality check + refutation propagation + feedback inbox (#241)
- Decision-layer fixes F3/F6/F11/F14 — decide output schema split etc. (#127)
- completion transaction — CONVERGED requires zero global contradictions (#202)
- CONVERGED requires discovery consumption (#203)
- Activated workspace without an oracle gets intercepted (#200)
- unified hook exit-code space — BLOCKED(3) vs REJECT(2) (#134)
- YAML safe_load hardening (#129)
- utcnow() deprecation replaced with timezone-aware (#131)
- worktree scan requires the .kunglao-worktree marker file (#137)

### Fixed or Removed

- Pre-release hygiene batch (#355) — one-off fix logs and session-plan leftovers deleted from docs/, HISTORICAL design docs moved into docs/design/archive/, specs/README broken links fixed (removing the untracked .research-tree-alignment dependency and the "no OpenSpec" contradiction), 51 delivered openspec/changes dirs archived to openspec/archive/, root DESIGN.md ruled HISTORICAL and archived, CHANGELOG v1.8.x mapping section completed, .claude/reviews/ session leftovers removed (git-hooks kept), .gitignore gains .research-tree*/ and .pytest_cache
- Dead-code removal — memory/ subsystem deleted wholesale (staging/longterm/candidates corpus + memory/scripts distillation pipeline + references/memory-protocol.md, measured zero runtime consumers); the memory_capture ghost entries in hook_activation ALL_HOOKS and cost_gate advice cleared in the same stroke (#355, originally #358 Wave 6)

## Internal version mapping

The v1.8.x / v1.9.x markers in pre-v0.1 in-repo code comments are
development-era feature-provenance annotations ("this gate landed at
v1.9.24"), not released versions. They all belong to the v0.1 first-release
scope, mapped as follows:

| Internal marker | Representative features (not exhaustive) |
|---|---|
| v1.8.x | orchestrator failure-mode engineering era (design rationale archived in docs/design/archive/DESIGN.md): v1.8 iterative-deepening tier gating; v1.8.1 C0a PROVEN no-discount + self-cap brake; v1.8.2 F1-F6 failure-mode compact table (SKILL.md §6-pre) + self-cap-safe-prose (§7) + B1c blocker; v1.8.3-5 enforcement-gate suite (troubleshooting/search/active-intervention/backtrack/reuse/hook-activation/ask-for-direction, tests/test_v1_8_enforcement_gates.py); v1.8.15/16 complete-teardown search operator chain (scripts/complete_teardown.py) |
| v1.9.0-1 | convergence-driven dispatch becomes the default scheduling mode |
| v1.9.2-7 | failure-blocked claim interception (dispatch_gate), priority-ranking corrections |
| v1.9.8 | worker_pulse convergence pulse, payload shape adaptation everywhere, fact naming fix |
| v1.9.12/13/18/25/26 | worktree isolation and worker state ownership (the repeatedly regressed dispatch-loses-monitoring defect class) |
| v1.9.17 | closeout checklist (guards against premature convergence) |
| v1.9.19 | superseded-path no-go declaration |
| v1.9.20/21 | liveness heartbeat (timestamps do not count), sanctioned SendMessage channel, smart ping protocol |
| v1.9.22 | verifier must be BLIND |
| v1.9.24 | facts-snapshot HARD-REQUIRED (guards against lost-state deception), best-first bias audit |
| v1.9.28 | dispatch pre-checks heartbeat aliveness (mechanized into a gate) |
| v1.9.29 | plan-drift/STALLED/stuck-worker gates, claim-status guard (the most-referenced marker) |
| v1.9.31 | plan-to-execute gate (#239) |
| v1.9.32 | tool-first gate (#294) |
| v1.9.33 | agenttype specialist-first gate (#310) |
| v1.9.36-38 | heartbeat trio (touch/tick/selfcheck) semantics unified |

Distribution stats (re-measured for #355; scope: git-tracked files, excluding
the frozen archives openspec/archive + docs/design|devlog archives +
references/archive, excluding this file itself):
**v1.9.x: 101 occurrences across 26 files in the live tree** — v1.9.29×26,
v1.9.24×13, v1.9.8×6, v1.9.28×4, v1.9.25×4, v1.9.13×4, the rest 1-3 each;
**v1.8.x: 19 occurrences across 8 files in the live tree** — v1.8.2×5,
v1.8.5×4, v1.8.16×3, v1.8.1×2, v1.8.3×2, v1.8.4×2, v1.8.15×1 (another 22
occurrences live inside the frozen archives). These comments stay untouched
per the release decision — they are "when was this introduced" provenance
anchors, not version declarations.
