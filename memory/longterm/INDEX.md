# Kong-agent longterm memory

Distilled rules — cross-project, claim-stripped, forward-looking. Each entry
was synthesized from ≥10 staging entries by `scripts/distill.py` (atomic
transaction; snapshot at staging/.snapshot/<timestamp>/).

## Schema
See `../references/memory-protocol.md` and `../scripts/memory_schema.py`.

## Conventions
- Filename: `<YYYY-MM-DD>-distill-N.md`
- Frontmatter: required `metadata.cross_project: true`; `claim_id` and `worker_id` MUST be absent
- Body sections: `## Rule` / `## Examples` (longterm-specific, replaces Symptom/Repro)
- Source traceability: `metadata.source_staging` lists the 10 staging entries that produced this rule

## Index