# issue-679-scheduled-tasks-schema

## Why

Live evidence in a workspace: `.claude/scheduled_tasks.json` = `{"tasks": []}` while kunglao's own entries sat stranded in `.unrecognized-*` sidecar files. The harness writes the `tasks` key; `loop_scheduler._read_entries` only recognized `jobs` or a bare array, so on every kunglao upsert it (1) quarantined the whole harness file to `*.unrecognized-*`, (2) treated it as EMPTY, and (3) `_write_file` rebuilt the document as `{"jobs": [...]}` — silently destroying the harness's `tasks` key while exiling kunglao's own next-generation entries to backup files. Two writers, one file, one winner: a schema war kunglao was losing twice (its entries never resided in the live file).

## What Changes

1. **Read**: `_read_entries` recognizes three first-class shapes — bare array, `{"jobs": [...]}` (kunglao's key), `{"tasks": [...]}` (the harness's key, #679). A document carrying both keys treats `jobs` as kunglao's container and `tasks` as foreign data.
2. **Write**: `_write_file` preserves the ORIGINAL container key (`tasks` stays a `tasks` file) and carries every unknown sibling key (`schemaVersion`, `owner`, ...) over in place — the main file keeps them, not just the sidecar.
3. **Fail-open unchanged**: shapes still not understood (`{"schedules": [...]}`) and corrupt bytes keep the r3-M1 byte-for-byte sidecar backup (`*.unrecognized-*` / `*.corrupt-*`) — never a silent clobber. The belt+braces sidecar for sibling-keyed documents is retained.

## Non-goals

- No change to the heartbeat red line (#593): writing the scheduler registry still never fakes `loop_registered`.
- No merging/reconciliation of entries between `tasks` and `jobs` when both ride one document — kunglao owns `jobs`, the harness owns `tasks`, neither rewrites the other's array.
- No migration of existing `.unrecognized-*` sidecars back into live files (recovery is a human/ops decision).
