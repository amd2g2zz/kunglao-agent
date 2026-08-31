## Why

v0.1.3 milestone review surfaced the loop-flow half of hypothesis-driven investigation: the agent reads the user's question and jumps straight to evidence-gathering (`C-NN` dispatch), never recording "before seeing evidence, I think this might be X". Without an upfront hypothesis the loop cannot detect "evidence that contradicts my starting assumption" — the AES example: agent dispatches "check hardcoded key" without ever recording "might be Cobalt Strike" vs "might be custom crypto" as competing explanations.

`scripts/hypothesis_store.py` (#528, closed) covers storage + restart rehydrate. **Nothing seeds hypotheses from task_spec** — the layer starts empty and stays empty unless the orchestrator LLM remembers to fill it (the exact "depends on LLM remembering" defect class this milestone is closing).

## What Changes

- **New `scripts/hypothesis_seeder.py`**: mechanical, idempotent scaffold seeder. `seed_from_task_spec(ws)` reads `task_spec.yaml` `primary_questions[]`; for each question with no existing open hypothesis carrying the body marker `pq:<qid>`, writes `hypotheses/H-NNN.md` (status=open, competitor_group=`pq-<qid>`, candidates=[] — orchestrator fills before first C-NN dispatch, claim_id=`C-PENDING` placeholder). CLI + kunglao_log observability.
- **`scripts/digest_build.py::build_digest`**: calls the seeder before `build_sec_g` (fail-open — a seeding failure never blocks cold start). This makes seeding mechanically enforced at **every cold start**: the digest lists open hypotheses, so a fresh session rehydrates the same competitor set it had before restart (#528's rehydrate goal, now with a guaranteed-nonempty input side).
- **`scripts/convergence_check.py`**: DRAIN gains `OPEN_HYPOTHESIS_AT_CLOSE` between `NOTE_LAYER_GAP` and `DISCOVERY_UNCONSUMED` (#443 state machine, additive) — fires when any hypothesis is `status: open` at close time → BLOCKED "adjudicate H-NNN (refute via refuting_fact_id / supersede) before convergence". Undecided competitor explanations at delivery are the exact "精神分裂 / 矛盾自报" defect the milestone review named.
- **CHANGELOG.md**: v0.1.3 Round 3 append. Plus fold-in cleanup: `openspec/changes/issue-663-anomaly-detection/` → `openspec/archive/` (post-merge move, plan §10.3).

## Capabilities

### New Capabilities

- `hypothesis-driven-investigation`: every `task_spec.primary_questions[]` entry has ≥1 open hypothesis scaffold before any C-NN dispatch (mechanically enforced at every cold-start digest build); hypotheses left open at convergence close block CONVERGED pending adjudication (refute with `refuting_fact_id` or supersede with `superseded_by` — the #528 state machine's existing terminal paths).

### Modified Capabilities

- `cold-start-digest`: `build_digest` seeds-then-lists (seeder runs before `sec_g`; fail-open posture unchanged).
- `convergence-decision-machine`: DRAIN events gain `OPEN_HYPOTHESIS_AT_CLOSE` (additive; no existing probe reordered).

## Impact

- **New files**: `scripts/hypothesis_seeder.py` (~150 lines), `tests/test_hypothesis_seeder.py` (~200 lines), `openspec/changes/issue-662-hypothesis-seed/{proposal,design,specs/.../spec,tasks}.md`.
- **Modified files**: `scripts/digest_build.py` (~10 lines), `scripts/convergence_check.py` (~30 lines, additive), `CHANGELOG.md`.
- **Backward compatibility**: no schema change (`hypothesis_store` schema untouched — the `pq:<qid>` marker lives in the body precisely because frontmatter extras are dropped by `HypothesisStore._write`); existing hypotheses (pre-#662 workspaces) simply appear in the new DRAIN gate if still open at close — that is the intended enforcement, not a regression.
- **Maker-checker**: seeding is scaffold-only (candidates=[]); the orchestrator/analyst fills candidates — the seeder never invents analysis content (init's #412 no-analysis rule preserved).
- **Related**: #528 (storage + rehydrate — this change supplies the input side), #663 (anomaly layer; both are v0.1.3 Round 3), #664 (intent-aware stopping — orthogonal), #614 (7 architectural gaps umbrella).
