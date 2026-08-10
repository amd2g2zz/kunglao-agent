# Design

## API

```python
def check_provenance_gate(fact_path: Path, ws: Path) -> tuple[bool, str]
```

- `fact_path`: path to the fact markdown file (e.g. `facts/F023-no-network.md`)
- `ws`: workspace root (where `evidence/_index.json` lives)
- Returns `(ok, reason)`: `ok=True` if all provenance refs resolve to index entries with matching sha256; `ok=False` + human-readable reason otherwise.

## Provenance extraction

Fact files contain a YAML frontmatter or fenced block with `provenance:` or `cites:` field listing evidence refs. Supported ref formats per entry:

1. **eid**: `E001` — looked up in index by eid
2. **path**: `evidence/x64dbg-c206-capture.txt` — looked up in index by path
3. **raw path**: `analysis_artifacts/vm_runtime/summary.json` — checked against index (derived files are NOT in index → reject)

The function reads `evidence/_index.json`, builds eid→entry and path→entry maps, then for each provenance ref:
- Resolves ref to an index entry (by eid or path)
- If not found in index → reject ("not in index" or "derived excluded")
- If found, verifies the file exists at `ws / entry["path"]` and sha256 matches

## Design decisions

1. **Pure function, no side effects** — caller passes paths, function reads + returns verdict (same pattern as blind_gate.py).
2. **Index is the single source of truth** — derived files are absent from index, so citing them fails naturally. No hardcoded derivation list in the gate itself.
3. **Hash mismatch = reject** — catches evidence tampering or stale index.
4. **No provenance field at all = reject** — a fact without provenance is not evidence-backed.
5. **Multiple refs allowed** — all must pass; first failure rejects.
