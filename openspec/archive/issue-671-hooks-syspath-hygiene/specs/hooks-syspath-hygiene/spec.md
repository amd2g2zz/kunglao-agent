## ADDED Requirements

### Requirement: hooks/ SHALL contain no bare sys.path.insert calls

Every `.py` file under `hooks/` SHALL be free of direct
`sys.path.insert` invocations, enforced by the guard
`tests/test_syspath_hygiene_671.py`. The single whitelist entry is
`hooks/_path_hygiene.py` — the module that IS the insert authority; every
other hook file obtains path membership exclusively through the hygiene
API. (Count basis at adoption: 31 sites / 13 files on dev `2b7f946`;
issue #671 filed 11; the dispatch-time sweep said 32 — the actual count
governs.)

#### Scenario: guard passes on the migrated tree
- **WHEN** the guard scans `hooks/` after the 31-site migration
- **THEN** it reports zero bare `sys.path.insert` occurrences and passes

#### Scenario: guard flags a planted violation (negative sample)
- **WHEN** a file containing a bare `sys.path.insert` is planted under a tmp root and the scanner runs on that root
- **THEN** the scanner reports the file and line, proving the guard can go red

#### Scenario: whitelist is exactly the authority module
- **WHEN** `hooks/_path_hygiene.py` contains `sys.path.insert`
- **THEN** the guard does not report it, and no other whitelist entry exists

### Requirement: scoped sibling imports SHALL restore sys.path

Function-scoped sibling imports SHALL use the `on_path(target)` /
`scripts_on_path()` context managers: membership for the duration of the
block, exact-entry removal on exit, and — when a resolved-equal entry is
already on sys.path — no insert, no pop, and no position change (the
reordering of an existing entry is as forbidden as leaking one: pytest's
session path already orders `hooks` before `scripts`, and flipping that
order is what broke the ambiguous `lib_kunglao` import).

#### Scenario: sys.path unchanged across a real hook entry
- **WHEN** a hook entry point that imports a scripts/ sibling (e.g. `completion_gate._kunglao_active` with a planted `.hook_state.json`) runs to completion
- **THEN** `sys.path` afterwards equals its pre-call snapshot

#### Scenario: already-present target is not reordered
- **WHEN** `on_path` wraps a target that is already on sys.path (not at position 0)
- **THEN** the entry stays at its position during and after the block

### Requirement: module-level membership SHALL be idempotent and position-stable

Module-level long-lived membership SHALL go through
`ensure_on_path(target)` / `ensure_scripts_path()`: at most one insert per
resolved target per process (ledger-deduped), and a target already on
sys.path is left where it is. The #568 order-robust bootstrap of
`hooks/worker_budget.py` SHALL keep its move-to-front semantics via
`ensure_on_path(target, front=True)` — remove any copy, insert once at
position 0.

#### Scenario: repeated ensures add no entries
- **WHEN** `ensure_scripts_path()` is called three times in one process
- **THEN** sys.path contains exactly one resolved-equal entry for scripts/ afterwards

#### Scenario: pre-present target is not moved
- **WHEN** the target is already on sys.path at a non-zero position and `ensure_on_path(target)` runs
- **THEN** the entry's position is unchanged (no anti-flip violation)

#### Scenario: front bootstrap moves without duplicating
- **WHEN** `ensure_on_path(target, front=True)` runs with the target present mid-list
- **THEN** the target ends up exactly once, at position 0
