# references/ Domain Index — progressive disclosure entry point

> Orchestrator: read this file once per round, pick a domain, dispatch the worker, worker reads `_index-<domain>.md`, then loads specific files. Full per-file catalog below the domain table.

## Domain table

| Domain | Files (re-library/) | Purpose |
|---|---|---|
| tools | tools, tools-dynamic, tools-advanced, tools-crypto | Static/dynamic/advanced/crypto tooling quick-reference |
| android-fingerprint | android-fingerprint-apis | Device/sensor fingerprint API taint seeds (dexdc --seeds; #692 WP5) |
| anti-analysis | anti-analysis | Anti-debug/anti-VM/anti-DBI detection and bypass |
| patterns | patterns, patterns-simulation, patterns-decode, patterns-debugging | General RE techniques: patterns/simulation/decode/dynamic debugging |
| languages | languages, languages-compiled, languages-go, languages-platforms | Language-specific RE (scripting/compiled/Go/platform stacks) |
| platforms | platforms, platforms-elf, platforms-kernel, platforms-hardware | Platform and format RE (OS/ELF/kernel/hardware) |
| methodology | field-notes, malware-analysis, malware-analysis-workflow, malware-analysis-quickstart, malware-triage, malware-dynamic-analysis, detection-engineer, malware-report-writer, phishing-case-study | Analysis methods and malware application domain (primary use case) |
| osint | multi-search-engine, multi-search-engine-refs | Multi-engine OSINT search |
| resources | awesome-re-resources | External RE resource collection |
| web-labs | web-re-quickref | Browser JS reverse engineering quick-reference (web workspaces, camoufox MCP supply, layered peeling workflow, crypto signatures, anti-patterns) |
| web-risk-control | web-risk-control | Web anti-bot defense-response doctrine (#761): signal taxonomy, adversarial decision tree (headless-first escalation), stack identification, detection-point localization loop |
| web-crawler-engineering | web-crawler-engineering | Sustainable collection engineering (#761): session persistence, rate disguise, IP strategy, CAPTCHA triage |
| contracts | agent-three-state-charter, error-response-taxonomy, dispatch-protocol | Behavior contracts the orchestrator loads on scenario (ask/stop charter, error response taxonomy, dispatch protocol) |

| Scenario | Domain |
|---|---|
| Disassembly / static analysis | tools + patterns |
| Dynamic debugging (x64dbg / Frida / Qiling / VM) | tools-dynamic + patterns-debugging |
| Packed / obfuscated / anti-analysis | anti-analysis + tools-advanced |
| Firmware / hardware | platforms-hardware |
| Kernel driver / module | platforms-kernel |
| Language-specific | languages |
| Platform-specific | platforms |
| Detection rules / reports | methodology (detection-engineer, malware-report-writer) |
| Intelligence / search | osint |
| Browser JS target (`--type web`) | web-labs |
| Anti-bot decisions & crawler ops (风控对抗/爬虫工程) | web-risk-control + web-crawler-engineering |
| Action error / tool-VM-install failure response | contracts (error-response-taxonomy) |
| Ask-the-user / irreversible-action decision | contracts (agent-three-state-charter) |

## Per-domain index files

| File | Domain | Purpose | When to read |
|------|--------|---------|-------------|
| `_index-tools.md` | tools | File-level index for the tools domain. | When a worker is dispatched to tooling / static-analysis work. |
| `_index-web-labs.md` | web-labs | File-level index for the web-labs domain (quick-reference, camoufox MCP, peeling workflow). | When dispatched to a browser JS reverse engineering task (`--type web`). |
| `_index-web-risk-control.md` | web-risk-control | File-level index for the anti-bot doctrine domain (#761). | When a web claim hits blocking / challenge / 风控 and must classify the signal, pick a decision-tree branch, or localize the detection point. |
| `_index-web-crawler-engineering.md` | web-crawler-engineering | File-level index for the sustainable collection engineering domain (#761). | After access is solved on a web target — designing sessions, rate budgets, IP strategy, or CAPTCHA triage. |
| `_index-anti-analysis.md` | anti-analysis | File-level index for the anti-analysis domain. | When a worker faces anti-debug / anti-VM / anti-DBI samples. |
| `_index-patterns.md` | patterns | File-level index for the patterns domain (general RE techniques). | When a worker needs pattern-recognition references. |
| `_index-languages.md` | languages | File-level index for the languages domain. | When a worker has identified the sample's language. |
| `_index-platforms.md` | platforms | File-level index for the platforms domain. | When a worker has identified the sample's platform/format. |
| `_index-methodology.md` | methodology | File-level index for the methodology domain (incl. malware application area). | When a worker starts a malware-sample analysis task. |
| `_index-osint.md` | osint | File-level index for the osint domain. | When a worker needs external intelligence / multi-engine search. |
| `_index-resources.md` | resources | File-level index for the resources domain. | When a worker needs external RE learning materials or community tools. |

## Top-level references (full catalog)

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `case-book.md` | failure-cases | Documents five real failure modes from prior sessions with root causes and fixes. | When recognizing a recurring behavioral pattern (e.g., idling with free slots, stale plans). |
| `cli-script-checklist.md` | contracts | CLI script spec checklist (issue #277): parameterized / injectable / idempotent / check-apply-remove / exit-code states / text-or-JSON output / error guidance. | When writing or reviewing a reusable tool script for scripts/, or deciding between a new CLI and an inline one-liner. |
| `cold-start-contract.md` | contracts | 8-file read sequence for round 0, incremental-change detection, Phase 0 mandates. | At session start for cold-start vs incremental-read decision, or Phase 0 hook config. |
| `convergence-loop.md` | contracts | 5 convergence-driven behaviors with case evidence, spin-detection, failure-analysis gate. | When diagnosing a spinning/stalled loop or deciding on failed-attempt handling. |
| `decision-rights.md` | governance | Decision rights matrix — 15-row three-way table (mechanical / LLM / user). | When resolving who decides a particular decision. |
| `agent-three-state-charter.md` | contracts | 3-state ask/stop charter (allowed / must-ask / must-stop; mechanical-first, LLM backstops miss-recall). | Before any "should I ask the user" decision, an identity/scope/authorization ambiguity, or an irreversible action. |
| `anomaly-baseline.md` | methodology | Anomaly detection baseline corpus sourcing + fail-open semantics + operator tuning knobs (#663). | When calibrating anomaly_detector thresholds or adding baseline corpus sources. |
| `error-response-taxonomy.md` | contracts | Action-error classes → forced responses (STOP / ASK / RETRY-ONCE / ESCALATE); human-event gate > default-allowed priority. | Immediately after any tool/VM/install/action error, before choosing a response. |
| `dispatch-protocol.md` | contracts | Dispatch prompt protocol v1 (JSON) + v0 (regex); `reversible: false` declaration field. | When writing a worker dispatch prompt or adding fields to the dispatch JSON. |
| `downstream-contract.md` | governance | Downstream contract for skill maintainers — full contract table and rules. | When maintaining or extending the skill. |
| `dynamic-re-tool-priority.md` | dynamic-analysis | Tool-priority order for dynamic RE dispatch, VM-channel-only mandate. | Before dispatching a worker for call-site stepping or dynamic RE. |
| `excerpt-lint.md` | gates | Three mechanical lint rules for condensed decompile excerpts. | When authoring or reviewing a condensed decompile excerpt fixture. |
| `failure-modes-lifecycle.md` | failure-modes | F1-F6: dispatch/heartbeat/routing lifecycle, premature-termination detection. | When reporting dispatch issues or premature "done" declarations. |
| `failure-modes-monitoring.md` | failure-modes | F7-F13: worker help, self-doubt, state discipline, environment downgrade rules. | When reporting worker-level problems or dynamic-miss NEGATIVE conclusions. |
| `failure-modes-state.md` | failure-modes | F14-F18: plan-state consistency (stale blockers, claims, drift, progress). | When reporting plan/status/progress issues. |
| `failure-modes.md` | failure-modes | Index routing the 18 failure modes across three domain files. | When a failure-mode occurred but unsure which domain file to load. |
| `guardrails.md` | governance | Full backing reference for orchestrator guardrails. | When the SKILL.md inline summary is insufficient. |
| `lessons/README.md` | failure-lessons | Global failure-lessons library (issue 41, cross-sample, never per-workspace): `scripts/failure_analysis_gate.py --lessons` aggregates closed-loop analyses at closeout into runtime lesson files; keyword retrieval (`similar_lessons`) runs automatically inside the gate at failure time. The README is the indexable face; runtime lesson files exist only in deployed copies. | After a closeout (`--lessons` aggregation), when choosing a method-ladder rung and past failures of the same shape matter, or when adding to / searching the library. |
| `machine-check-contract.md` | contracts | Executable-oracle contract (#332): verification records must carry machine_check {command, expected, actual, passed}; exception path and mapping-table mirror of references/machine_check_map.yaml. | When validating a red-team verification record, writing one, or promoting a claim. |
| `malware-phase-routing.md` | routing | Maps file types to analysis phases, VM isolation boundary. | At the start of a new malware engagement for phase decision. |
| `mechanisms.md` | governance | Mechanism lifecycle ledger — retired/superseded mechanisms with replacements (#446); mirrored by hooks/lib_kunglao.MECHANISMS metadata. | When retiring or superseding a mechanism, or auditing retirement completeness. |
| `method-constraints.md` | dispatch | Constraint table for known-incompatible scenarios. | Before dispatching a worker to include correct method constraints. |
| `operational-mechanics.md` | mechanics | HOW behind heartbeat tick/registration (loop_scheduler durable schedule, #754 continuous-tick standard), worker ping, self-cap-safe dispatch, VM launch; liveness_policy.py threshold single source (#597). | When implementing/debugging heartbeat, writing dispatch prose, VM x64dbg launch, or tuning a liveness/staleness threshold. |
| `optimization-2026-08.md` | optimization | Background compendium: smart-ping, closeout checklist, worktree caveats. | When needing the full expanded text of a compact SKILL.md reference. |
| `schema.md` | schema | All data schemas: boundary_type, fact.status, claim-register, etc. | When reading/writing structured state files. |
| `state-mapping.md` | schema | Two-layer state mapping: claim-register workflow states ↔ fact status + verify_status; ICD-203 nine-rule landing fields (#336). | When writing/migrating facts, linting, or reconciling register vs frontmatter statuses. |
| `subagent-review.md` (in `devkit/docs/`) | gates | Gate 5 (Subagent Review / Maker-Checker) contract — 3 required fields per specialist subagent dispatch (plan / status_sync / tools_used) + verified_by anti self-stamp. | Before any specialist subagent dispatch, or when pre-commit Gate 5 HARD_PAUSE fires. |
| `search-policy.md` | dispatch | Three-layer search strategy: claim-DAG, priority greedy, tier gate. | Before each dispatch round for priority_ratio.py and tier gates. |
| `tool-inventory.md` | tools | Full tool inventory table and kunglao CLI family. | When needing the complete list of available tools. |
| `verify-static-vs-dynamic.md` | verification | Static vs dynamic verification strategies. | When verifying a worker's evidence to pick the correct verification method. |
| `wal-protocol.md` | contracts | Write-ahead log for atomic multi-writer state updates. | When writing facts and updating claim-register concurrently. |
| `xml-injection-standard.md` | contracts | XML tag injection standard (#55): producer-attributed, trust-tagged agent-context injection across eight fixed tags (kunglao-state / kunglao-facts / external-tools / tool-recommendations / case-hints / gate-verdict / oracle-sanction / worker-signal). | When writing or changing any hook/script that injects text into the agent's context, or auditing which producer owns which tag. |

## re-library/ (Reverse Engineering Knowledge Base)

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `re-library/android-fingerprint-apis.md` | android-fingerprint | Device/sensor fingerprint API taint seed table - the capability doc driving dexdc `--taint-api` seeds; hypotheses (risk-control vs tracking) and anomaly concentration. | When a claim asks whether the sample collects fingerprint identifiers and where they flow (#692). |
| `re-library/anti-analysis.md` | anti-analysis | Anti-debugging, anti-VM, anti-DBI, code-integrity bypass. | When encountering binaries detecting debuggers/VMs/instrumentation. |
| `re-library/awesome-re-resources.md` | resources | Curated RE resource repos, tools, tutorials. | When seeking external learning materials or specialized utilities. |
| `re-library/falsifier-library.md` | methodology | Hypothesis-family falsifier pattern library: 10 families (hash/HMAC/block-cipher/protobuf/signing-entry/capability-claim/native-standard/fact-conflict/async-entry/obfuscation-variant) each with 2-3 distinguishing experiments (trigger + what positive/negative proves). | When filing or adjudicating hypothesis candidates — every candidate needs a named falsifier (#109 admission). |
| `re-library/loop-stage-gates.md` | methodology | Analysis-loop stage discipline: entry-anchor hard gate with equivalent-path principle, clean-surface suspicion rule (dynamic-resolution), transition-delta economics, instruction feasibility negotiation. | At every stage transition; when a requested step has a known-blocking precondition; when a capability claim rests on an unusually clean static surface. |
| `re-library/native-sign-recovery.md` | methodology | Boundary-first recovery of Android native request-signing: 6-step ladder (locate boundary -> multi-sample capture -> family-by-shape with falsifiers -> extract -> reproduce -> byte-exact replay gate) + incremental emulator stubbing loop + 4 code-listing worked examples. | When a captured request's signature field is computed inside native code and the goal is offline reproduction. |
| `re-library/stacked-protections.md` | methodology | Protection orthogonality table (pinning/RASP/obfuscation/transport-crypto as stackable dimensions), symptom->layer attribution order, recon sequence, AI-vs-mechanical division of labor. | Before/during any dispatch whose target may carry stacked protections; when hooks die or captures come back empty. |
| `re-library/verification-safety.md` | methodology | Verification action discipline: safe-to-invoke gate (>=2-match promotion), minimal-patch rule (bypass = probe license, never ships), 8-type evidence vocabulary for hypothesis-layer update channels. | When building verification harnesses; before any bypass patch; when typing evidence for categorical updates (#106). |
| `re-library/vm-deobfuscation-routing.md` | patterns | Pre-peel raw-JS VM screen (positive traits + negative exclusion table) + flattening-variant ecology at the stable layer (detection clues + countermeasure classes; tool selection deferred to execution-time research). | On raw minified JS before deobfuscation; when a flattening countermeasure keeps failing (wrong-variant check). |
| `re-library/wire-format-recognition.md` | methodology | Opaque-response 3-way triage (standard crypto / private protocol / standard serialization), schemaless protobuf parse loop, length-prefix conventions, JA3-class TLS fingerprint surface. | When a captured response body is unreadable; when offline replay is rejected despite a correct-looking signature. |
| `re-library/detection-engineer.md` | malware | Transforming analysis findings into detection content. | When writing detection signatures or hunting queries. |
| `re-library/field-notes.md` | field-notes | Binary type quirks, anti-debug bypasses, specialized patterns. | After triage, when diving into specific binary type analysis. |
| `re-library/jsvmp-triage.md` | jsvmp-triage | JSVMP/VMP bytecode-VM triage knowledge card (#884): three-feature thresholds (F1 big array / F2 dispatch loop / F3 semantic-free case bodies anchored on case-table presence), three-of-two verdict + confidence tiers, trace/OPCODE_MAP/replay methodology outline. | When a deobfuscated web bundle may hide a bytecode VM — read with the `jsvmp-triage` CLI verdict (tools/web/jsvmp_triage.py) to decide AST vs instruction-trace. |
| `re-library/kunglao-toolshelf.md` | tools | The repo's own toolshelf of `tools/` CLIs (#866 four-face registration): static triage (die_probe, pe_analyze, disasm_dump, overlay_scan, shellcode_scan, stack-strings, extract-syscalls, go-buildinfo-carve, binary-sweep, call-site-args, c_normalize, opaque_pred, disasm_constant_check, yara-scan, yara-gen), ghidra family (run_ghidra_postscript, ghidra_job async + ghidra_diff), crypto-tool, android providers (apk_mem_gate, baksmali_index), pipelines/aux (build_evidence_index, audit_legacy_proven, measure_blind_coverage, capture_golden, measure_cold_start, sanitize). | When choosing an in-repo CLI for a RE task or checking what the shelf can already do — pair with the per-tool contract entries in `tools/_index-<category>.md`. |
| `re-library/languages-compiled.md` | languages | Reversing compiled languages beyond C: Go, Rust, Swift, etc. | When encountering a non-C compiled binary. |
| `re-library/languages-go.md` | languages | End-to-end Go binary reversing. | When analyzing a statically-linked Go binary. |
| `re-library/languages-platforms.md` | languages | Platform/framework-specific RE (Android, Electron, SGX, etc.). | When reversing binaries tied to specific platforms/frameworks. |
| `re-library/languages.md` | languages | Scripting and esoteric language reversing. | When facing non-standard language targets. |
| `re-library/malware-analysis-quickstart.md` | malware | Quick installation/verification guide for malware skill set. | When setting up the malware analysis skill suite. |
| `re-library/malware-analysis-workflow.md` | malware | Skill orchestrator routing malware tasks to sub-skills. | When beginning any malware analysis engagement. |
| `re-library/malware-analysis.md` | malware | Six-phase malware analysis methodology. | When performing end-to-end malware analysis. |
| `re-library/malware-dynamic-analysis.md` | malware | Safe malware execution in sandbox environments. | When moving beyond static to runtime behavior analysis. |
| `re-library/malware-report-writer.md` | malware | Professional malware analysis report production. | When finalizing analysis and creating a report. |
| `re-library/malware-triage.md` | malware | Rapid initial assessment of malware samples. | When receiving new samples for quick classification. |
| `re-library/multi-search-engine-refs.md` | osint | Advanced search operators for multiple engines. | When performing OSINT with precise multi-engine queries. |
| `re-library/multi-search-engine.md` | osint | MCP tool integration for 17 search engines. | When programmatically querying multiple search engines. |
| `re-library/patterns-debugging.md` | patterns | Debugging and dynamic-analysis patterns. | When validation logic is hidden or symbolic solving is needed. |
| `re-library/patterns-decode.md` | patterns | Decode and deobfuscation patterns. | When a sample uses layered decryption or obfuscated strings. |
| `re-library/patterns-simulation.md` | patterns | Simulation and execution patterns. | When a sample contains custom VM/emulator or shellcode. |
| `re-library/patterns.md` | patterns | Foundational catalog of general RE patterns. | When identifying which general pattern category a sample falls under. |
| `re-library/phishing-case-study.md` | case-study | Same-topic contradiction incident and fact-base contamination. | When a same-topic PROVEN pair disagrees. |
| `re-library/platforms-elf.md` | platforms | ELF binary structure deep-dive. | When reversing Linux/Android ELF binaries. |
| `re-library/platforms-hardware.md` | platforms | Hardware and advanced architecture reversing. | When reversing embedded hardware, RISC-V, ARM64, microcontrollers. |
| `re-library/platforms-kernel.md` | platforms | Windows and Linux kernel driver reversing. | When analyzing kernel-mode code (drivers, rootkits, minifilters). |
| `re-library/platforms.md` | platforms | Platform-specific reversing (macOS/iOS, IoT, CAN bus). | When analyzing binaries for non-desktop platforms. |
| `re-library/tools-advanced.md` | tools | Advanced RE tooling: unpackers, diffing, symbolic exec. | When facing heavily packed/obfuscated binaries. |
| `re-library/tools-crypto.md` | tools | Encryption/encoding/hashing tool quick-reference. | When needing to identify/decode/crack encrypted data. |
| `re-library/tools-dynamic.md` | tools | Dynamic analysis tooling (Frida, angr, lldb, x64dbg, Qiling). | When performing runtime/dynamic analysis or function hooking. |
| `re-library/tools.md` | tools | Core static RE tools (GDB, Radare2, Ghidra, Unicorn). | When setting up a reversing workspace. |
| `re-library/web-crawler-engineering.md` | web-crawler-engineering | 爬虫工程 sustainable collection engineering (#761): 会话维持 cookie 池/登录态, 频率伪装 human cadence, IP 策略 住宅/机房/轮换/sticky, CAPTCHA 分类应对 slider/点选/re-challenge. | After access is solved on a `--type web` target — designing sustainable collection ops or triaging a CAPTCHA surface. |
| `re-library/web-re-quickref.md` | web-labs | Browser JS reverse engineering quick-reference: hook/boundary quick reference, signed-parameter workflow, layered peeling (unbundle → deobfuscate → VM boundary), crypto signatures, anti-patterns. | Before opening the browser on a web target (`--type web`); injected into web workspace CLAUDE.md at init. |
| `re-library/web-risk-control.md` | web-risk-control | 风控对抗 anti-bot doctrine (#761): 信号分类学 device-fingerprint/behavioral/environment-consistency/protocol, 对抗决策树 bypass→仿真→real + 无头升级链 (J6), 风控栈识别 加速乐/瑞数/自研, 检测点定位 触发→观察→归因 loop with camoufox CDP instrumentation (J7). | When a request is blocked / challenged / a signed param is rejected on a web target — classify the signal first, then pick the branch. |
