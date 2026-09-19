# design — issue-249-stalled-remedy

## Anchors (verified at HEAD 479217c)

- `scripts/convergence_health.py` — STALLED_FLATLINE=5, STALLED_STUCK_CLAIM=3,
  SPINNING_FLATLINE=8; exit 0/1/2/3/4 with 4=crashed fail-open (#3). The
  STALLED action prose ("reformulate or decompose") is emitted at the
  assess() STALLED branch; the dedup pressure valve deliberately preserves
  flatlines (anti-noise), which is what makes the deadlock tight.
- `hooks/worker_budget_core.py` — `check_convergence_health`: rc=1 ->
  (False, "convergence STALLED - diagnose before dispatching"); rc=4 ->
  fail-open with an observed crash message. Sole consumer:
  `worker_budget_sinks.pre_check` (the `('health', ...)` slot of the gate
  battery).
- The #237 pass-through pattern — `hooks/lib_kunglao.py`
  (`VERIFIER_REMEDIATION_AGENTS` + `is_verifier_remediation_dispatch`),
  wrapped at BOTH hook faces (dispatch_gate drift blocker +
  worker_budget_sinks drift gate) with try/except fail-closed-to-legacy.
- The decomposition operator — `scripts/target_ladder.py`
  (`mint_sibling_claims`, guarded: parent origin=failure-obstacle,
  claim-pinned obstacle_class, walked-valid 3-level ladder, non-empty
  inventory; idempotent on (origin, obstacle_for, ladder_family)).

### Anchor drift found

- The task brief said the remedy machinery is "#241 claim_granularity
  --split + #234 mint_split_claims, BOTH merged to dev". At HEAD 479217c:
  **#234 IS merged** (PR #270: scripts/target_ladder.py +
  mint_sibling_claims), but **#241 is NOT** —
  `scripts/claim_granularity.py` / `check_claim_granularity` exist only on
  `feat/241-granularity-gate` (964f2cf, not an ancestor of dev). This
  change therefore wires the MERGED #234 fan-out as the decomposition
  operator and stays additive w.r.t. #241 (the exemption's state
  intersection does not care which operator minted the sub-claims — any
  claim absent from the flatlined open set qualifies; #241's splits will
  ride the same channel when it merges).

## Decision 1 — state-intersected marker, not marker alone

A bare "remedy" marker would be self-certifying: any dispatch could print
it and walk past the gate. The #237 discipline is declaration INTERSECTED
with cheap detector state (verifier-class agent AND register PROVEN). The
#249 mirror: the marker `remedy: decompose` AND one of

- channel A: target claim ∈ stuck set (the last-3-snapshot intersection
  of open_ids, gated on dispatched evidence — the detector's own stuck
  definition, read via `convergence_health.stalled_state`, never
  re-implemented in the hook), or
- channel B: target claim ∉ trailing flatlined open_ids AND register
  status OPEN AND the claim's `depends_on` references a stuck claim
  (mint provenance read from the same register row).

Channel B is what makes the follow-through dispatchable in the window
between minting and the next convergence_check ledger row.

**Round-1 review correction (was factually false here):** channel B was
first specified as "register-OPEN + fresh — by construction exactly the
split's sub-claims". That invariant was FALSE as implemented: ->OPEN
registration is ungated (#819 gates only ->PROVEN) and the marker is
printed in the rejection prose itself, so a fresh unrelated OPEN claim
plus the quoted marker was admittable, repeatedly (each new id is absent
from the then-trailing snapshot). The `depends_on ∩ stuck_ids` pin is
the fix: the sub-claim must PROVE its mint lineage by depending on the
stuck parent. This is deliberately operator-agnostic — the issue-234
siblings (`depends_on: [parent]`, target_ladder mint) and the issue-241
splits (depends_on chain to the parent) both satisfy it; a future
operator with a different linkage shape would need either that edge or
an explicit provenance-field ruling.

## Decision 1b — remedy-depth escalation (round-1 MEDIUM: mint-loop)

Minting resets the flatline window with zero progress evidence, so an
unbounded mint/dispatch loop evades both STALLED and SPINNING. Minimal
counter-move, no new state store: every admitted remedy dispatch appends
an operator-action telemetry row to the convergence ledger
(`action: stalled_remedy_admitted`, actor `hook:worker_budget` — the
existing `record_operator_action` writer; assess already excludes typed
rows from the trajectory, so the row cannot perturb the verdict).
`stalled_state` counts consecutive cycles per stuck claim INSIDE the
claim's current stuck episode (episode starts at the last snapshot where
the claim was not in open_ids — a real trajectory change resets it; a
mint-window reset does not, because the stuck claim stays in open_ids).
At `remedy_depth >= 2` the follow-through channel (B) closes at the gate
face; channel A remains open but is bounded by the rest of the battery
(plan gate on re-dispatch, zerooutput thrash breaker, priority), so
repeated cycles escalate toward the human face instead of mint-looping.

## Decision 2 — the exemption lives INSIDE the rc=1 face

`check_convergence_health(paths, claim_id=None, payload=None,
prompt_text="")` consults the exemption only when the subprocess returned
rc=1. Consequences:

- SPINNING (rc=2) is structurally unreachable for the exemption; rc=4
  fail-open semantics are untouched.
- The subprocess still runs exactly once; the state re-derive is the
  in-process pure read (`stalled_state` — no telemetry, no subprocess).
  If the re-derive disagrees with rc=1 (ledger changed between the two
  reads) the exemption stays OFF (fail-closed).
- Legacy 1-arg callers (all existing tests, any external consumer) pass
  no claim id -> the exemption cannot fire -> exact prior behavior.
- The other gates in the pre_check battery (workers/cap/tools/tier/
  heartbeat/envfresh/backtrack/zerooutput/plan/toolfirst/agenttype/
  priority/snapshot) still apply to an admitted remedy dispatch — the
  exemption swaps one gate's verdict, not the battery.

## Decision 3 — two copies of the marker literal, one pinning test

scripts/convergence_health.py prints the marker in its action prose but
must not import the hooks twin (scripts-before-hooks sys.path ordering;
the #770 posture). hooks/lib_kunglao.py owns the enforced constant. The
cross-face sync is pinned by a fast unit test, the same way the #237 H1
marker split was closed by single-sourcing (here a single source is not
possible across the twin boundary without a new shared module — judged
not worth it for one literal; the pin fails loudly on drift).

## Decision 4 — the full cycle settles the parent SUPERSEDED, not PROVEN

The issue's end-to-end requires HEALTHY after mint. With a stuck
(dispatched-flat) parent, minting alone breaks the flatline but the stuck
channel keeps the verdict STALLED until the parent's claim-state changes —
which is the detector working as designed (#2 semantics). The remedy
dispatch's real-world output IS that state change: the parent retires
SUPERSEDED by its minted alternatives (TERMINAL per status_defs). The
cycle deliberately does NOT settle it PROVEN: a PROVEN settlement without
a verified reality check is precisely the UNVERIFIED_EVIDENCE drift the
B1o blocker rejects (#237 D3 forgery surface) — the test must not
manufacture a forged verify record to make the cycle green.

## Risk

- Blast radius (GitNexus, kunglao-agent index): `assess` LOW (3 d=1
  consumers: CLI main, kunglao-monitor.health_check, kunglao.cmd_health —
  all additive-key/output-text consumers); `check_convergence_health`
  LOW (1 d=1: sinks pre_check). The pre_check battery signature change is
  optional-kwargs only.
- Worst-case failure of the exemption predicate is fail-closed (legacy
  block), so the change can only ever ADD a pass channel for
  marker+state-intersected dispatches, never widen beyond them.
