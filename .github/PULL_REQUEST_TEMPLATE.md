## Summary

<!-- What this PR changes and why. One short paragraph. -->

## Issue linkage (REQUIRED)
<!-- Every PR closes exactly one issue (one-issue-one-branch-one-PR).
     Use the closing keyword so GitHub auto-closes on merge: -->
Closes #

<!-- Milestone of the linked issue: -->
Milestone:

## Anti-orphan gate (REQUIRED)

Every PR that adds or moves code MUST answer both. A "TBD" or "see code"
answer blocks the PR.

1. **Who reads this at runtime?** (name the consumer module + call site,
   e.g. `hooks/worker_budget.py:1383` reads `facts/_INDEX` via
   `_load_index()`.)
2. **What state transition writes this?** (name the trigger + writer,
   e.g. `update_index.py:main()` writes `_INDEX` after a fact status
   change; triggered by `kunglao-record.py claim promote`.)

<!-- For doc-only / test-only / template-only changes with no runtime
     surface, state "N/A — no runtime surface" and name what the file
     replaces or locks instead. -->

## Test plan

- [ ] `.venv/bin/python -m pytest <touched suites> -q`
- [ ] `/usr/local/bin/ruff check <touched .py files>`
- [ ] `python scripts/release_receipt.py --check` (if assets/manifest changed)

## Labels
<!-- capability:<axis> + theme:<area> + type; difficulty:hard for heavy PRs -->
