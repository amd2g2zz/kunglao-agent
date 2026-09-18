# Tasks — fix-239-plan-first-ownership

- [x] SDD proposal + design + spec delta (this change)
- [x] RED: first dispatch of a fresh claim (no plan file, no reference)
      passes — `tests/test_plan_first_ownership_239.py` (fails on HEAD)
- [x] RED: re-dispatch beyond the planning round without a plan reference is
      still REJECTED; with a worker-authored (anchor-citing) plan it passes
- [x] RED: a plan authored outside the worker's session (no anchor citation,
      pre-dispatch mtime) does not satisfy a re-dispatch (provenance)
- [x] Re-pin existing plan-first tests to the new contract
      (`tests/test_worker_budget.py`, `tests/test_framework_rigidity_57.py`)
- [x] GREEN: minimal `check_worker_plan` change (first-dispatch bypass keyed
      on the approval-point anchor log) + REJECT_FIXES['plan'] re-wording
- [x] Docs: `agents/kunglao-worker.md` golden rule #3 contract change
- [x] `openspec validate fix-239-plan-first-ownership` exits 0
- [x] Full `uv run python -m pytest -q`: no NEW failures vs the 3-failure
      env baseline; stage everything; REVIEW-NOTES-239.md
