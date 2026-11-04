## Why

The README pair describes the system as it was several releases ago, and two
of those descriptions now actively mislead.

`eval/` left version control (commit 7d5595f4, the corpus is operator-local by
owner directive), yet the README still calls the 12-unit matrix "built-in" —
a reader will look for a suite that is not there. The learning unit is
described as "success/failure tallies per method per state", while `arm_key`
in `scripts/rlvr/q_cells.py` keys on `family|recipe|verif|tier` and appends a
fifth `agent` segment under #705 MARL; the tallies are Beta posteriors and
selection samples rather than taking the argmax.

The comparison grew from five arms to seven — `docs/design/ws5-five-arms.yaml`
declares `cc-bare`, `cc-warm-context`, `cc-multisample`, `kunglao-cold`,
`kunglao-uniform`, `kunglao-warm`, `kunglao-warm-no-l1` — and the README still
says five, dropping exactly the two arms that make the comparison falsifiable.

Finally `rl-loop.gif` prints "1 steps" (the plural defect fixed in
`rl-comparison.gif` last round but missed here) and labels the chosen arm
"highest odds — first pick", which reads as argmax and contradicts the
sampling rule stated in the same section.

## What Changes

- Evaluation: the corpus is operator-local; those rows are measurements, not a
  rerunnable suite.
- Learning: the real key — four dimensions plus the agent segment — Beta
  tallies, sampling instead of argmax.
- Evaluation and roadmap: seven arms, plus the three readouts that separate
  learning value, architecture value and the sampling rebuttal.
- `docs/assets/rl-loop.gif`: "1 step", and "highest odds — likeliest draw".

Docs and one asset. No code, no behaviour change.
