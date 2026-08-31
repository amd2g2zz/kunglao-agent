# Spec — Error Response Taxonomy (issue #448)

## Requirement: a single source of truth

`docs/error_response_taxonomy.md` SHALL be the only document defining
how action errors are classified. No code or rule may state a response
action (retry / retry-once / ask / stop / escalate) to a specific error
class without referencing the taxonomy.

## Requirement: mechanical classifier is load-bearing

`scripts/error_response.py` SHALL classify each known error class via
mechanical signal matching (command signatures, exit codes, stderr
patterns). The classifier is the load-bearing layer; LLM backstops only
UNCLASSIFIED cases.

## Requirement: every ErrorClass appears in all five tables

For each `ErrorClass` enum value, all of the following MUST be
populated (non-empty, with no fallback defaults):
  - `_RESPONSE_MAP[cls] -> Response`
  - `_CHARTER_STATE[cls] -> str`
  - `_RATIONALE[cls] -> str`
  - `_ALLOWED[cls] -> list[str]`
  - `_FORBIDDEN[cls] -> list[str]`

Adding a new ErrorClass without updating all five tables MUST fail CI
(enforced by `TestTableCompleteness`).

## Requirement: priority statement

`HUMAN-EVENT-REFUSE` MUST be classified `STOP` and MUST carry
`proxy_repair` and `continue_silently` in `forbidden_actions`. The
priority is declared in:
  - `docs/error_response_taxonomy.md` (priority section)
  - `rules/kunglao-convergence-loop.md` (prohibition #1 footnote)
  - `Classification.rationale` (string-level audit trace)
  - `tests/test_priority_over_default_allowed.py`

## Requirement: UNCLASSIFIED default = ASK (safest)

When mechanical layer returns `ErrorClass.UNCLASSIFIED`, the response
MUST be `ASK` (not `STOP`, not `RETRY_ONCE`, not `ESCALATE`). The CLI
MUST exit with code 2 to signal the LLM-backstop recommendation.

## Requirement: bilingual signatures

Command signatures cover both English and Chinese phrasing (vmrun stderr
is observed in either). Coverage is **non-exhaustive** by design; the
`UNCLASSIFIED` default handles misses.

## Requirement: forbidden actions are explicit

Each `ErrorClass` MUST list at least one forbidden action in
`_FORBIDDEN`. Reasoning: a classification without "things you must NOT
do" is non-actionable.

## Requirement: regression fixture for #448 evidence

`tests/test_priority_over_default_allowed.py::test_exit_4_stops_*`
MUST be present and MUST assert:
  - `classify_init_exit(4).response is Response.STOP`
  - `"proxy_repair" in forbidden_actions`
  - `"continue_silently" in forbidden_actions`
  - `"must-stop" in charter_state`

## Requirement: CLI shape

```
scripts/error_response.py classify --kind <vmrun|init-exit|tool-install>
                                   [--stderr "..."] [--exit-code N] [--json]
```

Exit codes:
  - 0 = classified
  - 2 = UNCLASSIFIED (LLM backstop)
  - 1 = usage error

JSON output schema (when `--json`):
  `{kind, input, class, response, charter_state, rationale,
   allowed_actions, forbidden_actions}`