# Design: icd203-source-reliability

## Admiralty Code System

Source reliability: A (completely reliable) → F (unreliable).
Information credibility: 1 (confirmed) → 6 (truth cannot be judged).

Combined code: `{letter}{digit}`, e.g. "A1", "C5".

## Mechanical Defaults by Evidence Type

| type        | source_reliability | rationale                                |
|-------------|--------------------|------------------------------------------|
| capture     | A1                 | direct observation, raw instrument capture|
| trace       | A1                 | direct observation, execution trace       |
| dump        | A1                 | direct observation, memory/binary dump    |
| binary      | A1                 | direct observation, raw binary            |
| pcap        | A1                 | direct observation, network capture       |
| decompile   | A2                 | tool-derived from artifact (one step removed) |
| disasm      | A2                 | tool-derived from artifact                |
| yara-scan   | B2                 | tool pattern match (indirect)             |
| json        | B3                 | raw instrument output (possibly indirect) |
| text        | B3                 | unstructured, source varies               |
| cti         | C5                 | third-party threat intelligence           |
| sandbox     | D3                 | third-party sandbox execution             |
| other       | C5                 | unknown provenance, conservative default  |

## Override Mechanism

`--rel reliability_map.yaml` accepts a YAML file mapping eid or type to Admiralty codes:

```yaml
E001: A1
E005: B2
by_type:
  json: B3
  cti: C5
```

Precedence: eid-specific > type-specific > mechanical default.

## Integration Points

- `build_index()`: after entry assembly, call `_assign_reliability(entries, rel_map)`.
- `build_and_write()`: accept optional `rel_map` parameter.
- `main()`: add `--rel` argument.
- `_render_md()`: add source_reliability column to markdown table.
- `measure_blind_coverage.py`: add `--reliability` mode to report coverage.
