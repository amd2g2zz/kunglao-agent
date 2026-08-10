# Spec Delta: evidence-index

## source_reliability field

Every entry in `evidence/_index.json` MUST include a `source_reliability` field
containing an Admiralty code (letter A-F + digit 1-6, e.g. "A1", "C5").

### Assignment Rules

1. Mechanical default by `type` field (see design.md table).
2. Override via `--rel reliability_map.yaml` (eid-specific or type-specific).
3. Maker can override in fact-level metadata (future P5 scope).

### CLI

```
python build_evidence_index.py <workspace> [--write] [--rel reliability_map.yaml]
```
