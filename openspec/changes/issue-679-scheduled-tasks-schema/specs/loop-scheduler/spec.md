# loop-scheduler

## ADDED Requirements

### Requirement: dual-wrapper-shape read
The scheduler registry reader SHALL treat a bare array, a `{"jobs": [...]}` wrapper, and a `{"tasks": [...]}` wrapper (the harness's key, #679) all as recognized shapes, returning the entries of the selected container — jobs preferred when one document carries both keys. A PURE single-key form (the container key and nothing else) SHALL NOT produce a quarantine sidecar; a document carrying extra sibling keys keeps the belt+braces `*.unrecognized-*` sidecar per the fail-open requirement below, even though its entries are read normally.

#### Scenario: harness tasks shape is read, not quarantined
- **WHEN** `_read_entries` reads a file containing `{"tasks": [{"id": "harness-daily"}]}`
- **THEN** it returns that entry and writes no `*.unrecognized-*` sidecar

#### Scenario: both wrapper keys ride one document
- **WHEN** `_read_entries` reads `{"tasks": [...], "jobs": [...]}`
- **THEN** it returns the `jobs` entries (kunglao's container) and a subsequent upsert leaves the `tasks` array untouched

#### Scenario: legacy shapes still read
- **WHEN** the file is a bare array or a `{"jobs": [...]}` wrapper
- **THEN** entries are returned exactly as before this change

### Requirement: write preserves original document shape
The scheduler write path SHALL preserve the original entry-container key (`{"tasks": [...]}` stays a tasks document) and SHALL carry every unknown sibling key (e.g. `schemaVersion`, `owner`) over in place in the MAIN file, replacing only the container's value with the rewritten entry list.

#### Scenario: harness record survives a kunglao upsert byte-for-byte
- **WHEN** a `{"tasks": [...]}` seeded file goes through `upsert_durable_loop`
- **THEN** every harness record's exact serialized bytes (indentation included) still appear in the rewritten file, in original order
- **AND** the kunglao entry is appended once, discoverable via `loop_entry_exists`
- **AND** a second upsert neither duplicates the kunglao entry nor the harness records

#### Scenario: unknown sibling keys survive in the main file
- **WHEN** a file like `{"schemaVersion": 9, "jobs": [...]}` (or `{"owner": "claude-harness", "tasks": [...]}`) is upserted
- **THEN** the rewritten main file still carries `schemaVersion: 9` (resp. `owner: claude-harness`) alongside the updated container

### Requirement: fail-open sidecar backup for still-unrecognized shapes
Anything the reader still does not understand (corrupt bytes, structurally-valid shapes with no known container key such as `{"schedules": [...]}`, documents with unknown sibling keys) SHALL be preserved byte-for-byte in a `*.corrupt-*` / `*.unrecognized-*` sidecar BEFORE any rebuild — never a silent clobber (r3-M1). The sidecar is retained even for shapes the rewrite now preserves in place (belt+braces receipt).

#### Scenario: corrupt file backs up before rebuild
- **WHEN** the registry contains non-JSON bytes and an upsert runs
- **THEN** the original bytes exist in a `*.corrupt-*` sidecar and the entry is written to a fresh document

#### Scenario: unknown container shape backs up and still gains our entry
- **WHEN** the registry contains `{"schedules": [{"weird": true}]}` and an upsert runs
- **THEN** the original bytes exist in a `*.unrecognized-*` sidecar
- **AND** the file afterwards contains the unknown key's data plus exactly one kunglao entry
