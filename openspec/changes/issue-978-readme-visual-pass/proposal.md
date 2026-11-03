## Why

The README pair carries three defects that undermine the section it exists to
prove. Both READMEs embed `docs/assets/rl-curves.gif`, but the file was never
committed — the reference has been a broken image since the visuals landed
(b09d7299). The two learning measures that matter — how often claims settle and
how many acts each one costs — are described in prose but the chart that was
supposed to show them never rendered, so the section's central claim ("the loop
measures itself") has no visual evidence.

Separately, `README.zh-CN.md` still carries a translation leftover: 「贵得没
prose」的习惯, where "prose" was the English source's noun (an expensive habit
that barely moves the needle) and is meaningless in Chinese.

## What Changes

- Render the missing `docs/assets/rl-curves.gif` as ONE dual-axis chart:
  settle rate on the left axis (22% → 82%), acts per claim on the right
  (11 → 4), both drawn from the same append-only ledger, with ledger rows
  streaming underneath. One chart, one causal story — the crossover is the
  point.
- Add a one-sentence reading key under the chart, in both languages.
- Move the chart below the four-item bullet list so the claims stay together.
- Fix the Chinese sentence to 「花了大价钱却几乎不推进」.
- Normalise straight quotes to 「」 in the Chinese task-statement table.
- Rebuild `docs/assets/rl-comparison.gif`: the closing row said "1 steps".

Docs and assets only — no code, no behaviour change.
