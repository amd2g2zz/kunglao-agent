# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog 1.1](https://keepachangelog.com/en/1.1.0/), and the
versioning follows PEP 440. The internal iteration markers (v1.9.0–v1.9.38)
used before v0.1 are development-era labels, folded into the v0.1 first
release (see the mapping table at the end).

## [0.1.1] - 2026-08-17

### Added
- Subcommand UX + guided entry (#413): plugin moved to the official skills/ layout (#413)
- /kunglao-agent main entry — prints a subcommand menu on no args and WAITS, never silently runs; unknown subcommand prints the menu plus `unknown: <x>` (#413)
- /kunglao-agent:init skill — workspace initialization flow, argument-hint `<workspace> [--type windows|linux|android]` (#413)
- /kunglao-agent:analysis skill — convergence-loop entry, argument-hint `<workspace>` (#413)
- /kunglao-agent:help skill — subcommand usage list; the full convergence contract moved to skills/kunglao-agent/SKILL.md (#413)
- argument-hint frontmatter on every skill, shown at autocomplete; README gained a Command Reference table covering all four commands (#413)
- MCP-first tool-supply (#407): decompiler passes on ida-pro-vm|ghidra MCP registration; CLI (GHIDRA_HOME/idat64) is fallback only; decompiler check deduplicated across windows/linux/android manifests (#407)
- ask-then-install (#408): init prompts to install missing tools; consent auto-installs per-platform (pip/brew/choco/apt) + registers related MCP + re-probes; IDA never auto-installed (existing MCP URL registered on consent); --assume-yes for CI/headless (#408)
- New scripts/toolchain_install.py — per-item install commands by platform, mocked-install tests (#408)
- Release manifest + docs repointed to the moved main skill; structural checks updated (#413)

### Fixed
- Platform de-hardcoding (#409): analyzeHeadless resolved by sys.platform (.bat on Windows, extensionless on POSIX); venv python resolved by platform from the SKILL-root venv (uv run --project is authoritative) — no more false FAILs on macOS.
- Hook deployment/check unification (#410): env_check accepts workspace-parent settings.json; unwired hooks are WARN/ASK, not FAIL.
- Init workspace-path validation (#411): a sample directory passed as the workspace is refused (exit RC_PATH_SHAPE) with guidance; .claude/ stays at the workspace root; sniff reads bins/ only.
- Init never produces analysis conclusions (#412): seed claims are structural facts only; no family/verdict before the operator defines the task.
- Exit-code semantics audit (#414): RC matrix pinned by test; argparse usage errors normalized 2→1; cleanup removes only this-run artifacts.
- Test-suite validity audit (#394): redundant/meaningless tests removed/merged (before/after counts in the PR).

## [0.1.3] - 2026-08-25

### Round 1 — Unattended Runtime & Long-Horizon Defects (priority per user)

**Added**
- worker status contract (#607): unknown statuses (planning/preflight) count
  ACTIVE — invisible workers reach the stuck list and the #595 event; stuck
  workers' IN_PROGRESS claims reopen → OPEN (the loop's first machine path
  out of IN_PROGRESS); backtrack_gate delegates to the canonical parser.
- drift detection (#612): detect_drift() — stuck + empty evidence → advisory
  events (runs/.drift-events.jsonl); production had 3 incidents with 0%
  mechanical detection.
- monitor wiring (#620 Gap C): heartbeat_tick runs the orphan monitor every
  tick (#88 advisory frozen — rc never weighs).
- top-1 REJECT ledger (#603): runs/gate-rejections.jsonl + kunglao_resume
  consumer; retry-counter firewall pinned (REJECT never trips the #604 breaker).
- init marker robustness (#625): .kunglao-init.json is the PRIMARY
  completeness truth (survives YAML rewrites); YAML comment = legacy fallback.
- orchestrator Bash guard (#608): PreToolUse/Bash WARN on analysis binaries
  outside .wt-* worktrees (maker-checker, target-based #532-style) + durable
  event; registered in all four hook tables.

**Fixed**
- liveness single-source (#597): liveness_policy.py — 10+ _MINUTES constants
  unified (values unchanged); drift-guard test blocks bare assignments.
- TTL expiry observability (#613): one-shot .hook-slept.json + stderr WARN.
- tick rc surfacing (#617): heartbeat_rc reaches the summary line; ALERT
  banner; alert/first_failure persisted (truncation-immune).
- verify truthfulness (#609): --verify fails when registered-but-not-ticking
  (last_tick_ts staleness, fail-closed).
- prompt command ref (#611): /loop step-3 references the real --json
  invocation.
- plain-text crash (#610): priority_ratio default output iterates typed
  actions (was AttributeError on every non---json run).

### Round 2 — Init Handoff, Contracts & Intake

**Added**
- init mechanical handoff (#593 #598): init emits the REAL /loop prompt body
  (via the build_prompt emitter) + exact --verify/--tier commands — both
  by-design red lines PRESERVED (loop_registered never faked by init; hooks
  stay dormant until Phase-0 arm).
- intake preflight (#588 #590): quick_presence() PRESENCE-tier banner in
  O(seconds) before step-0; preconditions decision group (context-only).
- notes-due queue + completion reader (#628): rollup Step 2.5 queues terminal
  claims lacking a durable note; nothing auto-writes (judge-then-revise).
- closure wiring (#629): feedback.check_stale runs every tick (#88 advisory).
- renew audit (#619): action=renew event (was_expired/expiry_gap_s) into
  kunglao_log.
- REJECT observability (#624): env_check_gate REJECTs leave a persistent
  trail (both paths).

**Fixed**
- priority inputs (#594 #596): per-claim depends_on feeds the graph when
  claim_deps is empty; register PROVEN claims form the terminal set when
  _INDEX has no rows — fresh workspaces regain ranking gradient.
- done-requires-artifacts (#550): bare done is a violation, full stop (user
  ruling 2026-08-25: no legacy path) — the C-400 hole closed at W-15.
- tool-first honesty (#630): marker must name the MATCHED tool (or
  none+reasoning); post-side verify_tool_catalog resolves cited names.
- gate numbering (#563): QUICK_GATES + --quick stable selector;
  release_check_selfcheck fails loudly on stale workflow gate ids.
- two-settings-levels doc (#589): README Internals section derived from
  HOOK_DEPLOYMENT_TARGETS (registry named; HOME exclusion stated).

### Hygiene (ponytail, adjudicated)

- PendingDecisionList → function pair (#582); Classification → NamedTuple
  view (#581); ledger writer → stdlib WatchedFileHandler, format
  byte-identical (#584); the 8 kunglao-* entries share _entry.run (#585,
  limited wave — the 89-file sweep defers to v0.2).
- Closed as refuted by code facts: #578 #579 #583 (dead-code claims whose
  cited targets have live callers / don't exist); #620 Gap B wontfix (hash
  measures change; drift measures stagnation).
- #580 (StrEnum) deferred to v0.2: blocked on the Python 3.10 floor.

### Policy Decisions

- #550: no legacy-compat for bare done (user ruling 2026-08-25).
- #593/#598: init NEVER self-activates (both by-design red lines preserved;
  mechanical handoff instead — adjudication (b)).

### Round 3 — Post-Release Follow-ups (v0.1.3 milestone review)

**Added**
- anomaly detection layer (#663): `scripts/anomaly_detector.py` —
  BaselineCorpus dataclass, score_fact (lexical-only when no claim
  context), scan_anomalies (full 3-dim max per design.md D1), check_fact_anomaly
  single-fact consumer, _load_baseline (RE-library refs + 2 future
  sources, fail-open per design.md D5), CLI. `scripts/convergence_check.py`
  gains `ANOMALY_DETECTED` DRAIN event between GLOBAL_CONTRADICTION and
  DRAIN_CLEAN (per design.md D4) — anomalies surface as `BLOCKED` with
  fact_id + score + top_dimension. `scripts/lint_facts.py` schema bump:
  `VALID_BOUNDARY_TYPE` + `EMPTY_GATE_TYPES` add `'anomaly'`; `ACTIVE_SCHEMA_REV`
  1 → 2 (additive per design.md D3); template + drift test bumped in lockstep.
- references/anomaly-baseline.md: baseline corpus sourcing (RE-library refs +
  prior samples + operator `baseline_corpus:` config), fail-open semantics
  per design.md D5, operator tuning knobs (`anomaly_threshold` in
  `analysis_state.txt`), maker-checker boundary (design.md D8 — anomaly is
  observation, not verdict demotion; co-resident note via
  `_write_anomaly_note` for analyst review).
- tests/test_anomaly_detector.py: 9 RED → GREEN cases (RED1-RED6 unit,
  RED7 convergence_check integration, RED8 claim_migrator invariant,
  RED9 schema bump). Schema bump consistency for
  tests/test_fact_schema_rev_536.py and templates/fact-frontmatter.md.
- hypothesis seed layer (#662): `scripts/hypothesis_seeder.py` — mechanical
  idempotent PQ scaffold seeder (every task_spec primary_question gets an
  open `H-NNN` with `pq:<qid>` body marker, `candidates: []`,
  `claim_id: C-PENDING`; marker lives in the body because HypothesisStore
  rewrites drop unknown frontmatter keys — design D2). Wired into
  `digest_build.build_digest` before sec_g (fail-open): seeding is
  mechanically enforced at EVERY cold start, closing the "LLM must
  remember to seed" gap. `scripts/convergence_check.py` DRAIN gains
  `OPEN_HYPOTHESIS_AT_CLOSE` between NOTE_LAYER_GAP and
  DISCOVERY_UNCONSUMED (#443 additive) — unadjudicated competing
  explanations at delivery BLOCK convergence pending refute/supersede
  (#528 terminal paths); decide() output gains open_hypotheses +
  open_hypothesis_count (dict shape, mirrors anomalies).
- tests/test_hypothesis_seeder.py: 8 RED → GREEN cases (RED1-RED4 seeder
  unit, RED5 digest seed-then-list integration, RED6/RED7 convergence DRAIN
  gate, RED8 scaffold shape). Fold-in cleanup: openspec change
  issue-663-anomaly-detection archived post-#666-merge.
- intent-aware strategic stopping (#664): `scripts/completion_gate.py`
  gains exit code 4 (`INTENT_UNMATCHED`) — at the would-be-PASS point
  (items closed, defers signed), the gate re-extracts content anchors
  from `task_text` via #54 F1's `_extract_anchors` and verifies each
  appears in some `task_spec.yaml` primary_question id or question text.
  ≥1 unmatched anchor → exit 4 with the unmatched anchors named in the
  reason. Precedence 3 > 2 > 1 > 4 > 0 (intent check fires only at the
  would-be-PASS point — item-level defects and unsigned defers strictly
  outrank it; design.md D1). All paths fail-open (D4): no `workspace_path`,
  no `task_spec.yaml`, malformed YAML, empty PQs, zero anchors, anchor-
  module import failure → check skipped, oracle verdict unchanged. CLI
  verdict map gains `4: "INTENT_UNMATCHED"`; `hooks/completion_gate.py`
  docstring exit-code table gains the 4 row (D5 — shim logic already
  blocks on every non-zero exit, so no propagation change). Two new
  helpers: `_pq_coverage_text(task_spec)` schema-tolerant corpus builder
  (handles canonical `{id, q}`, legacy one-key `{Q1: text}`, plain-string
  items, top-level mapping) and `_intent_unmatched(oracle, task_text)`.
- tests/test_intent_aware_completion.py: 8 RED -> GREEN cases (RED1
  unmatched-anchor returns 4 + names anchors, RED2 covered anchors ->
  PASS unchanged, RED3 no workspace_path -> skip, RED4 no/malformed/
  empty-PQ task_spec -> skip + no crash, RED5 unresolved items outrank
  intent, RED6 CLI JSON verdict label).
- apkid pre-scan at android intake (#669): `scripts/apkid_scanner.py`
  (NEW) - T1-second YARA-based fingerprint scan before jadx dispatch.
  Wraps `apkid scan --json <apk>`, writes `evidence/apkid.json` with the
  schema `{tool, version, target, scanned_at, findings,
  summary{packer,compiler,obfuscator,anti_vm,anti_debug,total},
  status, reason}`. Fail-open on every layer: missing binary ->
  `status:unavailable`, non-APK input -> `status:error` (no crash).
  `scripts/toolchain.py` FIXES + `_STATIC_NEXT_ACTIONS` gain `apkid`
  (FIXES line is the FIRST tool entry to embed its upstream URL inline
  - `https://github.com/rednaga/APKiD` - addressing the user's "agents
  have to search for tool addresses" feedback). `scripts/hypothesis_seeder.py`
  gains `seed_apkid_candidates(ws)`: the "system optimum" wire per
  the user's directive - apkid output feeds the EXISTING hypothesis
  pipeline (pq-family competitor_groups get `apkid:<category>:<rule>`
  candidates appended when their PQ id/question matches packer /
  compiler / obfuscator / anti-debug / anti-vm tokens), not a parallel
  pipe. Idempotent, fail-open. `scripts/kunglao_init.py` android flow
  Phase 0 invokes the scanner after target alignment, before #670's
  apk_mem_gate.
- tests/test_apkid_scanner.py: 7 RED -> GREEN cases (RED1 happy-path
  parse + summary rollup, RED2 missing-binary -> unavailable, RED3
  non-APK -> error, RED4 schema shape always populated, RED5 toolchain
  registers apkid, RED6 hypothesis_seeder appends candidates,
  RED6b no apkid file -> noop).
- memory-gated jadx dispatch (#670): `tools/static/apk_mem_gate.py` (NEW)
  - T1 memory-aware estimator. Calibrated against a single data point
  (395MB APK / 12GB heap / ~10h GC-thrashed completion): `est =
  max(4GB, 50 * dex_bytes_total)`, `budget = 0.65 * avail_gb`. Verdict
  selects dispatch path: `jadx-ok` (budget >= 1.5*est), `targeted-jadx`
  (est <= budget < 1.5*est -> baksmali xref + per-class jadx), `smali-only`
  (budget < est -> baksmali + smali semantic), `refuse` (JAR target -
  pure Java has no smali fallback; analysis cannot proceed). Writes
  `evidence/apk_mem_gate.json` ALWAYS (fail-open, operator audit). Stdlib
  memory detection: ctypes GlobalMemoryStatusEx (Windows) / sysconf
  (POSIX) with 4GB fallback on failure. Operator escape hatch via
  `analysis_state.txt` (`apk_mem_override=jadx|baksmali|refuse`).
  Calibration basis string travels in JSON per #54 numeric-fidelity.
- `tools/static/baksmali_index.py` (NEW) - replaces gitnexus's role for
  DEX (gitnexus is Java-only). Calls `baksmali list --format json` for
  class enumeration + per-class `baksmali xref` for call graphs.
  Emits `evidence/smali_index.json` in gitnexus-shape compat
  (`{tool, version, target, classes:[{name, methods:[{name, signature,
  xrefs:{calls, called_by}}]}], scanned_at}`) so downstream consumers
  (#663 anomaly, #662 hypothesis) don't branch on tool identity. The
  "system optimum" wire per user's "思考当前体系怎么最优的发挥作用"
  directive.
- `scripts/toolchain.py`: FIXES + `_STATIC_NEXT_ACTIONS` gain `baksmali`
  (URL `https://github.com/baksmali/smali/releases` embedded inline -
  second tool entry after #669 apkid to carry upstream URL; addresses
  user's "agents have to search for tool addresses" feedback).
- `scripts/convergence_check.py`: `Event` enum gains `JADX_INFEASIBLE`
  (intake-level, NOT in DRAIN - the REFUSE verdict aborts intake BEFORE
  convergence starts; name exists for observability consistency).
- tests/test_apk_mem_gate.py: 9 RED -> GREEN cases (RED1 small APK +
  9.5GB avail -> jadx-ok, RED2 large APK + 1GB avail -> smali-only,
  RED3 90MB APK + 7.5GB avail -> targeted-jadx, RED4 JAR -> refuse
  regardless of budget, RED5 dex_bytes_total = sum of dex sizes not zip
  overhead, RED6 avail_gb fallback on detection failure, RED7
  calibration_basis always populated, RED8 evidence JSON written even
  on REFUSE, RED8b operator override apk_mem_override=jadx).
- tests/test_baksmali_index.py: 4 RED -> GREEN cases (RED1 baksmali
  missing -> noop + warning, RED2 schema shape, RED3 gitnexus-shape
  compat, RED4 per-class xref fail-open).
- CI release-check restoration (dev branch red since #661; 10 root-cause
  classes fixed in one pass):
  1. kunglao-init.py `from _entry import run` shadowed the module's own
     business run(ws, force=...) -> alias _entry_run (#660 dispatcher
     regression; ~180 cascade failures across init/toolchain/target tests).
  2. hook_activation.register_hooks missed the orchestrator_tool_guard.py
     writer call while the registry + self-check expected it (#608 landing
     gap) -> PreToolUse/Bash entry now written.
  3. decide() frozen anchor re-pinned at 619ebd3 after the intentional
     #662/#663/#670 semantics additions (31 cases;
     tests/decide_anchor_619ebd3.json machine-generated; c5cb1ae anchor
     recoverable from history).
  4. Event vocabulary pin gains STUCK_WORKERS_PRESENT (#595),
     OPEN_HYPOTHESIS_AT_CLOSE (#662), ANOMALY_DETECTED (#663),
     JADX_INFEASIBLE (#670).
  5. release-manifest.yaml declares the #670 tools (apk_mem_gate.py,
     baksmali_index.py) + both gain the #317 UTF-8 stdout guard.
  6. EMIT_ACTIONS gains apkid_candidates/hypothesis_seed (#662/#669),
     reject (#233 env gate face), renew (#619 TTL face).
  7. scripts/README.md catalogs _entry/anomaly_detector/apkid_scanner/
     hypothesis_seeder; references/_INDEX.md + _INDEX.yaml gain
     anomaly-baseline.md + mechanisms.md; ext index regenerated.
  8. Stale test pins brought to current contracts: wire-up entries 10->11
     + registry set + env_check fixture + heartbeat REGISTRY tuple +
     worker_budget status_defs import + hooks/lib_kunglao MECHANISMS
     metadata (#446) + _entry.py docstring discipline + dedup_319
     scanner exemption + digest_sec_g premise (no-PQ workspace) +
     proven_backstop module-family scan + suite_health golden mtime
     refresh (#595 stuck-scan determinism doctrine).
  9. v012/exit4 replays use sys.executable (the #457 hard pin
     /usr/local/bin/python3.11 broke the 3.10 job with PermissionError).
  10. worker_budget.py shim: order-robust path bootstrap (moves hooks/
     dir to sys.path FRONT — the conditional insert left scripts/
     winning and lib_kunglao.scan_active_workers unresolvable
     standalone) + explicit _claim_statuses re-export (underscore names
     skip star-import) + scripts/kunglao_export.classify platform-stable
     (as_posix + absolute paths skip the scratch-zone check — the CI
     /tmp misclassification).

## [0.1.2] - 2026-08-23

### Added
- workspace CLAUDE.md template — progressive disclosure (37-line core + 9 pointers) + 6 carrier memory contract + loop mandatory block (#535)
- Version stamp system — kunglao_template_version three-carrier stamp + fact schema_rev + upgrade detection (#536)
- Workspace carrier contracts — eager scaffold 9 carriers + .workspace-manifest.json + _INDEX unified schema + scratch/ free-zone (#538)
- Skill package contract text fix — SKILL.md:112 contradiction rewrite + global rules channel dispatch (#537)
- Enforcement persistence — SessionStart re-arming + always_arm() + liveness predicate split + Stop gate always armed + MCP matcher (#533)
- Observability lifeline — init full-path log + .init-report.json + 19 silent modules wired (#534)
- Rollup write-loop automation — claim terminal state triggers lessons/outcome writes (#524)
- Lessons nursery two-stage lifecycle — draft → active + trigger_precision gate (#525)
- Lessons utility telemetry + deprecate governance — CBM quartet + tombstone (#526)
- Dispatch context block mechanization — worker channel injection + verifier BLIND hard exclusion (#527)
- Hypothesis persistence + restart rehydration — hypotheses/ + digest sec_g + state_anchor structured pointer (#528)
- Strategy convergence four metrics — regret / cost-to-slope / P(faster|hit) / competence (#529)
- Workspace export tool — zone-based routing (contract carriers / evidence / scratch) + manifest + verify (#540)
- v0.1.2 milestone audit four-piece set — white-box + black-box + log + regression (#539)

### Changed
- Tool-search three sources — mcp_probe enumeration + dispatch acceptance + artifact→evidence e2e (#515)
- Mechanism registry + retirement precedent (#446)
- Quick fixes baseline test failures (#457)

### Fixed
- Init deployment: .claude/settings.json deadlock (hooks always skip), agents zero-deployment, .mcp.json empty scaffold (#478)
- Deployment coverage: pkg_detect + INSTALL_PLANS 5→17 full coverage (#477)
- Environment drift detection + bounded repair ladder (#475)
- Toolchain probe upgrade to capability (#474)
- Hook chain final gates: task-oracle registration + fingerprint table (#473)

### Changed (coverage policy alignment, #564)

- **Policy decision**: coverage stays as **OBSERVATION**, not a
  release gate — `#463` 4-gate quality framework is reaffirmed and
  `pytest.ini`, `pyproject.toml`, and `.github/workflows/release-check.yml`
  are explicitly aligned on that stance. The buffered floor asserted
  inside `tests/test_coverage_floor_520.py` (FLOOR=60, target 75)
  remains as a normal pytest assertion, **not** via `--cov-fail-under`,
  so the `#463` config comment stays literally true while `#520` ships
  its ratchet.
- `tests/test_coverage_policy_564.py` — drift guard: enforces
  (a) no `--cov-fail-under` anywhere in `pytest.ini`,
      `release-check.yml`, `pyproject.toml`, or `ci.yml`;
  (b) every policy truth source (pytest.ini / release-check.yml /
      pyproject.toml / test_coverage_floor_520.py) carries an
      `OBSERVATION` marker, so a future edit that flips only one file
      fails the integration test. Without this guard the four
      sources could drift silently; with it the choice is conscious
      or loud.
- `pyproject.toml` dev-deps comment `#463` block updated to spell
  "observation" so the three truth sources share one word.

### Added (hypothesis persistence + restart re-hydration, #528)

- `scripts/hypothesis_store.py` — the hypothesis layer carrier over
  `hypotheses/` (`H-*.md`: id / claim_id / competitor_group / candidates /
  status): parse + strict state machine open -> refuted (requires
  `refuting_fact_id`) | superseded (requires `superseded_by`), terminal
  states never reopen, `open -> open` idempotent for cold-start rehydrate;
  unparseable files are skipped so a corrupt hypothesis never blocks a
  reader
- digest `## sec_g — open hypotheses` (scripts/digest_build.py): the
  cold-start digest lists OPEN hypothesis pointers only (never the
  motivation body, capped rows, never reads notes/); absent when there
  are none — pre-#528 workspaces keep the exact six-section digest; the
  section build is fail-open (a hypotheses-layer crash degrades the
  digest to six sections, it never blocks cold start)
- cold start is now the 9-file read: `runs/digest.md` joins
  references/cold-start-contract.md as file 9, read via the
  kunglao-resume read-only face
- state_anchor `hyps=` segment (hooks/state_anchor.py): structured
  open-hypothesis pointers inside the existing 500-char anti-narrative
  anchor; `build_anchor_payload()` exposes them as
  `[{"claim_id", "hyp_id"}]` dicts
- resume brief (#466 face) surfaces `runs/digest.md` data-age row + a
  `hypotheses` block (open_count + pointers) — read-only, fail-open
- `scripts/notes_writer.py` — notes/ result-layer writer with the
  supersedes-chain contract: a same-claim correction MUST declare
  `supersedes: <prior-id>`, the prior note is never modified, a
  correction is always written `verify_status: pending` (never inherits
  the old stamp), and a pointer at a nonexistent note is rejected
- write_guard (#532 note leg) gains Leg 3: the note post-image is
  adjudicated against the chain contract on every Write/Edit — a
  chainless same-claim correction (the AES->ChaCha20 silent-overwrite
  shape), a fake chain pointer, or an inherited stamp is BLOCKED
- hypotheses/ README stub (kunglao-init CARRIER_READMES) updated from
  "#528 owns the real writer" to the landed writer + state machine;
  docs/workspace-manifest.md hypotheses/ row now names
  hypothesis_store.py, digest sec_g, and the state_anchor segment

### Added (environment drift detection + bounded repair L1, #475)

- env-state single source of truth: `runs/env-state.json`
  (`per_capability: {status, last_probe_ts, detail}, written_by, ts`),
  written by `scripts/env_state_probe.py` — liveness-subset probes only
  (TCP/adb-forward/port reachability; capability trials never run on the
  periodic path, #474 contract)
- heartbeat_tick step 8: the env probe is bound to the tick — the only
  mechanically-enforced periodic (#475 design argument) — so env freshness
  is guaranteed by construction, not by a new timer; probe failure never
  fails the tick
- worker_budget `check_env_fresh` dispatch gate (pure file read, <5ms):
  missing env-state FAIL_OPEN + hint; explicit FAIL ∩ the dispatch's
  tier/tools REJECT with L1 repair guidance; entries older than 2×TTL
  (60 min) REJECT with the self-heal hint "run one heartbeat_tick"
- kunglao-monitor `env_drift` advisory field (OK/DRIFT/NO_DATA + drifted
  capability list) — #88 contract preserved: advisory only, never gates a
  tick; tick-output.json gains the optional `env_drift` property (required
  set unchanged)
- `scripts/env_repair_l1.py`: bounded deterministic L1 repair
  (adb-reconnect / vm-rediscover / mcp-rehandshake) — idempotent, safe
  no-op without substrate, rewrites env-state on success; L2/L3 out of scope
- tool_error_policy wiring (#309 debt paid): worker_budget post_check now
  counts per-tool consecutive failures (runs/tool-errors.json) and applies
  the WARN=3/DISABLE=5 hysteresis — warn → stderr advisory,
  disable_escalate → escalation + env-state capability marked failed;
  consumer count 0 → 1 (mechanical)

### Changed (probe capability tiers, #474)

- toolchain probes now carry an explicit probe tier — `presence`
  (file/registry), `liveness` (side-effect-free handshake: TCP, adb
  forward + recv, raw JDWP), `capability` (real trial run) — exposed as a
  per-item `probe` field in `--json` output (scripts/toolchain.py)
- decompiler check is honestly three-state: a registered ghidra/ida-pro-vm
  MCP name or a present CLI binary is now WARN "capability unverified"
  (previously a fake PASS satisfying the HARD init gate on registry
  evidence alone — a Python probe cannot reach into the MCP session);
  PASS requires the analyzeHeadless import trial, available only under the
  new `--capability` flag / `check(..., caps=True)` (minutes-long, init/
  on-demand only; the default path runs presence+liveness only)
- new android `jdwp_debug` WARN informational check (optional capability, 2026-08-19 user ruling): `adb jdwp` pid discovery +
  `adb forward tcp:8700 jdwp:<pid>` + the raw 14-byte JDWP-Handshake echo
  (never `jdb -attach` — attach holds/resumes the target); jdb enters the
  android matrix docs (CLAUDE.md golden) as the interactive driver



### Fixed (platform de-hardcoding, #409)

- analyzeHeadless path is now platform-correct in scripts/toolchain.py
  (windows/linux/android manifests) and scripts/env_check.py: Windows
  resolves `support/analyzeHeadless.bat`, macOS/Linux resolve
  `support/analyzeHeadless` (no extension) — the previous hardcoded .bat
  constant made the probe always False on POSIX (observed on macOS with
  GHIDRA_HOME set), so Ghidra was never detected there. New shared resolver
  `scripts/platform_paths.py` (#409)
- venv python in scripts/env_check.py check ⑤ now probes the SKILL-root
  venv (`uv run --project <skill_root>` is authoritative, #389) resolved by
  sys.platform — `Scripts/python.exe` on Windows, `bin/python` on POSIX —
  instead of the workspace `ws/.venv/Scripts/python.exe` Windows layout that
  always FAILed on macOS (#409)
86b479a (fix(#409): platform de-hardcoding — analyzeHeadless(.bat) + skill-root venv by sys.platform)

### Fixed (kunglao-init exit-code semantics, #414)

- kunglao-init exit paths audited against the documented RC constants
  (0/1/2/3/4/5) and pinned by a per-mode RC matrix test: argparse usage errors
  no longer exit 2 (which collided with RC_FATAL_VERIFY) — normalized to the
  documented generic RC_ERROR=1; the template-defect cleanup path now removes
  exactly this run's scaffold entries (it previously passed no created
  manifest, so nothing was cleaned and this-run artifacts were mislabelled
  "pre-existing"); the misleading "existing content is always preserved"
  comments now state that cleanup removes only this run's artifacts while
  pre-existing content is never deleted. SKILL.md / kunglao-init-worker /
  README branch on the documented RCs, including the previously-undocumented
  exit 3 (agent-teams flag reject) (#414)


### Added (subcommand UX + guided entry, #413)

- The plugin moved to the official `skills/` subdirectory layout (#413).
- `/kunglao-agent:init` skill — workspace initialization flow, argument-hint `<workspace> [--type windows|linux|android]` (#413).
- `/kunglao-agent:analysis` skill — convergence-loop entry, argument-hint `<workspace>` (#413).
- `/kunglao-agent:help` skill — subcommand usage list (#413).
- The full convergence contract moved to `skills/kunglao-agent/SKILL.md` (#413).
- The root `SKILL.md` is now a thin command router (#413).
- `/kunglao-agent` with no arguments prints a subcommand menu and WAITS — never silently runs (#413).
- An unknown subcommand prints the menu plus `unknown: <x>` (#413).
- `argument-hint` frontmatter on every skill, shown at autocomplete (#413).
- README gained a Command Reference table covering all four commands (#413).
- Contract tests for the subcommand routing + menu behavior, TDD RED-first (#413).
- `release-manifest.yaml`, `structural_check.py`, `check_global_rule_subset.py`, and docs repointed to the moved main skill (#413).
>>>>>>> 3eca5a0 
(feat(#413): subcommand UX + guided entry — skills/ layout, menu, hints, README table)

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
### Fixed (init workspace-path shape, #411)

- `kunglao-init` now validates the workspace path shape before writing
  anything: a sample directory passed as the workspace — either a directory
  named `bin/`/`bins/` (e.g. `~/Downloads/Sysdiag/bin`) or one containing a
  `bin/` subdir with no `bins/` — is refused with guidance (exit 6,
  `RC_PATH_SHAPE`) and ZERO files written; `.claude/` and every scaffold
  entry stay under the workspace root. The type sniffer / sample detector
  read `bins/` (plural) only, never `bin/`. Valid workspace roots (`bins/`
  or `claim-register.yaml`) and creatable directories proceed unchanged.
  Tests: path-shape cases in tests/test_kunglao_init.py (#411)

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
