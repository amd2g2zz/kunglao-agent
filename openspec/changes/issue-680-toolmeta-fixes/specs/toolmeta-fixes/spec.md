## ADDED Requirements

### Requirement: toolchain.FIXES SHALL be a structured `dict[str, ToolMeta]`

`scripts/toolchain.py` MUST define `FIXES: dict[str, ToolMeta]` where `ToolMeta` is a
frozen dataclass with fields `fix` (remediation guidance text, the legacy string value),
`description` (one-line purpose), `url` (official homepage/docs), `repo` (source
repository, when applicable), `package` (PyPI/npm/apt name, when known), `verify_cmd`
(post-install verification command, for install-able tools). The optional fields MAY be
None; `fix` and `description` MUST be non-empty strings.

#### Scenario: schema shape
- **WHEN** `scripts/toolchain.py` is imported
- **THEN** every value in `FIXES` is a `ToolMeta` instance whose `fix` is a non-empty string, and the dataclass exposes exactly the six fields `fix`, `description`, `url`, `repo`, `package`, `verify_cmd`.

#### Scenario: static entries carry upstream metadata
- **WHEN** FIXES is inspected at import
- **THEN** all static (non-`mcp:`) entries have a non-None `url` starting with `http` and a non-empty `description`. The apkid/baksmali URLs match the ones shipped in #669/#670 (https://github.com/rednaga/APKiD, https://github.com/baksmali/smali/releases).

#### Scenario: install-able tools carry a verify command
- **WHEN** a FIXES key is install-able (`toolchain_install.INSTALL_PLANS[name].kind == "auto"`)
- **THEN** its `verify_cmd` is a non-empty string (e.g. `jadx --version`).

#### Scenario: mcp-derived entries are out of scope and degrade
- **WHEN** `mcp:<name>` entries are derived from `mcp_probe.MANIFEST`
- **THEN** they carry the register command as `fix` and the manifest `purpose` as `description`, with `url=None` (MCP server metadata is out of scope, #680).

### Requirement: string consumers SHALL keep a working string face

`ToolMeta.__str__` MUST render the `fix` guidance text (never a dataclass repr), and
`toolchain.fix_text(name) -> str | None` MUST be the canonical typed accessor. In-repo
string callers (kunglao-init, toolchain_negotiation, deploy_shim, toolchain_install)
MUST use `fix_text()`; unknown names MUST return None so `.get(name, default)` default
semantics are preserved via `fix_text(name) or default`.

#### Scenario: old string callers
- **WHEN** an un-updated caller interpolates a FIXES value into a string
- **THEN** the result is the remediation guidance text, byte-identical to `fix_text(name)`.

### Requirement: operator-rendered fix guidance SHALL put the URL on its own line

`toolchain.format_human` and `kunglao-init.py` refusal output MUST render, for each
non-PASS item with metadata, a `fix:` line followed by a separate `url:` line (only
when the URL is known) and a `verify:` line (only when a verify command exists). An
entry with `url=None` MUST NOT crash and MUST simply omit the `url:` line.

#### Scenario: human output with known URL
- **WHEN** `jadx` FAILs and `format_human` renders the report
- **THEN** the output contains `fix: install jadx and add it to PATH` on one line and `url: https://github.com/skylot/jadx` on its own line.

#### Scenario: unknown URL fallback
- **WHEN** an entry has `url=None` (e.g. an `mcp:<name>` item)
- **THEN** `format_human` renders the `fix:` line without a `url:` line and raises no exception.

### Requirement: `format_json` SHALL keep the fix text and add the URL additively

The `"fix"` key of a check in `--json` output MUST remain the guidance text string
(schema stability for existing consumers) and the check object MUST additionally carry
`"fix_url"` (the known URL or null).

#### Scenario: json output
- **WHEN** a FAIL item with metadata is serialized
- **THEN** `check["fix"]` is the guidance text and `check["fix_url"]` is the URL string (or null when unknown).

### Requirement: `scripts/toolchain_install.py` SHALL read the structured ToolMeta

Install-plan output MUST read the structured fields: the install-failure official
guidance appends `url:` and `verify:` lines from the ToolMeta, and a successful install
prints the verify command before the re-probe. `_official_guidance` MUST keep its
fallback text for unknown names.

#### Scenario: install failure guidance
- **WHEN** a consented install fails
- **THEN** the printed official guidance includes the `fix` text plus the `url` (own line) and `verify` command when the ToolMeta carries them.

#### Scenario: unknown item
- **WHEN** `_official_guidance` is called for a name absent from FIXES
- **THEN** it returns the fallback text "see the toolchain check detail above" (no crash).
