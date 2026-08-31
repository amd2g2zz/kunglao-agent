# Spec delta: kunglao upgrade (#726)

## ADDED requirement: workspace scaffold upgrade

`kunglao upgrade <ws> [--dry-run]` SHALL bring a stale workspace's framework
scaffold up to the current skill version.

### Scenario: v0.1.2 workspace upgraded
- **WHEN** a workspace stamped 0.1.2 with 9-hook settings and a
  `.hook_state.json` missing `completion_gate` is upgraded
- **THEN** hooks are re-registered to the full current registry (incl.
  `orchestrator_tool_guard.py`, `violation_capture.py`), ALWAYS_ARMED
  membership is repaired, all three stamp carriers carry the current
  version, an upgrade record is appended to `runs/.init-report.json`, and
  `.agent/specs.yaml` is seeded if absent

### Scenario: user data is byte-invariant
- **WHEN** the upgrade runs
- **THEN** the sha256 digest (stamp-line-normalized for
  `facts/_INDEX.md` and `claim-register.yaml`) of every file under
  `claims/ facts/ runs/ hypotheses/ notes/ evidence/ oracle/` is identical
  before and after; any mismatch MUST abort with exit code 4

### Scenario: dry-run
- **WHEN** `--dry-run` is passed
- **THEN** the planned migration steps are printed and no file is written

### Scenario: already current
- **WHEN** the workspace stamp equals the skill version
- **THEN** the command is a no-op reporting "already at version" with exit 0

### Scenario: unknown origin
- **WHEN** the workspace has no readable version stamp
- **THEN** the command refuses with exit code 3 and guidance to run init

### Scenario: snapshot and events
- **WHEN** a real (non-dry) upgrade runs
- **THEN** `runs/upgrade-snapshot.<ts>.json` holds pre-upgrade framework-file
  hashes, and `kunglao_log` receives one `upgrade_item` event per applied
  item plus one `upgrade` summary event
