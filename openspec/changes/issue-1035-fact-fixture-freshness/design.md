## Context

The production fact linter compares review dates with the local calendar date and warns after 30 days. The shared factory currently fixes both dates to one historical day.

## Decisions

Generate both dates from one local current-date reading, so they match the linter's calendar and cannot be backdated relative to one another. Tests control the calendar at two distinct dates and run the real lint rule on fresh and explicitly aged facts.

## Risks / Trade-offs

A fixture crossing midnight between creation and lint remains fresh; no production date policy changes are needed.

## Integration contract

Tests of settlement and fact guards call `write_certified_fact` when preparing a workspace. The generated frontmatter carries matching current `created` and `last_reviewed` dates; linting it must not emit `STALE_LAST_REVIEWED`, while a review older than the configured threshold must emit that fingerprint. This preserves the settlement test path supporting INV-003.
