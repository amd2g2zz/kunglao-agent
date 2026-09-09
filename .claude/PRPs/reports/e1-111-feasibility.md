# E1 Feasibility Verdict — issue #111 (hypothesis-verification loop integration test)

- **Verdict: PASS.** The inequality `r1 > r2 >= r3` is achievable on the synthetic
  signed-request fixture using ONLY the real modules (`priority_ratio`,
  `oracle_runner`, `case_bank`, `posteriors`, `hypothesis_store`, `dead_letter`)
  with seeded rng. No production code change is needed.
- **Numbers (variant A, full design):** over a 60-seed sweep, r1 in {7..10}
  (mode 10 at 50/60 seeds), r2 = 1, r3 = 1 — zero failures. Seed sweep
  `min r1 = 7 > r2 = 1`: the gate is not seed-fragile.
- **Chosen fixture constants:** `FIXTURE_SEED = 111` (r1=7, r2=1, r3=1),
  `MAX_DISPATCHES = 12` (r1 worst case is bounded at 10 = 3 naive claims x 3
  attempts + 1 green), naive-family worth override = 5.0 (#759 channel).

## Fixture (all synthetic values hashlib-derived)

6 claims C-101..C-106, all `OPEN`, `answers_question: PQ-SIGN`,
`competitor_group: PQ-SIGN` (naive family C-101/102/104, salted family
C-103/105/106). True algorithm: `sign = md5("k1" + md5(canonical_params))`
(salted composite); naive hypothesis `sign = md5(canonical_params)` is
plausible from the 32-hex shape and WRONG. 3 oracle cases CASE-S1..S3
(`target_pq: PQ-SIGN`, expected entries byte-anchored to facts F001..F003),
clients `client_salted.py` / `client_naive.py` under `oracle/`.
Round-1 trap: `runs/value-weights.yaml` per-claim overrides boost the naive
family (the #759 worth channel consumed by `claim_value_weight`,
scripts/priority_ratio.py) — the "string-shape routing prior" cold start.

## Mechanism attribution (ablation, seed 111)

| Variant | r1 | r2 | r3 | Reading |
|---|---|---|---|---|
| A full design | 7 | 1 | 1 | PASS |
| E attempts/DLQ only (no bank elimination) | 7 | 4 | 1 | partial: untried naive sibling C-102 still burns in round 2 |
| F attempts reset ALL + no elimination (brief's literal "resets claim attempts") | 7 | 10 | 10 | **FAIL** — the naive trap replays verbatim |
| G posteriors OFF (bank elimination on) | 10 | 1 | 1 | posteriors are NOT the flipper |
| H worth override OFF | 1-2 | 1-3 | 1 | FAIL on some seeds — the round-1 naive burn is NOT forced without the worth trap |

**The flip is produced by:**
1. **Case-bank premise_correction retrieval (sufficient, necessary for the
   full flip).** Before each round-N>1 dispatch the loop retrieves
   `runs/case-bank.jsonl` entries (failures-first, `case_bank.retrieve`);
   NEGATIVE entries carry a mandatory `attribution` naming the family's
   client (ruling 4 makes unattributed failures unbankable) plus a
   `premise_correction`. Families whose retrieval shows an all-cases red are
   dropped from the dispatchable pool before ranking — the issue's own
   "eliminated by a retrieved premise_correction before dispatch" face.
2. **Dispatch-frontier memory (promotion_attempts -> DLQ), partial alone.**
   `priority_ratio`'s candidate filter drops claims at `attempts >= 3`; the
   driver mirrors `dead_letter.mark_dead` (#36) at exhaustion. Round 2 under
   this channel alone still burns the never-tried naive claim (r2=4).
3. **Terminal hypothesis adjudication.** H-01 is `refuted`
   (`refuting_fact_id`) at the first naive red; `hypothesis_store`'s state
   machine refuses reopening terminal hypotheses, and the round refile files
   a fresh open hypothesis only for the surviving competitor space — the
   refuted family is never resurrected as a live candidate.

**Not the flipper (measured, not assumed):**
- Case posteriors Beta(1, 1+reds) lower `case_face` for ALL PQ-linked claims
  uniformly (case linkage is `answers_question == target_pq`, shared by every
  competitor), so they cannot reorder within the PQ family — variant G keeps
  the full speedup with posteriors disabled.
- `FLIP_POTENTIAL_BASE/(1+attempts)` decay is a `feeds` diagnostic only; it
  never enters the score (scripts/priority_ratio.py, `fp` assignment vs
  `score`).
- Novelty saturation does not exist since #107 (the novelty proxies were
  deleted with the weighted VoI formula).

## Round-reset semantics (deviation from the brief, forced by measurement)

The brief contains two mutually contradictory clauses: "Round 2 keeps
posteriors+case_bank but resets claim attempts" vs expected mechanism "(a)
FLIP_POTENTIAL_BASE/(1+attempts) decay on round-1-dispatched claims" — decay
presupposes attempts PERSIST. Variant F measures the literal reset: r2 = r3 =
10, FAIL. The coherent round-reset (used by the test) is:

- claims closed BY a round's green (`PROVEN`) reopen with `attempts = 0` —
  the green is re-earned through the oracle every round (no degenerate
  "cached answer" carry-over; the issue's round-3 guard stays meaningful);
- terminal refutation adjudications (`DEAD` claims, `refuted`/
  `superseded` hypotheses) persist — experience lives in the DESIGNED
  channels only (runs/posteriors.yaml, runs/case-bank.jsonl, hypotheses/*.md).

The test never hardcodes which family is correct: elimination is driven by
banked oracle observations; if the salted family had gone red, the same rule
would eliminate it.

## Scratch evidence

Experiment script kept out of the repo (run under /tmp/e1_111/e1.py); per-run
workspaces under /tmp/e1_111/run-<variant>-seed<seed>/. Nothing committed
except this report.
