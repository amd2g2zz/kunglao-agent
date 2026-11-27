# Design — issue 1005, C1 s1

## D1. Where the worker rows actually are (measured, not inferred)

The chain's premise was verified against the local corpus rather than
re-asserted:

```
20 real sessions that dispatched workers:
  isSidechain:true rows in the MAIN transcript      0  (0 in all 20 sampled)
  worker rows                                        in <session>/subagents/agent-*.jsonl
  those rows carry isSidechain: true                 (probe over 3 files: 340/370, 129/143, 643/643)
```

So the fix is a read-domain change, not a field-name change: the gauge must
read the session, not one file. Folding the worker files' sidechain output
rows into the analysis side makes the shipped `0` become 140 … 11,725,237
tokens on those same 20 sessions, and the ratio leave `machine/1` for
115–2546.

## D2. The machine side stays put

Counting worker files' rows through the same flag rule (sidechain →
analysis output only) keeps the machine numerator exactly what it was.
Folding worker input tokens into it would have moved the ratio's numerator
in the same change that moved its denominator — the gauge's stated meaning
(machine-overhead input over analysis output) would no longer be
comparable with any earlier sample. Pinned by
`test_worker_input_tokens_do_not_enter_the_machine_side`.

## D3. A pure memo, not a cursor

Sampling happens once per Edit/Write/Agent call. Two designs were
available:

| | incremental byte cursor | (size, mtime_ns) memo |
|---|---|---|
| correctness depends on persisted state | yes (a wrong offset is a wrong number) | **no** (miss ⇒ recompute) |
| partial-line handling | needed | not needed |
| cost per sample | new bytes only | new/grown files only |

The memo won because a measurement face must not become wrong because its
cache was wrong. Corrupt or absent memo ⇒ full recompute, same number
(pinned). Measured on the worst real session (887 MB main + 1.5 GB across
307 worker files), two runs of the same pair: full fold 21.19 s then
memoized repeat 11.17 s; under a concurrent test load 30.05 s then 11.65 s.
The remainder is the main transcript, which the shipped gauge already
re-read in full on every sample — memoizing it needs the cursor design and
is out of this slice.

## D4. Dollars: harvest what exists, never invent what does not

`cost-state` rows carry the CLI's own cumulative `totalCostUSD`. Census over
the 25 real session rows whose cost face is empty: **11 of them still resolve
to a transcript** (3 workspaces were deleted, 11 rows recorded no workspace),
and **1 of those 11 carries a cost-state row** ($5.0409120000000005, a session
that exited rc=1 on its own). So the dollar path is real but reaches 1/25 of
the population; the token path reaches 11/25. No measured kill shape left a
cost row either: over the 5 located transcripts of `rc=143` empty-cost rows the
count is 0 (s2's census), and one controlled run — `claude -p` with the base URL
pointed at a closed port, then SIGTERM — exited 143 with empty stdout and
`cost_state_rows=0`. That is n=5 real plus n=1 controlled, not a proof for every
future CLI build; the fallback therefore reads the row rather than assuming its
absence.

Pricing the usage rows was then checked, not assumed:

```
one session, same file, two accounts (f98e67f2):
  transcript usage rows, glm-5.3-flash:  in=1,468,628 out=343,953 cr=23,840,896
  CLI modelUsage "glm-5.3-flash[1m]":    in=  215,870 out=  31,441 cr= 1,257,088
  CLI modelUsage "claude-sonnet-5[1M]":  in=  175,022 …  (a model no usage row names)
```

The name spaces do not join and the populations diverge per model (measured
on one session: input 6.8x, cache-read 19x; the mixed grand totals of the two
populations are 2.8x), and the CLI's own row says `hasUnknownModelCost=True`.
So a rate table would put killed sessions on a different money scale than the
completed sessions they are compared against — the exact failure mode the
brief warns about. The fallback therefore reports dollars only where the
CLI wrote them, always reports the token account, and writes the reason
when there is no number.

## D5. Precedence

stdout wins whenever it carries a dollar figure, and then the transcript is
not opened at all (one extra filesystem walk per completed session would
buy nothing). Otherwise the transcript face is used; when no transcript
qualifies, `session_cost` keeps its old shape (`None`) so the change cannot
manufacture a face where nothing was measured — that also keeps the
existing crash-row pin (`session_cost is None`) true for the cases it
covers.
