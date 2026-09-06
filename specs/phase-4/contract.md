# Phase 4 Contract — M1 DECIDE action-selection rework

> **Revised 2026-08-06 (issue #1 cleanup-routing-module)**: the routing layer
> (method_router / method_topk / method_router_register / method-graph) was
> experimentally falsified and CUT; this contract has removed all routing
> sections. The priority_ratio section keeps the current implementation (the
> old 0.35·Δdisc formula); the VoI-proxy rewrite lives in issue #2
> (`phase4-voi-priority`).
>
> **Revised 2026-09-06 (issue #107 Thompson rebuild)**: the owner ruling
> "探索和价值网络完全重构，之前的不要了" discarded the weighted VoI-proxy
> formula AND the explore/exploit dual path. ONE ranker survives:
> score = (sampled case posterior + LAMBDA_DH·ΔH_PQ) · worth, Thompson-ranked
> per posterior state, stable tie-break claim_id. explore_gate /
> EXPLORE_THRESHOLD / the cheapness face / `explore_mode` are deleted; the
> sections below describe the REBUILT surfaces (pre-#107 text is history).

Source documents (frozen sources, excerpts with line numbers):
- `docs/design/archive/module-design.md` — all of §M1 (L112-207); M1.1 division L114-125; M1.2 signatures L126-159; M1.3 schema L160-172; M1.4 state machine L173-192; M1.5 error handling L193-199; M1.6 test points L200-205
- same directory `docs/design/archive/design-spec.md` — §3.2 ratio-key algorithm (L129, with the 2026-08-06 VoI-proxy final decision)
- ready for reuse, unchanged: `scripts/convergence_check.py::decide` (5-branch matrix, golden F-01..F-16), `scripts/priority.py::rank_claims` (legacy additive weights), `scripts/ask_for_direction_gate.py` (selfcheck ask-back part already implemented)

> 2026-08-14 (#319 dedup): the source documents moved with the docs-tree
> unification into `docs/design/` (old tree deleted, see git history); line
> numbers re-verified against the current files. Note: the current
> `docs/design/archive/module-design.md` M1.2 contains
> resource_selector/feedback_updater (2026-08-06 revision), differing from
> this contract's frozen post-CUT signature set — the two-tree content drift
> the #319 audit found.

---

## 1. Function signatures (frozen, M1.2 original L126-159, routing removed)

```python
def convergence_matrix(open_count, partial_count, free_slots, blocked_count) -> Decision:
    """→ DISPATCH(1) | DISPATCH_VERIFIER(2) | SATURATED(3) | BLOCKED(4) | CONVERGED(0)"""

def priority_ratio(claims: list[Claim], deps: DepGraph, evidence: EvidenceView,
                   rng: Random | None = None) -> list[Action]:
    """#107 Thompson ranking: score = (case_face + LAMBDA_DH·ΔH_PQ) · worth
    case_face = Σ linked oracle cases of ONE Beta posterior Thompson sample
                (no linkage → one Beta(1,1) prior sample = cold-start exploration)
    ΔH_PQ     = H of the claim's PQ categorical (posteriors.yaml), else 0
    worth     = #759 value-weights multiplier (exogenous, not a DOF)
    LAMBDA_DH = 0.25 — the only free parameter
    rng=None → Random(0); live callers share posterior_rng(ws)"""
    # deleted with the owner ruling: [0.45L+0.30D+0.25N]/cost, gap_bucket
    # sort head, explore_gate, EXPLORE_THRESHOLD, the cheapness spread

def selfcheck(text: str) -> list[str]:
    """scan orchestrator output for ask-back / self-cap violations"""

def decide(ws: Path, scan_text: str | None = None) -> dict:
    """compose the above; output contract frozen. Routing CUT: top_actions.skill is always None, the worker picks its own tools."""
```

### Landing map (contract-blank decisions)

| Design signature | This-phase landing | Note |
|---|---|---|
| `convergence_matrix(...)` | **not rebuilt** — `convergence_check.decide(ws)` already implements the same matrix (5 branches in the same order, L241-259) and is golden-frozen | M1.6 L202 "behavior snapshot exists" |
| `priority_ratio(claims, deps, evidence, rng=None)` | `scripts/priority_ratio.py::priority_ratio` | pure function; failure-blocked filtering is the caller's job; the workspace rides `EvidenceView.ws` (#107: posteriors + oracle cases load through it) |
| `explore_gate(count, threshold)` | **deleted (#107)** — cold start is Thompson's Beta(1,1) prior sampling; no phase gate exists | |
| `selfcheck(text)` | `scripts/kunglao-decide.py::selfcheck(text)` composes `ask_for_direction_gate.find_violations` (ask-back) + `worker_budget.detect_self_cap` (self-cap) | ask_for_direction_gate already implemented, tests only added |
| `decide(ws)` | `scripts/kunglao-decide.py::decide(ws, scan_text=...)` | standalone CLI, not a kunglao.py subcommand |

### priority_ratio component semantics (contract-blank decisions, all pinned into the contract and tests)

- `Δdisc(a) = marginal_discriminator(a, evidence)`:
  - claim a has a **terminal fact** in `facts/_INDEX.md` (status containing one of PROVEN/VERIFIED/NEGATIVE/REFUTED/DEFERRED) → `0.0` (dedup against evidence already obtained)
  - otherwise `1.0`
- `E_unlock(a) = expected_unlock(a, deps) × P(success)`:
  - closure reuses `priority._leverage_v2` (sigmoid transitive closure + gateway bonus, clamped [0,1]; priority.py L93-113 ready for reuse)
  - `P(success) = 1/(1+promotion_attempts)` (contract blank)
- `unc(a) = freshness(a) = 1/(1+attempts(a))` (same shape as P(success))
- `cost(a) = NEXT_TIER_CHEAP[evidence_tier_attempted(a)]`, dict = priority.py L44 `{0: 1.0, 1: 0.5, 2: 0.2}`, out-of-range `0.1`
- `score(a) = (0.35·Δdisc + 0.35·E_unlock + 0.10·unc) / cost(a)`
- ordering: score descending; dispatchable filter: non-terminal, attempts<3, depends_on all terminal
- `classify_action(claim)`: keyword classifier (statement+answers_question lowercased): C2/mpd/pegasus/dead-drop→`c2_config_extract`; command table→`command_table`; protocol/runtime/network→`protocol_restore`; persistence/autorun→`persistence`; injection/reflective→`injection`; anti-analysis/garble/decoy→`anti_analysis`; family/vidar/wingo/gsb→`family_attribution`; no hit→`evidence_collection`

### Exploration, redefined (#107)

There is no exploration MODE. Thompson sampling explores intrinsically: an
uncertain arm (Beta(1,1) prior, few runner verdicts) samples wide and
occasionally ranks first; a settled arm concentrates. The dispatch gate
audits the SAME ranker with the SAME seed (`posterior_rng(ws)`) — the
#100/#101 dual-authority conflict is structurally impossible.

---

## 2. Output schema reference

- frozen structure: `schemas/decide-output.json` (M1.3 L163-170 field by field)
- required 8 fields (#107 dropped `explore_mode` with the dual path): `decision` (enum 6 values — #371 added INVALID: the legitimate convergence_check return when task_spec primary_questions is non-empty but malformed (#77 fail-closed), reusing exit 4) / `exit_code` (0-4) / `top_actions[]` (items: claim_id, action, score, skill) / `blocked[]` / `failure_blocked[]` / `stale[]` / `drifts[]` / `selfcheck[]`
- additional fields (additionalProperties allowed, not frozen-required): `open_count`, `partial_count`, `free_slots`, `error`
- field mapping (contract blanks):
  - `blocked` = ids among open_claims with `blocked=True`
  - `failure_blocked` = convergence_check's failure_blocked (via failure_analysis_gate.scan_workspace)
  - `stale` = stuck_workers' worker names (>20min without an in-progress update)
  - `drifts` = always `[]` (not computed in phase 4; plan_drift_detector is a separate gate)
  - `selfcheck` = scanned when `--scan-text` is provided, otherwise `[]`
  - `top_actions[].skill` = always `None` (routing CUT, the worker picks)

## 3. State machine (M1.4 original flow, routing steps removed)

```
decide(ws):
  evidence = load_evidence(ws)                    # facts/_INDEX + ledger + loopstate
  decision = convergence_matrix(...)              # ← convergence_check.decide (golden)
  if decision == DISPATCH:
    actions = priority_ratio(claims, deps, evidence,   # ONE path (#107)
                             rng=posterior_rng(ws))    # seed shared with the gate
    top = actions[:k]
    dispatch(top)                                 # skill=None; worker picks its own tools
  elif decision == DISPATCH_VERIFIER:
    dispatch_verifier(partial_facts)
  return DecideOutput
```

- `k = free_slots = max(0, 3 - active_workers)` (convergence_check L231)
- DISPATCH_VERIFIER / SATURATED / CONVERGED: `top_actions=[]`, remaining fields mapped from convergence_check as-is
- script exception (M1.5 L198): record ledger (failure_recorded) + return `BLOCKED` (exit 4) + `error` field — **never a false convergence**

## 4. Test points (M1.6 + this-phase RED list, routing test points removed)

| Test point | Assertion | File |
|---|---|---|
| Thompson composite | `score == round((case_face + LAMBDA_DH·ΔH)·worth, 6)`; deterministic under the default seed; ordering = sample descending, tie-break claim_id | tests/test_priority_ratio.py |
| cold-start exploration | no linked oracle case → one Beta(1,1) prior sample; feeds record the fallback flip potential 0.3 | same |
| flip potential | 0.5 base decayed by promotion_attempts (diagnostic only) | same |
| dispatchable filter | terminal / attempts≥3 / dep non-terminal excluded (unchanged) | same |
| posterior hookup | linked case posteriors + PQ categoricals load through EvidenceView.ws (runs/posteriors.yaml, oracle/cases/*.yaml) | same |
| deleted surfaces | explore_gate / EXPLORE_THRESHOLD / cheapness / explore_mode greppable nowhere in scripts/ + hooks/ | tests/test_value_rebuild_107.py |
| kunglao-decide composition | on DISPATCH top_actions populated and passing `schemas/decide-output.json`; on CONVERGED top_actions=[]; skill always None | same |
| selfcheck | ask-back text REJECT (rc=1); self-cap text REJECT (rc=1); composed scan returns the violation list | same |

## 5. Completion criteria

1. all new tests green + full regression green (`python -m pytest -q -p no:cacheprovider`)
2. `schemas/decide-output.json` validates kunglao-decide output via jsonschema
3. E4.1: `tools/measure_value_order.py` outputs the conformance rate % (reported honestly; no re-ordering or sample cherry-picking to hit a target)
4. constraints: do not touch SKILL.md/references/hooks/kunglao.py/convergence_check.py/priority.py/test_suite_health.py/test_kunglao_init.py; no git commit
5. **issue #1 cleanup**: `git grep -iE "method_router|method_topk" scripts/ tests/` empty

> issue #2 (`phase4-voi-priority`) will rewrite the §1 priority_ratio
> signature + component semantics into the VoI proxy
> `[0.45L+0.30D+0.25N]/cost`, and change the "ratio-key formula" test point
> in the table above.
