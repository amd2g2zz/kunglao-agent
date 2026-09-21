# ADR-001 — Strategy-Parameter Governance, and the First Application: LAMBDA_DH Removal (#295)

> Status: ACCEPTED (2026-09-22). Owner safety requirement, issue #295.
> Companion evidence: the #294 replay ruler (`scripts/replay_ruler.py`,
> PR #321), the EXP-B audit (issue #295 comment), and the #294 λ
> epistemology check. This ADR supersedes the #107 clause
> "LAMBDA_DH = 0.25 is the only free parameter" — the parameter dies;
> the single-free-parameter *discipline* it embodied is what survives,
> now codified as the procedure below.

## 1. Why this ADR exists

The DECIDE rank face carries named constants that are genuine free
parameters of the strategy (they shape which claim gets dispatched
next). A hand-set free parameter inside a self-improving loop is an
objective-tuning hazard: a loop that could adjust its own ranking
weights at runtime would be optimizing against a moving target —
unfalsifiable, unauditable, and a standing correctness risk. The owner
ruling is absolute: **the loop must NEVER tune its own objective at
runtime.**

## 2. The parameter-change procedure

Every rank-face strategy constant (currently `W_DOWNSTREAM`,
`DOWNSTREAM_DECAY`, `DOWNSTREAM_CAP`; the D_t weights
`D_W_ORACLE/D_W_IMPL/D_W_EV` when they earn admission) changes only by
this procedure:

1. **Evidence bar (entry).** A change is admitted only with attached
   **#294 replay evidence** — `scripts/replay_ruler.py` output over the
   real historical workspaces (TTC deltas, order digests, D_t/reward
   faces), read-only, sandboxed. No replay numbers, no change. The
   `lambda_default` vs `lambda_zero` comparison that killed LAMBDA_DH
   (§4) is the shape: the harness measures, the ledger decides.
2. **Versioned PR only.** A new value lands as a versioned commit in a
   PR that (a) carries the replay evidence, (b) moves the value pins in
   the same commit, and (c) updates the earn-in comment at the constant's
   definition. Silent drift is impossible by construction: the value
   pins (`tests/test_replay_ruler_294.py::TestDownstreamConstantPins`,
   and the formula-shape pins in `tests/test_value_rebuild_107.py`,
   `tests/test_epistemic_pricing_250.py`) hard-assert current values or
   removal shape and go red on any unpinned change.
3. **Never runtime self-tuning.** No production path writes a ranker
   constant at runtime. The ONLY mutator in the tree is the replay
   harness's parameterize step (`replay_ruler._rank_under_config`), and
   it is a validate-then-assign with a `finally: restore` — it evaluates
   a counterfactual in a sandbox and can never leak a value into
   production state. This is test-pinned:
   - `tests/test_replay_ruler_294.py::TestConfigPoisonHole` — a bad
     config value raises before anything is assigned, and a successful
     counterfactual probe run leaves the constant exactly on its
     pinned production value (evaluation cannot leak);
   - `tests/test_replay_ruler_294.py::TestNoRuntimeSelfTuning` — an AST
     scan over EVERY deploy-shipped Python surface (`scripts/`,
     `hooks/`, `tools/` — the ranker is imported at hook time by
     `worker_budget_core` and `dispatch_gate`, so a hooks-side write
     must fail the scan too) proving no module other than the ranker's
     own module-level definitions and the harness's restore block
     carries a write or deletion site for any ranker constant — in
     EITHER form: a bare Name target or the module-attribute form
     through the import alias (`pr.W_DOWNSTREAM = tuned`, `+=`,
     annotated assigns, and `del pr.W_DOWNSTREAM` are all matched and
     flagged; a mutation proof pins that the sanctioned block's own
     attribute-form writes are matcher-visible and exempted by file+
     function identity, never by being invisible). Plus two behavioral
     probes — a full rank run and a hooks dispatch-budget
     audit pass — that execute the real rank face and assert the
     constants come back frozen.
   The harness may evaluate; it may never write back.

## 3. The downstream-term precedent (the exemplar)

`W_DOWNSTREAM` and its companions in `scripts/priority_ratio.py` are
the template every future parameter change must follow: the constant
definition carries (a) its **value**, (b) its **earn-in evidence**
inline — the three-workspace TTC replay table from the #294 run — and
(c) the **governance comment** naming the pins and the governed
procedure. Value + evidence + governance-comment, physically adjacent,
so no reader can change the number without reading why it is the
number.

## 4. First application — REMOVE the ΔH_PQ term (λ = LAMBDA_DH dies)

The first governed application is a REMOVAL, not a re-tuning. The
card's own bar — "replay-driven validation or correction of
LAMBDA_DH=0.25 on real ledgers" — resolved to correction in the
strongest possible direction:

**Evidence.**

- **EXP-B audit** (issue #295 comment): across **612/612 real rank
  events** the `dh_pq` feed carried ΔH = 0; `runs/posteriors.yaml` was
  never instantiated in any real workspace (no PQ categoricals in the
  wild); pooled Spearman vs progress was **+0.068 (p = 0.16)** — no
  signal — and the sign was **wrong vs gate fires (+0.108, p = 0.025)**.
- **#294 λ epistemology check** (merged, PR #321): **zero non-zero ΔH
  events across ALL workspaces**, and the λ=0.25 vs λ=0 replay produced
  **order digests byte-identical at every tick** — the term is
  mechanically inert on all real data.

**Decision.** Remove the ΔH_PQ face from the production score. The
score becomes `(case_face + W_DOWNSTREAM · downstream_term) · worth`.
On all historical behavior this is a runtime no-op: the term contributed
`LAMBDA_DH × 0 ≡ 0` at every tick of every real workspace, so ordering
is byte-identical by exact IEEE-754 arithmetic (`x + 0.25·0.0 == x` for
every score the loop has ever produced) — risk nil, per EXP-B's own
words. The λ epistemology *harness face* (`replay_ruler.lambda_check`)
stays: it measures HISTORY, and old events legitimately carry `dh_pq`
strings; post-removal events carry no such feed, which the parser
already scores as inert. The `lambda_default`/`lambda_zero` ruler
configs are consumed — their question is answered — and collapse away;
`base` vs `downstream` remains the live TTC comparison axis.

**Removal pins.** The former `LAMBDA_DH == 0.25` value pins are now
removal pins: `tests/test_value_rebuild_107.py` and
`tests/test_epistemic_pricing_250.py` assert the attribute no longer
exists and the score formula carries no ΔH lift even where a PQ
categorical exists. No unpinned drift is possible in either direction.

## 5. Consequences

- Adding a new strategy parameter requires this procedure **before**
  the constant exists, not after: the earn-in comment + pins land with
  the constant (the W_DOWNSTREAM shape).
- The replay ruler remains the only sanctioned measurement instrument;
  its sandbox/restore discipline is the boundary between measuring the
  objective and tuning it.
- If a future PQ-categorical-like term is proposed, it re-enters
  through §2 — with #294 evidence that it moves TTC/order on real
  ledgers, unlike the term removed here.
