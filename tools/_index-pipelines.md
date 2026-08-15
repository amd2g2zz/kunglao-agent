# pipelines domain index (tool layer)

> Domain: evidence-index/report pipeline tools. When a worker is dispatched to evidence registration, index building, or report generation tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml). Plan orchestration templates (recipes) live in `tools/pipelines/recipes/*.yaml` (pure data templates, not an executor — see `tools/pipelines/README.md`).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `build-evidence-index` | Evidence index builder (evidence/_index.json + _INDEX.md) | Read when evidence has landed and needs index registration; not for pure analysis without registration |

## Contract entries

### build-evidence-index

- **用途**: Scan the workspace's evidence/ + analysis_artifacts/ and build the evidence index (evidence/_index.json + _INDEX.md).
- **用法**:
  ```bash
  python tools/pipelines/build_evidence_index.py <workspace> --write
  ```
- **输入**: Workspace root (positional, required) + `--write` (persist switch); optional `--out`/`--rel`.
- **输出**: evidence/_index.json + _INDEX.md (eid/path/sha256/source_reliability).
- **exit code**: 0 success / 2 error (missing workspace etc.).
- **when_not**: Not needed for pure analysis without evidence registration.
