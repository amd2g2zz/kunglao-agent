# Anomaly detection baseline corpus (issue #663)

`scripts/anomaly_detector.py` scores each fact against a **baseline corpus** to surface "this is unusual" observations (per design.md D1, D2). This document specifies how the baseline is built and how operators tune it.

## Three sources, merged (per design.md D2)

The baseline corpus is the union of three frequency dictionaries
(`term_freq`, `pair_freq`, `path_freq`):

1. **RE-library pattern docs** — every `.md` under `references/re-library/`.
   Each doc contributes `+1` to `term_freq` per tokenized word (heuristic
   best-effort; structured ingestion is a followup).
2. **Prior completed samples** — `~/.kunglao/samples/` (each `bins/<sha>/`
   workspace contributes its `facts/_INDEX.md` conclusions).
   Currently **empty** — wired but not populated (planned alongside #358
   P4 v0.2 batch). Future: when this lands, the baseline grows
   automatically as the analyst completes samples.
3. **Operator-provided patterns** — `analysis_state.txt` line
   `baseline_corpus: <path>`. Optional manual augmentation.

The scanner reads each source, increments frequency counters, and merges.
All three sources are independently optional — missing source =
`term_freq` / `pair_freq` / `path_freq` is empty for that source, which
fails-open per design.md D5.

## Fail-open semantics (per design.md D5)

`scripts/anomaly_detector.py` fails open in three layers:

- **Baseline missing** (`term_freq` etc. all empty): `score_fact` returns
  `0.0` for every fact; `scan_anomalies` returns `[]`. The DRAIN stage of
  `convergence_check.decide()` does NOT fire `ANOMALY_DETECTED`. The
  cold-start loop never blocks on a missing baseline.
- **Baseline file unreadable** (corrupt / permission): same as missing —
  warn once via `kunglao_log`, continue with empty baseline.
- **Single fact unreadable** (parse failure): skip that fact, continue with
  others.

Rationale: anomaly detection is a **reader attention** mechanism, not a
correctness gate. Failing closed would BLOCK every convergence when the
baseline corpus is empty (cold-start), which is the worst case for an
analyst who needs the rest of the loop to proceed. Correctness remains
with the contradiction gate (#147) and the maker-checker FAIL_CLOSED
(#98).

## Operator tuning knobs

| Knob | Where | Default | Effect |
|---|---|---|---|
| `anomaly_threshold` | `analysis_state.txt` | `0.7` | Per-engagement sensitivity. `0.5` flags more, `0.9` flags only extreme. |
| `baseline_corpus:` | `analysis_state.txt` | unset | Operator-provided patterns file (third source above). |
| `RE-library/` | `references/re-library/` | built-in | Token frequency ground truth. |

## Outputs of `scan_anomalies`

For each PROVEN fact whose score ≥ threshold, returns:
```python
{
    "fact_id": "<F-NNN-slug>",
    "claim_id": "<C-NNN>",
    "score": <float in [0, 1]>,
    "top_dimension": "lexical" | "semantic" | "path",
}
```

The integration with `convergence_check.decide()`:
- If anomalies list is non-empty, DRAIN verdict becomes `BLOCKED` with
  reason naming each anomaly (fact_id + score + top_dimension).
- If empty, DRAIN proceeds normally (`DRAIN_CLEAN` → `CONVERGED`).

## Maker-checker boundary (per design.md D8)

An anomaly is **observation, not verdict**. The fact's own status
(`PROVEN`, `INFERRED`, etc.) is preserved — anomaly never triggers a
STAMP downgrade in `claim_migrator`. The anomaly surfaces as a
co-resident note at `notes/<fact_id>.md` (helper:
`anomaly_detector._write_anomaly_note`) for analyst review:

- **Confirm** (note stays, doc the anomaly) — analyst's explicit verdict
- **Refute** (delete note, extend `baseline_corpus:` in `analysis_state.txt`)

If a future change needs anomaly-driven STAMP downgrade, that's a
separate openspec change (the current openspec explicitly excludes it).

## Examples

```text
# Common API call -> score ~0
$ python scripts/anomaly_detector.py tests/_fixtures/workspace --json
{"anomalies": [], "count": 0}

# Rare syscall with unknown path -> score ~1.0
$ python scripts/anomaly_detector.py tests/_fixtures/workspace --json
{
  "anomalies": [
    {"fact_id": "F042", "claim_id": "C-12", "score": 1.0, "top_dimension": "path"}
  ],
  "count": 1
}
```

## Related

- `scripts/anomaly_detector.py` — implementation (mirrors this doc)
- `scripts/convergence_check.py` — `ANOMALY_DETECTED` DRAIN event consumer
- `scripts/lint_facts.py` — `boundary_type: anomaly` accepted; `ACTIVE_SCHEMA_REV = 2`
- `templates/fact-frontmatter.md` — schema_rev bumped to 2 (consistency)
- Issue #663 — origin discussion
- #358 P4 v0.2 batch — re-library gap-fill will grow the baseline (planned)

recall_useful: pending
