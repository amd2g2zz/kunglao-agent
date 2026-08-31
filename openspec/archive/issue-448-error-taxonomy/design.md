# Design — Error Response Taxonomy (issue #448)

## Architecture

```
                   docs/error_response_taxonomy.md (SINGLE SOURCE)
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   toolchain_install       error_response.py       init exit code
   (HARD = STOP,           (mechanical classifier,  (table-mapped
    already in tree)        command grammar +        at parse time)
                             stderr signatures)
                                │
                                ▼ UNCLASSIFIED
                       LLM semantic backstop
                       (orchestrator reads docs-as-prompt;
                        lands judgment as structural declaration
                        → routes back to mechanical execution)
```

## Mechanical layer (load-bearing, finite enumeration)

Command signatures (vmrun / kubectl / apt / pip) have a **finite grammar**
— that's where regex works. The classification table is the single map:

- `_RESPONSE_MAP[ErrorClass] → Response`
- `_CHARTER_STATE[ErrorClass] → str` (must-stop / must-ask / etc.)
- `_RATIONALE[ErrorClass] → str` (audit trace)
- `_ALLOWED[ErrorClass] → list[str]` (whitelist)
- `_FORBIDDEN[ErrorClass] → list[str]` (blacklist)

Adding a new ErrorClass requires all five populated — enforced by
`TestTableCompleteness`. Skip a table = CI red.

## Classification algorithm

```
classify_vmrun(stderr)        — vmrun signature regex, zho+en
classify_init_exit(rc, stderr) — table lookup on rc
classify_tool_install(stderr)  — degrade_report HARD pattern

Order inside each classifier:
  1. specific signature (cancel / lock / timeout / channel / identity)
  2. higher-priority signals first (review-gate BLOCKED > others)
  3. UNCLASSIFIED as last resort -> rc=2 in CLI (LLM backstop signal)
```

## Priority statement

```
HARD human-event gate (review-gate BLOCKED, init exit 3/4)
  > default allowed rule (hard prohibition #1)
```

Evidence: issue #448 T1 — agent hit init exit 4 then kept scanning /24
subnets. Default-allowed rule is the wrong baseline for this class.
This priority is declared in:
- `rules/kunglao-convergence-loop.md` (prohibition #1 footnote)
- `docs/error_response_taxonomy.md` (priority section)
- `Classification.rationale` ("Hard priority over the default allowed rule")
- `tests/test_priority_over_default_allowed.py::test_exit_4_stops_*`

## Files

| File | Lines | Role |
|---|---|---|
| `docs/error_response_taxonomy.md` | ~70 | single source of truth |
| `scripts/error_response.py` | ~220 | mechanical classifier + CLI |
| `tests/test_error_response.py` | ~190 | 31 tests |
| `rules/kunglao-convergence-loop.md` | +5 | priority declaration |

## Risks

- **Regex miss-recall** — same as #447 doctrine: mechanical covers known
  signatures; LLM backstops the rest (UNCLASSIFIED -> rc=2 -> LLM
  semantic review). Same trade-off.
- **Stderr language drift** — vmrun signatures are partly English and
  partly Chinese. Enumeration is bounded per command but not per-language;
  LLM backstop fills gaps.
- **Toolchain version drift** — vmrun stderr wording changes between
  versions. The patterns cover currently-observed phrasing; new phrasing
  flows through UNCLASSIFIED -> LLM -> declaration -> table update.

## Open

- Should `toolchain_install.py` degrade_report call `error_response.classify_*`
  to emit the JSON shape, or just emit `Response.STOP`? — Phase 2.
- runtime hook for orchestrator stderr capture? — follow-up.