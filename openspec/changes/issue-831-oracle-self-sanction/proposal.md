# completion_gate second-stop PASS accepts self-authored sanction (#829)

Child of #825.

## Why

`hooks/completion_gate.py:126-140`:

```python
adj = (oracle_early or {}).get("adjudication", {}).get("stop_hook_active", {})
if adj.get("second_stop") and adj.get("last_decision") == "PASS":
    return 0
```

Any write to `task-oracle.yaml` with those two fields passes the stop hook. In the incident the orchestrator wrote `second_stop: true, last_decision: PASS, last_decision_at: 2026-08-31T02:55:00Z` — **backdated 65 minutes before the file's own mtime** — while 3 claims were still open. No sanction-provenance check exists.

## What Changes

- Sanction must carry provenance: settable only via a `runs/oracle-adjudication-*.md` record whose authorship traces to a non-maker session (reuse #825 ledger), plus a monotonic clock anchor: `last_decision_at` ≤ file mtime AND ≥ ts of the newest open_item resolution.
- Cheap immediate fix: reject `last_decision_at` values inconsistent with file mtime ordering — backdating becomes detectable.