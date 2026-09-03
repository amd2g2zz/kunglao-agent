## ADDED Requirements

### Requirement: kunglao-init SHALL deploy workspace hooks by default — absence of settings.json is not a legal skip

When init completes a fresh initialization with hooks enabled (the default), `scripts/kunglao-init.py` SHALL create `<workspace>/.claude/settings.json` when absent (minimal `{"hooks": {}}`), deploy the hook registration through the canonical #445 path, and run the post-write self-check. The historical skip branch (`hooks skipped — no <workspace>/.claude/settings.json`) SHALL be reachable ONLY through the explicit `--no-hooks` flag. A deployment self-check failure SHALL exit `RC_HOOK_WIRING=7` as before.

#### Scenario: default init wires hooks
- **GIVEN** a fresh workspace with a sample and `--type windows --skip-toolchain`
- **WHEN** init exits 0
- **THEN** `<ws>/.claude/settings.json` exists and its hooks section contains registry hook commands (self-check PASS), and no "hooks skipped" line appears

#### Scenario: --no-hooks is the only legal skip
- **GIVEN** the same workspace and `--no-hooks`
- **WHEN** init exits 0
- **THEN** `<ws>/.claude/settings.json` is not created by init and the output names `--no-hooks` as the reason

### Requirement: init SHALL deploy the core subagents to the workspace, idempotently

Init SHALL copy `kunglao-worker.md`, `kunglao-redteam.md`, `kunglao-init-worker.md` from the skill repo's `agents/` into `<ws>/.claude/agents/`. A rerun with unchanged sources SHALL leave the targets byte-identical (sha256 guard); a changed source SHALL update the copy.

#### Scenario: core 3 land and stay stable
- **GIVEN** two consecutive default inits of the same workspace
- **WHEN** the second exits 0
- **THEN** all three agent files exist and their sha256 equals the source files' both times

### Requirement: init SHALL record MCP supply state in the env manifest without executing registration commands

Init SHALL probe registered MCP servers via `mcp_probe.registered_names` (the single enumeration implementation) for every manifest item applicable to the project type. Registered items SHALL be recorded `pass`; unregistered items SHALL be recorded `manual` with the item's register command. Init SHALL NOT execute `claude mcp add` (placeholders require human input; auto-registration is #451/#474 territory). The degradation SHALL appear in both the env manifest and stderr.

#### Scenario: unregistered HARD item is recorded, never silent
- **GIVEN** a fresh workspace, type windows, no ghidra registered anywhere
- **WHEN** init exits 0
- **THEN** env-manifest.yaml contains an `mcp:ghidra` component with status `manual`, and stderr mentions the missing registration

### Requirement: aux skills deploy ONLY under --skills

`--skills a,b` SHALL copy the named `skills/<name>` directories into `<ws>/.claude/skills/`. Without the flag NOTHING is installed. An unknown name SHALL fail fast with RC_ERROR listing valid names.

### Requirement: every deployment SHALL land in an env manifest

Init SHALL write `<ws>/env-manifest.yaml` — component name, path, sha256 (where applicable), status, detail — rewritten atomically each run. The manifest SHALL NOT participate in the analysis state hash (deployment ledger, not analysis state; resume must not warn).

### Requirement: deploy_env SHALL expose a plugin_mode seam

`deploy_env(..., plugin_mode=True)` SHALL skip L1 (hooks) and L2 (agents) while still writing the manifest. No plugin form is implemented in this change; the seam is locked by test for #364.
