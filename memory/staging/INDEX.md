# kunglao-agent staging memory

Raw observations from in-session work. Each entry is a claim/worker-bound
event (success / failure / discovery / feedback). When 10 entries accumulate,
`scripts/distill.py` distills them into 1 longterm entry (atomic clear).

## Schema
See `../references/memory-protocol.md` and `../scripts/memory_schema.py`.

## Conventions
- Filename: `<YYYY-MM-DD>-<tag>.md` (date = observation date)
- Frontmatter: required `name`, `description`, `metadata.type`, `metadata.originSessionId`, `metadata.modified`
- Body sections: `## Symptom` / `## Repro` / `## Fix applied` (staging-specific)
- INDEX.md is append-only — never edit existing lines

## Index