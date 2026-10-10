# step-record-667 delta — issue-667-step-experience-ledger

## ADDED Requirements

### Requirement: Every tool call lands one hash-only step row

The shadow PostToolUse capture SHALL append one `step-record/1` row per
tool call (schema, ts, session_id, call_id, tool, input_sha, output_sha,
reads, writes, duration_ms) where every content-bearing field is a
sha256 — raw prompt/output/file content SHALL NOT appear in any row.
Recording SHALL be fail-open: any error yields no row and never blocks
the tool flow.

#### Scenario: a Bash call lands a hash-only row

- **WHEN** a Bash tool call completes in a workspace
- **THEN** runs/step-ledger.jsonl gains one row whose fields are the
  schema stamp, event ts, session id, call id, tool name, and shas —
  and no raw command/output text appears anywhere in the file

#### Scenario: a broken workspace never blocks the flow

- **WHEN** the workspace cannot be resolved or the ledger is unwritable
- **THEN** the hook exits 0 with no row and no error surface
