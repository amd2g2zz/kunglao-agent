# Proposal: toolchain.FIXES → structured ToolMeta (#680)

## Problem

User feedback (2026-08-25): external tool addresses and descriptions are missing from
the toolchain check surface. An agent (or operator) hitting a FAIL item gets a one-line
prose fix (`"install jadx and add it to PATH"`) with no upstream URL and no description —
so the agent burns cycles searching for install info and may pick the wrong package.
`#669`/`#670` inlined URLs into two entries (apkid, baksmali) as a partial patch; the
remaining entries are bare text.

`scripts/toolchain.py` `FIXES: dict[str, str]` is the registry (23 static entries + 7
`mcp:<name>` entries derived from `mcp_probe.MANIFEST`). It has no field for a URL, a
one-line purpose, a source repo, a package name, or a post-install verify command.

## Solution

Refactor `FIXES` from `dict[str, str]` to `dict[str, ToolMeta]` where `ToolMeta` is a
frozen dataclass carrying:

- `fix` — the remediation guidance text (the legacy string value, preserved verbatim)
- `url` — official homepage / docs URL (required on static entries)
- `description` — one-line purpose (required)
- `repo` — source repository URL (when applicable)
- `package` — PyPI / npm / apt package name (when known)
- `verify_cmd` — command that verifies the install, e.g. `jadx --version` (for install-able tools)

Every string consumer keeps a working string face: `ToolMeta.__str__` renders the legacy
`fix` text (old f-string callers degrade to the old surface, never `ToolMeta(...)` repr),
and a typed accessor `toolchain.fix_text(name)` becomes the canonical string face for
in-repo callers (all updated).

## Out of scope (issue #680)

- Tool metadata for MCP servers — `mcp:<name>` entries are derived from
  `mcp_probe.MANIFEST` (a separate manifest); they get `fix` + `description` from it and
  `url=None` (the fallback path), no upstream curation.
- Dynamic tool discovery (vs the static registry).

## What changes

- `scripts/toolchain.py`: `ToolMeta` dataclass; `FIXES: dict[str, ToolMeta]` (23 entries
  populated with url + description; repo/package/verify_cmd where applicable);
  `fix_text()` accessor; `next_action_for` mcp branch reads `meta.fix`;
  `format_human` renders the URL on its own line (`url:`) plus `verify:` when known;
  `format_json` keeps `"fix"` as the text and adds `"fix_url"` (additive, schema-stable).
- `scripts/toolchain_install.py`: official guidance / install-plan output reads the
  structured fields — `url:` and `verify:` lines on the install-failure guidance, the
  verify command printed after a successful install (before re-probe).
- `scripts/kunglao-init.py` `refuse_toolchain`: fix text via `fix_text()`, then the URL
  on its own line.
- `scripts/toolchain_negotiation.py`, `scripts/deploy_shim.py`: `FIXES.get(name, ...)`
  string fallbacks switched to `fix_text(name) or ...`.
- `tests/test_toolchain_metadata.py` (NEW): 5 contract tests (issue acceptance list).

## Acceptance

- [ ] `FIXES` is `dict[str, ToolMeta]`; ToolMeta exposes fix/url/description/repo/package/verify_cmd.
- [ ] All 23 static FIXES entries populated with url + description.
- [ ] Install-able tools (FIXES ∩ `toolchain_install.INSTALL_PLANS` kind=auto) carry `verify_cmd`.
- [ ] `url` unknown (mcp entries) → rendering degrades (no url line), no crash.
- [ ] Old string callers: `str(toolchain.FIXES["pefile"])` == the fix guidance text; `fix_text()` is the typed face.
- [ ] `scripts/toolchain_install.py` guidance reads structured fields (url/verify lines).
- [ ] Operator-rendered fix guidance (format_human + kunglao-init refusal) includes the URL on its own line.
- [ ] `tests/test_toolchain_metadata.py` 5 RED → GREEN; no regression in toolchain suites.

## Related

- #669 (apkid — first inline URL), #670 (baksmali — second), #692 (WP2 consumes the ToolMeta pattern), #690 (absolute-path policy — URLs are not path literals, exempt).
