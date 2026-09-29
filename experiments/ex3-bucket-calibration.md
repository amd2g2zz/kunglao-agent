# EX-3 — FACT_BUCKET_EDGES fill-distribution replay (issue #429, v0.1.6 W3-T3.2)

**VERDICT: NO CALIBRATION.** The live `FACT_BUCKET_EDGES = (0, 4, 9, 19, 49)`
(scripts/state_signature.py:107) stay UNCHANGED — the replayed dispatch
history never produces enough mass near any interior edge to test, let
alone indict, their placement. No re-mint is declared (nothing changed).

Reproduce:
`uv run --project . python experiments/ex3_bucket_calibration.py`
(raw numbers: `experiments/ex3-results.json`, same commit).
Harness: `experiments/ex3_bucket_calibration.py`.

## Setup

- Campaign root: `eval-campaign-v016/runs/eval-campaign-v016/` (the
  exp1-7 successor campaign workspaces, 2026-09-22/23; the same data
  face EX-1 mined and the #432 reindex consumes).
- Workspaces = the #240 marker set (`claim-register.yaml` present):
  **54 workspaces**.
- Trajectory face = each workspace's `.convergence_ledger.jsonl`
  `facts_total` history (one point per recorded convergence snapshot —
  the recorded per-tick state of the dispatch loop); a workspace with no
  ledger contributes its terminal `facts/F*.md` count as one declared
  fallback point.
- Each point bucketed by `state_signature.fact_bucket` — ONE
  discretization source, zero re-implementation. **142 samples.**

## Numbers

Fill distribution (bucket index → samples; buckets are 0 | 1-4 | 5-9 |
10-19 | 20-49 | 50+):

| bucket | range | samples | share |
|---|---|---|---|
| 0 | exactly 0 | 133 | 93.7% |
| 1 | 1-4 | 6 | 4.2% |
| 2 | 5-9 | 3 | 2.1% |
| 3 | 10-19 | 0 | 0% |
| 4 | 20-49 | 0 | 0% |
| 5 | 50+ | 0 | 0% |

Interior-edge mass (raw points within ±2 of the edge, below/above — the
declared straddle test):

| edge | below | above |
|---|---|---|
| 4 | 0 | 0 |
| 9 | 0 | 3 |
| 19 | 0 | 0 |
| 49 | 0 | 0 |

Only 3 of 54 workspaces ever held facts at all (max trajectory = 9 facts,
in `ws-net-verify-license-l1a-v1-...89310`, 5 recorded points); 51
workspaces sat at bucket 0 for their whole life.

## Verdict reasoning (declared criteria, in the results JSON)

Declared rule: *calibrate iff some interior edge shows ≥ 5 points within
±2 of it on BOTH sides* (evidence the edge cuts a dense region), on a
base of ≥ 30 samples.

1. **Sample base passes (142 ≥ 30) but the spread does not exist**: the
   entire campaign occupies buckets 0-2; buckets 3-5 are never reached.
2. **No edge is straddled**: the only edge with any adjacency mass is 9
   (3 points above, 0 below) — the 9-fact workspace parked exactly AT
   the upper-inclusive boundary of bucket 2 rather than straddling it.
   One workspace touching one edge is not calibration evidence.
3. **The empty upper buckets reflect campaign scale, not edge
   misplacement**: this campaign predates the #432 method-family gate
   (0 dispatch rows carry a `method_family`) and the fact-producing loop
   barely engaged (93.7% of snapshots at zero facts). Moving edges to
   fit a distribution that never left the floor would be fitting noise.
4. **Undecided, not decided-negative**: the edges remain UNTESTED above
   count 9. The binding measurement arrives with the W3 E2E runs
   (T3.3), where the kernel is actually live; re-run this harness then.

## Action

- `FACT_BUCKET_EDGES` unchanged — no constants diff, no re-mint.
- Re-run `experiments/ex3_bucket_calibration.py` after T3.3's E2E
  activation runs; calibration only becomes decidable with trajectories
  that reach the upper buckets.

## Threats to validity

- `facts_total` (convergence snapshots) and `fact_face` (F*.md glob)
  are the same glob face today; historical rows predate no known
  divergence, but any future face split would need this harness
  re-examined.
- The terminal-fallback point (workspaces with no convergence ledger)
  contributes one point per workspace — with 54 workspaces and 27
  ledgers this is up to half the sample base at bucket 0; it biases the
  floor bucket's mass, which is already overwhelming, and touches no
  interior edge.
- A campaign of ~10-tick workspaces measures SHORT trajectories; a
  long-running production workspace could populate buckets 3-5 within a
  single run — another reason the current absence of mass is scale, not
  evidence.
