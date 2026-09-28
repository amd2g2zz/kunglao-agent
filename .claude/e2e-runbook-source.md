# ERRATA (post-review 2026-09-28): this rehearsal runbook contains one
# error productized-then-corrected in scripts/e2e/: C7's "#880
# emit_settlements: action=settlement" — the REAL emitter action is
# "claim_settled" (register_proven_gate.py). scripts/e2e/model.py
# SETTLEMENT_ACTION pins the real value. Kept verbatim as the rehearsal
# record; the harness is authoritative where they disagree.

# kunglao-agent E2E dogfood runbook — py-derive-v1 (release gate)

Mandate: REAL full-pipeline run on post-wave dev. Target: eval unit
`py-derive-v1` (smoke tier, python, replay-roundtrip oracle) — legitimately
solvable (constants recoverable from target source) and CONVERGE-able.

## Fixed paths / constants

- REPO_WT  = /Users/mikenike/workprojects/kunglao-wt/e2e-dogfood   (worktree, post-gate reset to origin/dev)
- WS       = /tmp/e2e-ws-<YYYYMMDD-HHMM>/                          (real workspace, NEVER in repo)
- TARGET   = /tmp/e2e-sample/py-derive-v1/                         (sample unit copy; analysis material = target/derive.py)
- CANON    = uv run --project <REPO_WT> python <REPO_WT>/scripts/<script>.py ...
- Unit anchors (from task.yaml, used verbatim in resolve answers):
  - goal_verbatim: "Recover the three parameters of the derivation in target/derive.py and re-implement derive(data) -> int so it reproduces the reference outputs on arbitrary inputs."
  - success_criterion: "A derive() re-implementation that reproduces every published and checker-minted probe output exactly."
  - verification_method: reproduction
- Contamination rule: ground_truth.json / checker.py STAY OUT of the workspace.
  Material mounted into WS = target/derive.py only. Checker runs harness-side
  (by the runner) as the mechanical reproduction oracle at C7 only.

## C1 — init (intake + scaffold + toolchain gate + deploy)

Cmd A:
  uv run --project $REPO_WT python $REPO_WT/scripts/kunglao-init.py $WS \
    --lane algorithm --type linux
Expected: exit 8 = structured pending list on stdout (JSON). Anticipated
decision ids: goal_verbatim, success_criterion, verification_method, and any
target/type alignment the intake cannot pre-read. Record wall time.
Cmd B: write /tmp/e2e-answers.json mapping EVERY decision_id from the pending
document (anchors verbatim from task.yaml above; lane=algorithm already given).
Cmd C (REHEARSAL FINDING: flags are NOT persisted across re-entries —
repeat --lane/--type or the `type` decision re-pends):
  uv run ... kunglao-init.py $WS --lane algorithm --type linux --resolve /tmp/e2e-answers.json
Expected: exit 0. Observable: WS/claim-register.yaml seeded (algorithm lane =
scaffold-decision seeds, NO analysis conclusions — #412), analysis_state.txt,
task_spec.yaml (anchors filled), task-oracle.yaml skeleton, hooks deployed to
WS/.claude/settings.json, deployment ledger written.
FAIL = any rc not in {0,8} or exit-4 HARD toolchain fail → STOP, capture stderr.

## C2 — hooks wire-up (import-deps class must be impossible)

  uv run ... hook_activation.py $WS --wire-up
Expected: exit 0 + selfcheck lines all PASS (hook_activation self-checks every
registered hook command). Post-wave proof: NO write_guard/yaml ImportError.
Extra mechanical sweep (runner-side): for every hook command in
WS/.claude/settings.json, run it once in a throwaway cwd; assert stderr has no
ModuleNotFoundError / ImportError / NameError.

## C3 — heartbeat on + first tick (module_emit NameError must be gone, #413)

  uv run ... hook_activation.py $WS --heartbeat-on
  # startup action (loop prompt body executing = cron-acceptance proof, #461):
  uv run ... hook_activation.py $WS --heartbeat-on --loop-registered
  uv run ... heartbeat_tick.py $WS
Expected: both exit 0; tick report JSON on stdout; NO "module_emit" /
NameError degradation in stderr. runs/.heartbeat.json exists (worker_budget
REJECTS dispatch without it).

## C4 — entry via registered console script (#416)

  uv run --project $REPO_WT kunglao check-stale $WS
Expected: JSON envelope {"status":"current","rc":0,...}. (Post-wave the
entry-registration batch registers the `kunglao` console script; if the
script is absent → gate was opened prematurely → BLOCKED report.)

## C5 — analysis entry gate (version stamp 0.1.6 + tick continuity)

Prereq: >= 2 consecutive ticks (gaps <= 2x interval — interval is 5m — last <= 35 min):
  sleep 300 && uv run ... heartbeat_tick.py $WS   (second tick)
  uv run --project $REPO_WT kunglao analysis $WS
Expected: rc=0 (stale gate + durable /loop reconcile + continuous-tick verify
all green). rc=5 stale / rc=6 heartbeat dead / rc=7 anchors missing → STOP,
capture, classify.

## C6 — dispatch loop (convergence → priority_ratio #1 → worker returns facts)

C6-pre-1 (Phase-0 pre-registration; REHEARSAL FINDING: post-C6 convergence_check
returns BLOCKED rc=4 "verification requirements undeclared" until this is done;
init leaves only the template at WS/.claude/templates/state/): instantiate
goal-operationalization.yaml at WS root and fill FROM the verbatim task:
  deliverables:
    - "Re-implementation of derive(data: bytes) -> int committed in the
       workspace (artifacts/derive_reimpl.py) reproducing the reference outputs"
    - "The three derivation parameters recorded as numeric facts with evidence"
  acceptance:
    - "eval checker VERDICT PASS on the re-implementation (min_pair_ratio 1.0)"
    - "byte-exact reproduction of all 12 published + checker-minted probes"
  not_done:
    - "a re-implementation matching only the two __main__ probe strings does
       not count as done"
    - "parameters asserted without a fact file + evidence pointer do not count
       as done"
  diff_vs_verbatim: ["analysis material is the constructed eval target
       (target/derive.py), not a live binary sample"]
  generalization: required          # goal says "on arbitrary inputs";
  probe_cases:                      #  checker mints fresh probes
    - "checker-minted probes (12, never captured) — fresh-input master oracle"
    - "published pairs 0-11 — replay verification ladder"
  declared_ts: <now>
  oracle_behavior_acknowledged: true
Validate:
  uv run ... goal_operationalization.py $WS/goal-operationalization.yaml → 0
C6-pre-2 (intake enrichment): add primary_questions to WS/task_spec.yaml:
  primary_questions:
    - id: pq-1
      question: "What are the three derivation parameters of target/derive.py?"
    - id: pq-2
      question: "Does a re-implemented derive() reproduce every published and
                 checker-minted probe output exactly?"
(task-oracle.yaml needs NO manual backfill — REHEARSAL FINDING: init fills
task_text from the resolve answers; tick reports oracle_registered=true.)
C6-pre-3 (register analysis claims — seeds C-001..C-003 are already PROVEN
structural scaffold decisions, #412): append to WS/claim-register.yaml claims:
  - C-004 statement: "target/derive.py implements a 64-bit derivation whose
    three parameters (initial offset, multiply prime, fold multiplier) are
    recoverable from the target source + probe outputs."
    answers_question: pq-1, boundary_type: numeric, promotion_gate: "all three
    constants re-derived from evidence and byte-confirmed by the replay
    checker", status: OPEN, source: static_re
  - C-005 statement: "A re-implementation of derive() reproduces every
    published and checker-minted probe output exactly."
    answers_question: pq-2, boundary_type: confirmed, status: OPEN,
    source: synthesis
C6-pre-4 (mechanical):
  uv run ... env_check.py $WS                    → OVERALL=PASS
  uv run ... convergence_check.py $WS            → decision DISPATCH (rc per table)
  uv run ... priority_ratio.py $WS --json        → rank #1 claim id
Dispatch (orchestrator act, fire-and-continue): Task tool, subagent_type
kunglao-worker, background; prompt opens with the v1 canonical envelope
  {"kunglao_dispatch":{"version":1,"claim":"C-NN","tier":1,"tools":["grep","python3"],"agent":"kunglao-worker"}}
+ task text + facts-snapshot: line. T1 tier (pure static, cheap).
Per tick until facts land:
  uv run ... heartbeat_tick.py $WS
  uv run ... convergence_check.py $WS
  uv run ... convergence_health.py $WS           (every 3rd turn)
Expected observables: runs/worker-status-<id>.md written FIRST (worker-side
rule), then facts/F<NNN>.md with the recovered constants evidence; claim
classified from worker status; re-run priority_ratio for next top.
Verifier face: dispatch kunglao-redteam BLIND (raw evidence path + questions
only; never the maker's fact content) per maker-checker §1b.
Mechanical reproduction oracle (runner-side, harness act):
  uv run --project $REPO_WT python \
    $REPO_WT/eval/v1/tasks/smoke/py-derive-v1/checker.py --candidate <reimpl>
  → VERDICT PASS, min_pair_ratio 1.0
  (REHEARSAL FINDING: the /tmp copy of checker.py CANNOT resolve the repo
  scripts dir — parents[4] IndexError; MUST run via the repo-layout file.)
  Note: checker writes runs/eval/... evidence INSIDE $REPO_WT (untracked,
  gitignored, never committed; delete after the run).

## C7 — completion (PROVEN → CONVERGED → settlement rows)

Promote verified claims to PROVEN in WS/claim-register.yaml (register_proven_gate
enforces provenance); verdict face writes evidence/verdict.json (verdict-scorer).
  uv run ... convergence_check.py $WS            → decision CONVERGED, rc=0
  uv run ... completion_gate.py <WS>/task-oracle.yaml  (transaction clean)
Expected: exit 0; settlement rows appended to WS/runs/logs/kunglao-<date>.jsonl
(#880 emit_settlements: action=settlement, duration_ms ledger-measured);
CONVERGED evidence = claim-register all-PROVEN + facts/_INDEX + verdict.json.

## Stop conditions

Any checkpoint rc outside its expected set → capture exact command + stderr +
component, STOP, report DONE=BLOCKED with failure class. 4h wall budget for
the analysis phase; mid-flight at budget → honest PARTIAL state report.
Cleanup: hook_activation.py $WS --heartbeat-off at closeout (unconverged
teardown is rejected); workspace and target are disposable.

## Per-tick loop contract (C6/C7 driver, from the registered loop prompt)

Each 5-min cycle, in order:
1. uv run ... heartbeat_tick.py $WS            (rc=1 → read report, handle; rc=2 idle_circuit_breaker = MANDATORY stop)
2. read runs/.heartbeat-tick.json → action_taken MUST name a convergence-advancing act
3. uv run ... convergence_check.py $WS --json  → decision field, imperative:
   DISPATCH → priority_ratio.py #1, dispatch THIS turn (background kunglao-worker,
              v1 envelope + facts-snapshot; ≤3 concurrent; status file first)
   BLOCKED  → self-recover (resolve / stale_blocker_prune) or reactivate claim;
              worker-death records (runs/.worker-death-*.json) → RESUME claims
              absorbing the dead worker's artifacts (never redo from zero)
   DEFERRED → check reactivation possibility
   PARK     → record wake_condition + --heartbeat-off (revive via mission_stall.py)
   SATURATED→ poll all active workers
   CONVERGED→ §6.3 checklist + blind_gate spot-check + kunglao-verify L1 rerun
              + handoff-check → --heartbeat-off ONLY after this
4. ping active workers (SendMessage "[ping HH:MM] step? stuck? eta?"); TaskStop at 3 strikes
5. finished worker → verify facts → classify into claim-register → re-run priority_ratio
