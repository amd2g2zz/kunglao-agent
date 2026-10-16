# design — issue-733-arming-shape-law

## The extraction

`_parse_expected` mixed two concerns: the SHAPE law (what counts as a
well-formed `expected`) and the WORKSPACE resolution (#126 — every
non-pending ref must name an existing artifact). The shape law is what
the arming gate needs; the resolution needs `ws` and is the loader's
alone. Splitting them gives each consumer exactly its half:

```python
def expected_shape_error(raw) -> str | None   # the law: first fault or None
def _parse_expected(ws, case_path, cid, raw)  # law + #126 resolution
```

`_parse_expected` wraps the predicate's message with the same
`{case_path.name}: case {cid!r}` prefix as before, so every raise is
text-identical to the pre-refactor behaviour — pinned by the probe
matrix in `test_predicate_is_the_single_source`.

## Why the runner's shape wins

The runner is the executor: it diffs observed stage values against
`expected` entries, so an entry without `field`/`value` cannot
participate in a red/green at all. The old mapping shape carried only
grounding refs — it could never be executed, only observed against,
which is exactly the fabricated-signal hole. One law, defined in the
executor, imported by the observer.

## Failure posture

Unchanged: the gate stays fail-open (`armed_case_ids`/`_cases_by_pq`
skip unreadable docs, never raise), and the parse keeps raising
`OracleCaseError` with the same wrapping.

## Consequences, stated

- **The old mapping shape stops being armed.** This is the intended
  tightening — but it means every dict-shaped armed doc in existence
  loses its armed status until re-authored. The repo's synthetic
  fixtures are migrated here; the live workspace's four docs are NOT
  (data migration, needs per-case domain judgement, tracked on the
  issue).
- **The live workspace's amendment observations stop** until its docs
  are re-authored. Honest: those observations were against docs the
  runner can never execute.
- `armed_case_ids`' loud "no armed cases" warn (run()) now also fires
  for shape-legacy docs — the gap is visible, which is the point.
