# issue-991-changelog-unreleased — design

## Decision 1: `[Unreleased]`, not a numbered section

The owner has not fixed the next release number. Explicit rule:

- not fixed → `## [Unreleased]`
- fixed → `## [0.1.6-rc3] - YYYY-MM-DD`

A numbered heading would assert a release identity that does not exist,
and would desynchronise the changelog from the two version sources that
`tests/test_changelog.py::test_manifest_and_pyproject_are_0_1` pins to
`0.1.6-rc2`. Do not back-date or rewrite the rc2 section.

The existing test module already anticipates this shape: its
`test_changelog_references_issue_numbers` scopes the v0.1 completeness
invariant to the `## [0.1]` section precisely so that a newer
`[Unreleased]` section does not inherit it.

## Decision 2: the contract lives in the existing test module

Appending two tests to `tests/test_changelog.py` keeps TDD honest
(RED: `missing [Unreleased] section`; GREEN: 5 passed) without adding a
new test module. A new module would require registration in
`tests/_tiers.py` and the #807 test inventory, which is governance churn
unrelated to a documentation change.

The contract checks mechanically verifiable properties: heading position,
three subsections, ≥12 bullets, a `(#NNN)` reference per bullet, one
representative issue per wave, the literal `SUPERSEDES` / `fail-closed`
wording, and all five HARD class names.

## Decision 3: the #801 reversal is a Changed entry, not a Fixed bullet

`hooks/gate_policy.py` explicitly supersedes the 2026-09-28 owner ruling
that a crashed gate must fail-closed. Five HARD classes still block;
`format` and `self_health` now proceed with rc 0 plus a sidecar row and
a `gate_warn` ledger row. Filing this under `### Fixed` would misrepresent
a deliberate widening of the enforcement posture as a defect repair.
Compensating observability is recorded but is not described as blocking.

The separate question — whether the five call sites in
`dispatch_gate.py::_reject_with_guidance` that still take the default
`gate_class="format"` are correctly classified — is out of scope here and
is flagged in issue #991 for an owner decision.

## Decision 4: no version-source edits

`pyproject.toml`, `release-manifest.yaml`, tags, release notes and the
dev → master merge belong to the release-checklist gate, not to this
change. Keeping them untouched also keeps
`scripts/release_receipt.py --check` green.

## Verification

- `python -m pytest -q tests/test_changelog.py` → 5 passed.
- Full `python -m pytest -q` baseline on the branch.
- `npx openspec validate issue-991-changelog-unreleased` → exit 0.
- `uv run python scripts/release_receipt.py --check` → rc 0.
