# Spec — Hook-table anchor derivation (#675)

## ADDED Requirements

### Requirement: Hook count anchors SHALL be derived from the registry

Every tests/-side expectation about the number of registered hook commands
or the set of registered hook files MUST be computed from
`wire_up_settings.WIRE_UP_HOOK_FILES` (and, for double registrations,
`wire_up_settings.DOUBLE_REGISTERED_HOOKS`) at import/assert time. Hand-pinned
count integers and hand-mirrored registry file lists in tests are FORBIDDEN
outside the sentinel file.

#### Scenario: registry gains a properly-registered hook
- **WHEN** a hook file is added to `WIRE_UP_HOOK_FILES` and `register_hooks`
  gains the matching `_ensure` call
- **THEN** `tests/test_wire_up_settings.py` and
  `tests/test_heartbeat_bootstrap.py` pass with no test-file edit

#### Scenario: anchor re-hardcoded to a literal
- **WHEN** a count anchor is changed back to an integer literal inconsistent
  with the derivation
- **THEN** the anti-repinning guard test fails naming the drifted constant

### Requirement: The double-registration set SHALL live beside the registry

`wire_up_settings` MUST export `DOUBLE_REGISTERED_HOOKS` (frozenset of hook
files registered on more than one event slot), co-located with
`WIRE_UP_HOOK_FILES`. The expected fresh-wire-up command count is
`len(WIRE_UP_HOOK_FILES) + len(DOUBLE_REGISTERED_HOOKS & WIRE_UP_HOOK_FILES)`.

#### Scenario: sentinel pins the export
- **WHEN** `tests/test_hook_registry_singlesource.py` runs
- **THEN** `DOUBLE_REGISTERED_HOOKS` is asserted equal to an explicit literal
  (the sentinel's loud-fail job), so silent membership drift is impossible

### Requirement: The env_check settings fixture SHALL guard registry coverage

`tests/test_env_check.py::_write_settings` (a per-matcher grouping that only
mirrors `register_hooks`) MUST verify at construction time that the union of
files it deploys equals `WIRE_UP_HOOK_FILES` exactly, raising AssertionError
with the symmetric difference on mismatch — a registry growth that forgets
the fixture fails loudly at fixture build, never as a confusing downstream
env-check failure.

#### Scenario: registry grows, fixture forgotten
- **WHEN** a registry hook file is absent from `_write_settings` groups
- **THEN** every test using `_write_settings` fails with
  `AssertionError` naming the missing file

### Requirement: Kicker entry-count anchors SHALL derive from the kicker table

`tests/test_external_kicker.py` per-event entry counts MUST be computed from
`external_kicker.KUNGLAO_HOOK_ENTRIES`, not integer literals.

#### Scenario: kicker table grows
- **WHEN** an entry is added to `KUNGLAO_HOOK_ENTRIES`
- **THEN** the derived counts follow without a test-file edit
