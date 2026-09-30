# EX-5 — MC replay A/B: predict-before-try (issue #460 Part B)

Reproduce: `uv run --project . python experiments/ex5_predict_before_try.py`
(raw numbers: `experiments/ex5-results.json`, same commit; deterministic —
two runs over the same table produce byte-identical output, sha256
`7a983359…` over the committed results).

Policies:

- **A (status quo)** — flat cells + fixed probe set: the DTS sampler
  over the training pool with the feature prior off.
- **B (candidate)** — feature-conditioned prior + probe arms: the same
  sampler with `KUNGLAO_PREDICT_BEFORE_TRY=1`, the held-out run's
  instance features, and the training rows as the feature table.

Protocol: leave-one-run-out over a mined feature table; candidates =
the training pool's observed method vocabulary; P_LLM = the measured
proposal share; the environment scores a drawn first act against the
held-out run's own empirical per-family success rate; 200 seeded
trials per run per policy. Metrics: cold-start first-act success rate
and oracle PASS rate (modal first act carries a settled positive
credit).

## Result: UNDERPOWERED — flag stays OFF

| | table rows | usable runs | A first-act succ | B first-act succ | A oracle | B oracle | verdict |
|---|---|---|---|---|---|---|---|
| fixture golden | 3 | 2 | 0.00 | 0.00 | 0.00 | 0.00 | UNDERPOWERED |

**This is not a win, and it is not a loss — it is no signal.** The
only mined table in the repo (the Part-A sanitized fixture golden)
carries two usable runs whose method vocabularies do not even overlap
(`static_re` vs `static-decompile`/`synthesis`), so every first act
either policy draws is unverifiable against the held-out run (p=0 for
both policies equally — a symmetric miss, not an asymmetry). The
machinery IS live under the replay: the two policies produce
different modal first acts (A → `static-decompile`, B → `synthesis`
on the mod-crypto-js run — the feature pool moves the draw), proving
the prior actuates; the table simply cannot adjudicate it.

Per the activation rule (design Decision 1/6 and the spec's EX-5
requirement), `KUNGLAO_PREDICT_BEFORE_TRY` **stays default-off**. Part
B ships flag-gated and inert; activation requires re-running this
harness on a real-scale mined table (`--table <runs/feature-table.jsonl>`
from the e2e campaign roots) with a decisive B win on BOTH metrics,
then an owner flip decision (ADR-001 governance pattern).

## Why so small, honestly

No live `runs/e2e/<run_id>/run-state.json` anchors exist on any
reachable root today (checked /tmp/e2e workspaces, kunglao-wt, the
repo runs/ tree); the committed fixture golden is the entire mined
substrate. The harness declares underpower below 3 usable runs so the
same command scales when the campaign data lands — nothing in the
protocol is fixture-specific.
