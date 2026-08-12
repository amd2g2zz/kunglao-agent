# Plan: Batch 5 — Absorption (C8-C13) + Dead-Code + Remaining Defects/Arch-Debt Backlog

## Summary

`absorption-research-round2.md` catalogued 4 dimensions kunglao-agent had not yet acted
on: external absorption candidates (C8-C13), implementation defects (F1-F15), architecture
debt (D1-D17), and dead/unwired mechanisms (10 classes). Batch 4
(`batch4-reposition-re-only.plan.md`) only covers the repositioning correction (drop CTI/
verdict-attribution). **This plan is the missing piece**: it turns the rest of the
round-2 catalog into a filed, executable backlog, after removing everything that batch 4
already supersedes and everything already shipped in issues #95-#99.

## User Story

As the person maintaining kunglao-agent,
I want the absorption/cleanup findings from round 2 turned into concrete issues instead of
sitting in a research doc,
So that the 9 dead gates, the remaining real defects, and the external capabilities worth
adopting actually get built or explicitly closed as won't-fix.

## Problem → Solution

**Current**: `absorption-research-round2.md` exists as a research artifact. Of its
findings, only 5 P0 items shipped (#95-#99, verified via `git log`: commits 447ef17,
5817fdd, 74d3025, 035bea6, 9f9c9d6). Everything else — C8-C13, the 9 unwired gates, ~10
remaining F-defects, ~13 remaining D-arch-items — has no issue, no plan, no owner.

**Desired**: every surviving finding (after subtracting shipped items and batch-4-owned
items) is either (a) filed as an issue in one of 4 tiers below, or (b) explicitly marked
NOT-BUILDING in this plan with a one-line reason, so nothing silently falls through.

## Metadata

- **Complexity**: XL (spans ~25 surviving findings across 4 stages; each stage ships as its own mini-batch of parallel issues, mirroring batches 1-4)
- **Source PRD**: `absorption-research-round2.md` (this repo)
- **PRD Phase**: N/A — round-2 research doc has no phase field, this plan supersedes it as the execution tracker
- **Estimated Files**: varies per stage (see tables) — this plan is the backlog, not itself a code change

---

## Verified baseline (what's already done — do not re-file)

| ID | Finding | Shipped as | Commit |
|---|---|---|---|
| F1 / D2 | hooks/ didn't import `status_defs.TERMINAL` (5-value local copy) | #95 | `9f9c9d6` |
| F2 | `decide-output.json` schema didn't match `decide()` output | #97 | `035bea6` |
| F8 | `record_event` read-modify-write race | #96 | `74d3025` |
| F15 / D6 | maker-checker FAIL_CLOSED triple + degrade deadlock | #98 | `5817fdd` |
| D14 | global rule missing VM-only HOST_FORBIDDEN_TOOLS | #99 | `447ef17` |

Verified live in the repo (not just claimed): `hooks/worker_budget.py:59` imports
`TERMINAL` from `status_defs`; `scripts/kunglao_record.py:140-148` uses
`os.O_APPEND`; `schemas/convergence-check-output.json` exists alongside
`decide-output.json`; `rules/kunglao-convergence-loop.md` §7 has the VM-only clause
(confirmed earlier this session).

## Superseded by batch 4 (do not re-file separately)

- C6 "补 custom VM/WASM/RISC-V + specific tools" — narrowed in batch 4/this session's
  correction to RE-core-only, no firmware/game; the tool-absorption part (Qiling/Triton/
  rr/r2frida) is folded into **Stage-5 C6** below, scoped correctly this time.
- Any CTI/verdict/attribution-shaped finding — batch 4 owns all of that; nothing here
  duplicates it.

---

## Stage inventory (the actual backlog)

### Stage 1 — Structural (R1-R7, from the skill-audit, not round-2 but same backlog gap)

| ID | Finding | File(s) | Fix |
|---|---|---|---|
| R1 | SKILL.md is 560 lines, ~200 behavior + 360 reference, fails `test_skill_lte_500_lines` | `SKILL.md` | Split: keep dispatch contract + convergence loop + hard prohibitions in SKILL.md; move the local-defaults table, module inventory prose, and any narrative already duplicated in `references/*.md` out to reference-only |
| R2 | 36 files hardcode `C:/Users/hr/.claude/skills/kunglao-agent/` — breaks on any other machine | `SKILL.md`, `scripts/*.py`, `references/*.md` | Replace with `${CLAUDE_SKILL_DIR}`-relative resolution (or equivalent — check whether the harness exposes a skill-root env var; if not, resolve via `Path(__file__).parent` inside scripts, and drop the absolute path from prose, replacing with "the skill's `scripts/` directory") |
| R3 | dir layout is flat, no `.gitignore` hygiene doc | repo root | Confirm `.gitignore` covers `bins/`, `analysis_space/`, `.venv/`, `runs/*` scratch — audit against the security constraints already in force this session, file gaps only |
| R4 | `references/` has no index/TOC — 30 files, no map | `references/` | Add `references/INDEX.md` (one line per file: purpose + when to read) — mirrors skill-creator's progressive-disclosure guidance |
| R5 | no `LICENSE`, no `AGENTS.md` | repo root | Add both if the repo is meant to be shared/portable (per skill-repo-skill manual); if intentionally private-only, mark NOT-BUILDING here explicitly instead of leaving unfiled |
| R6 | no `evals/evals.json` | repo root | Add per skill-creator's schema (see `references/schemas.md` read this session) — at minimum 3 evals covering: convergence-loop dispatch, maker-checker verify, and (post-batch-4) the new verdict correctness/completeness check |
| R7 | 42+ openspec changes accumulated, no lifecycle tracking (D8 duplicate — merge) | `openspec/changes/` | Decide: archive completed changes per `openspec archive`, or accept as permanent history — file as one decision issue, not a code change |

### Stage 2 — Dead-code / unwired mechanisms (10 classes → disposition each)

| Class | Item(s) | Verified state | Disposition |
|---|---|---|---|
| 1 (HIGH) | 9 gates never called by any hook or SKILL.md flow: `plan_drift_detector.py`, `stale_blocker_prune.py`, `claim_expiry.py`, `provenance_gate.py`, `report_consistency_check.py`, `explore_gate.py`, `failure_analysis_gate.py` (non-hook path), `premature_termination_detect.py` (non-hook path), `ask_for_direction_gate.py` (non-hook path) | Confirmed present in `scripts/` this session (`ls scripts/` matched all 9) | **Per-gate decision, not blanket**: `failure_analysis_gate.py` and `premature_termination_detect.py` are documented in SKILL.md as manually-invoked (not hook-driven by design — SKILL.md explicitly calls them out as "run when X happens"), so those 2 are **NOT dead — just not hook-wired, which is intentional**. The other 7 (`plan_drift_detector`, `stale_blocker_prune`, `claim_expiry`, `provenance_gate`, `report_consistency_check`, `explore_gate`, `ask_for_direction_gate`) need a real per-gate call: is it referenced anywhere in SKILL.md prose as "run this when"? If yes → it's manual-by-design, downgrade to LOW. If no reference anywhere → wire into the matching hook (`worker_budget.py` pre/post) or delete. File as 7 small issues, one per gate, each starting with "grep SKILL.md + references/ for this script's name — if zero hits, it's truly orphaned; wire or delete." |
| 2 (MED) | 6-8 openspec changes `planned` with no implementation | `openspec/changes/*/tasks.md` | Fold into R7 (Stage 1) — same lifecycle-tracking decision |
| 3 (MED) | eval (`kunglao_eval.py`) not wired into CI | `.github/workflows/release-check.yml` | Confirmed: workflow greps show no `eval` step. Add a CI step running `kunglao_eval.py --oracle-selfcheck` (the existing self-check mode, not a slow full L2 red-team run) so at minimum eval regressions are caught |
| 4 (MED) | `verdict-redteam` agent never dispatched by SKILL.md routing | `agents/verdict-redteam.md` | **Batch-4-adjacent**: once batch 4's Task 3 rewrites `verdict-redteam.md`, wire its dispatch into the convergence-loop's post-convergence verdict step (SKILL.md "verdict (verdict-scorer agent, optional post-convergence)" line) so the blind-check actually runs, not just exists |
| 5 (LOW) | `orchestrator-proactive-loop` learned skill never recalled by SKILL.md/hooks | `~/.claude/skills/learned/orchestrator-proactive-loop.md` | Either add an explicit reference in SKILL.md's self-recovery behavior (#1) pointing to it, or archive it as superseded by the now-mechanical convergence gates (#95-#99 made several of its recommendations structural) |
| 6 (MED) | `outcome_capture` (#35) writes OUTCOME ledger rows but `priority.py` never reads them | `scripts/priority.py`, `scripts/outcome_capture.py` | **Verified this session**: `grep -n "OUTCOME\|outcome_capture\|aggregate_reward" scripts/priority.py` → zero hits. Real gap. Wire `aggregate_reward()` output into `rank_claims()`'s value term (or a 5th weighted factor) so claims with a track record of red-team-confirmed outcomes get prioritized differently than claims with no history |
| 7 (LOW) | `memory_capture` listed in `ALL_HOOKS` with no backing implementation | `scripts/hook_activation.py` (`ALL_HOOKS` list) | Either implement the stub or remove the phantom entry — 1-line fix either way, file as a single small issue |
| 8 (LOW) | `confidence_schema` — zero runtime imports outside its own test | `scripts/confidence_schema.py` (if exists) or equivalent | Confirm it's truly orphaned (grep repo-wide for imports); if genuinely unused, delete; if it should back the `confidence_band` field used throughout (PROVEN-INITIAL/FULL), wire it as the validator |
| 9 (LOW) | 18 marginal scripts with CLI/tests but no live-loop caller | `scripts/*.py` | Audit pass: for each, one line — "called by hook X" / "called by SKILL.md flow Y" / "orphaned, candidate for deletion." No code change, just a disposition table added to this plan on completion |
| 10 (LOW) | re-library read by only `kunglao-worker` agent | `references/re-library/` | Not a bug — by design per round-2's own correction. **Superseded by Stage 5 C9** (structural CI gate for re-library) — no separate action here |

### Stage 3 — Remaining implementation defects (F3-F14, minus F1/F2/F8/F15 already shipped)

| ID | Finding | Severity | Fix |
|---|---|---|---|
| F3 | 3-layer `decide` (kunglao-decide.py / kunglao.py cmd_decide / convergence_check.py) role confusion, schemas differ, "byte-identical" claim is false | MED | Either collapse to one canonical `decide()` with the other 2 as thin CLI wrappers (mirrors the "intentional CLI wrapper + module" pattern already corrected in round 2 for kunglao-verify), or document the 3-way split's actual purpose if it's intentional and just needs a truthful docstring |
| F4 | 16 `test_*.py` files live in `scripts/` instead of `tests/`; `pytest.ini` has no `testpaths` | LOW | Move files, add `testpaths = tests` to `pytest.ini`, confirm CI picks them up either way (they may already run via glob — verify before assuming this is broken) |
| F5 | `priority.py::rank_claims` has no regression tests beyond `test_priority_ratio.py` (confirmed: only that one file exists under `tests/`) | MED | Add `tests/test_rank_claims.py` covering leverage-v2 sigmoid, the tier gate, and the Stage-2-item-6 outcome-weighting once that lands |
| F6 | `DISPATCH_VERIFIER`→`SATURATED` boundary text is misleading when partials+0-free-slots | LOW | One-line message fix in `convergence_check.py`'s human-readable output |
| F7 | `_note_layer_gaps` spec deviation (DESIGN.md already notes this as known, not hidden) | LOW | Already self-documented in DESIGN.md's top NOTE — no code change needed, just confirm the NOTE is still accurate after any Stage-1 SKILL.md edits touch nearby text |
| F9 | `_set_claim_status` line-parsing is fragile (flow-style YAML / missing spaces / partial-ID match) | MED | Replace ad-hoc line parsing with a real YAML round-trip (load, mutate, dump) if not already doing so — check current implementation before assuming a rewrite is needed |
| F10 | `fact_id` has 3 inconsistent formats (`F-NNN` / `F<16hex>` / `F<NNN>-<slug>`) | LOW | Pick one canonical format going forward (recommend `F<NNN>` per the majority convention seen in `facts/F<NNN>.md` naming), add a migration note for existing fact files, do not force-rename historical facts |
| F11 | `kunglao-decide` exception path writes a poison ledger row (`open_count=-1`) causing false flatline/churn signals | MED | Fail closed instead: on exception, skip the write entirely and surface the error, rather than writing a sentinel value that downstream health checks might misinterpret as real data |
| F12 | `blind_gate.py::record_dissent` uses deprecated `utcnow()` | LOW | `datetime.now(timezone.utc)` — mechanical fix |
| F13 | failure-modes F1-F18 doc covers only LLM behavior, not script-implementation bugs like F1/F8 (this round's own findings) | LOW | Add a short "implementation-bug class" section to `references/failure-modes*.md` referencing this backlog as the record, so future audits don't have to rediscover the same gaps from scratch |
| F14 | `convergence_check.py` returns exit code 64 on missing-workspace, outside the documented 0-4 range | LOW | Document exit 64 explicitly in SKILL.md's decision table, or remap to a documented code — pick one, don't leave it undocumented |

### Stage 4 — Remaining architecture debt (D1, D3-D5, D7-D13, D16-D17; D2/D6/D14 shipped)

| ID | Finding | Fix |
|---|---|---|
| D1 | 3 contract sources (SKILL/DESIGN/global-rule) with no mechanical arbiter; global rule known-incomplete | `check_global_rule_subset.py` (shipped in #99) already covers the global-rule-subset direction — extend or confirm it also checks DESIGN.md isn't silently contradicting SKILL.md on anything load-bearing (SKILL.md already states it wins on conflict, so this may already be resolved by policy — verify before filing as still-open) |
| D3 | hook chain is non-linear (12 sub-checks, 5+ subprocess per dispatch, slow on Windows); exit-code collisions between hooks (`worker_pulse` BLOCKED=2 vs `worker_budget` REJECT=2) | Consolidate exit-code space (one enum shared by all hooks) — this is a real correctness risk (ambiguous exit code), not just a performance one; prioritize the exit-code collision fix, treat the subprocess-count perf issue as a separate lower-priority follow-up |
| D4 | SKILL.md SNR — folds into R1 (Stage 1), no separate action |
| D5 | convergence exit codes are advisory, not hook-mandatory (F1's root cause pattern) | Audit whether any *other* exit code besides the already-fixed DISPATCH/STALLED/SPINNING (per SKILL.md L125-127, already mechanically gated per #95-99 work) still lacks a hook enforcer — if all are covered post-batch-1-4, close as resolved; if gaps remain, file them specifically |
| D7 | `.wt-*` worktree glob has no marker file, collides with user's own `.wt-backup`-style dirs | Add a marker file (e.g. `.kunglao-worktree`) written at worktree creation, have the glob check for the marker instead of just the name pattern |
| D8 | 42+ openspec planned, no lifecycle — merges with R7 (Stage 1), no separate action |
| D9 | DESIGN.md permanently lags SKILL.md | Accept as documented policy (SKILL.md L46 already states this) — NOT-BUILDING, this is a deliberate tradeoff already made, not a defect |
| D10 | PROVEN-INITIAL→FULL hardcoded thresholds (≥2 tier or ≥5min multi-VM) fail non-PE/ELF or non-VM samples permanently | Needs a design decision, not a mechanical fix: define an alternate PROVEN-FULL path for samples where VM detonation is inapplicable (e.g., static-only analysis of a script/config file) — file as a design issue, not an immediate PR |
| D11 | decision-rights matrix labels `convergence_check` "mechanical" but it's LLM-invoked, not a hook | Documentation fix only — clarify in DESIGN.md/SKILL.md that "mechanical" means "deterministic output," not "hook-enforced-without-LLM-involvement" |
| D12 | specialist-agent selection is implicit tribal knowledge (adding one means editing 5 natural-language locations) | Add `references/specialist-registry.yaml` (agent name → trigger keywords → claim-type mapping) as the single source, have SKILL.md's specialist-first behavior reference it instead of hardcoding the list inline (this also naturally absorbs Stage-0.5's cti-correlator/shodan-host removal and any future additions) |
| D13 | hook FAIL_OPEN/FAIL_CLOSED policy undocumented rationale (LOW) | One doc pass: table of every hook + its fail policy + one-sentence why — likely already partially covered by #98's two-tier classification work, verify overlap before filing as fully separate |
| D16 | only 8 of 18 F-row failure modes have mechanical enforcement | Cross-reference against Stage-2's dead-gate disposition — several of the "orphaned" gates from Stage 2 Class 1 may be exactly the missing enforcement for these F-rows; resolve Stage 2 first, then re-count what's still actually missing |
| D17 | non-PE/ELF assumption (Go garble/.NET/firmware/Rust) has no specialist, falls to meta-deferred | **Firmware explicitly out of scope (user "不需要")** — narrow this to Go garble/.NET/Rust only, which are legitimate common RE targets already partially covered (`go-symbols` agent exists for Go). File as: does `.NET`/Rust need a dedicated specialist, or is `kunglao-worker` (general fallback) actually sufficient today? Investigate before building a new agent speculatively |

### Stage 5 — External absorption (C8-C13, narrowed; C1-C7 already exist per round-2's own correction)

| ID | Capability | Source | Scope (narrowed, RE-only, no firmware/game/CTI) |
|---|---|---|---|
| C8 | Fact-reference graph (cites/overlap/contradiction propagation across facts, not just claim-level `claim_deps`) | auto-re-agent | Add a lightweight `facts/_GRAPH.md` or `knowledge_graph.py`-equivalent that indexes fact-to-fact `cites`/`supersedes` edges for neighborhood-contradiction queries — this is a genuine gap: `claim_deps.yaml` (confirmed present in `templates/`) only models claim-level dependency, not fact-level cross-reference |
| C9 | Structural-integrity CI gate merging reverse-skill + ctf-skills ideas | reverse-skill, ctf-skills | Add a CI check: re-library orphan-reference scan (any `references/re-library/*.md` file not linked from `SKILL.md` or another reference) + `facts/_INDEX.md`-vs-actual-facts-dir drift check |
| C10 | Deterministic state-machine hard-preconditions (vs current event-then-degrade pattern) | AgentSec | **Partially superseded**: #98 already moved maker-checker to a structured two-tier classification (event-driven degrade, not full precondition-blocking). Re-assess whether a stronger hard-precondition model is still worth the complexity, or whether #98's fix already captured the valuable part — likely a smaller residual than round 2 estimated |
| C11 | Data-driven task routing with regex must/mustAll/exclude + bidirectional testing | reverse-skill, ctf-skills | Feeds into D12's `specialist-registry.yaml` — same underlying gap (implicit routing knowledge), same fix, don't duplicate as a separate mechanism |
| C12 | Graceful capability degradation (pre-declared `BackendCapabilities` probe) | auto-re-agent | Relevant mainly for D17's non-PE/ELF gap and D10's non-VM PROVEN-FULL gap — implement as part of those, not as a standalone mechanism |
| C13 | Operation-level audit log (who/when DEFERRED, overrode PROVEN, changed weight) | AgentSec | The `.convergence_ledger.jsonl` (confirmed exists) tracks convergence trajectory but not discrete operator decisions — add an `OPERATOR_ACTION` ledger line type (mirrors `LedgerLineType.OUTCOME` added in #35) for exactly these events |

---

## Execution sequence

```
Stage 1 (structural, mostly docs/config, low-risk, ships first, unblocks nothing else): R1..R7
Stage 2 (dead-code disposition — must run before Stage 4 D16, since D16 depends on knowing what's actually still orphaned): Class 1 (7 gates, parallel) -> Class 2-9 (small, parallel)
Stage 3 (remaining defects, independent of Stage 2/4): F3,F4,F5,F6,F7,F9,F10,F11,F12,F13,F14 (mostly independent, <=5 parallel per file-partition)
Stage 4 (arch debt, D16 depends on Stage 2 completing): D1(verify-only) || D3 || D5(verify-only) || D7 || D9(NOT-BUILDING, no issue) || D11(docs-only) || D12 || D13(verify-overlap-with-#98-first) || D17(investigate-before-build) -> D10(design-issue, no immediate code) ; D16 after Stage 2
Stage 5 (absorption, mostly independent, C11/C12 fold into D12/D10/D17/C10 — file jointly not separately): C8 || C9 || C13 ; C10/C11/C12 as amendments to their Stage-4 counterpart issues, not new issues
```

## NOT Building (explicit, per this plan)

- Firmware/game/UEFI/WASM/RISC-V additions anywhere (user: "firmware/game这些不需要")
- Any CTI/OSINT/attribution mechanism (owned entirely by batch 4's removal, never re-added here)
- D9 (DESIGN.md lag) — accepted as deliberate policy, not filed as an issue
- Full C10 hard-precondition state machine as originally scoped — narrowed after confirming #98 already captured most of the value
- A blanket "wire all 9 dead gates" — Stage 2 Class 1 explicitly requires a per-gate manual-vs-orphaned check first; some (failure_analysis_gate, premature_termination_detect) are intentionally manual, not bugs

## Acceptance Criteria

- [ ] Every row in Stages 1-5 above is either filed as a GitHub issue or has an explicit NOT-BUILDING line in this plan
- [ ] Stage 2 Class 1's per-gate grep audit completes before any gate is wired or deleted
- [ ] No issue from this batch touches CTI/attribution/firmware/game surfaces
- [ ] `master-plan.md` gets a new revision entry once this batch's issues are filed, cross-referencing this plan file

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Some "dead" gates in Stage 2 Class 1 turn out to be referenced somewhere this research missed | Medium | Wastes a delete-then-revert cycle | Per-gate grep-first requirement is already built into the Stage-2 table, not left implicit |
| D10/D17 get treated as mechanical fixes when they're actually design decisions | Medium | Rushed threshold change could weaken PROVEN-FULL's integrity guarantee | Both explicitly marked "design issue, not immediate code" / "investigate before build" in the tables above |
| Stage 4/5 overlap (D12≈C11, D10/D17≈C12) gets filed as duplicate issues | Medium | Wasted parallel work, potential merge conflicts | Explicitly cross-referenced in the tables — file jointly, not separately |

## Notes

This plan is the direct answer to "要吸收的内容没有纳入到计划内吗" — batch 4 only ever
covered the repositioning correction; this batch 5 is the rest of
`absorption-research-round2.md`'s catalog, narrowed by this session's two scope
corrections (RE-only, no CTI; no firmware/game) and by verifying against the actual repo
state what's already shipped (#95-#99) so nothing gets double-filed.

## Next Steps

Review the Stage 1-5 tables, confirm the NOT-BUILDING list, then file issues per stage
(recommend Stage 1 and Stage 2 Class-1-audit first, since Stage 2's findings gate Stage
4's D16 accuracy). Each issue follows the existing one-issue-one-PR-one-branch-one-worktree
convention, ≤5 parallel per stage.
