# web (labs) project type — Behavioral Spec (#728)

## Type union

- `init_state.VALID_TYPES` and `toolchain.VALID_TYPES` contain `"web"`.
- Every user-facing type guidance string (init usage/help/error, resume
  hint, env_check_gate fix text) enumerates all of VALID_TYPES — derived
  where cheap, hand-written strings list web.
- `kunglao-init --type web` is accepted; unknown types still RC_ERROR.
- No `KIND_TYPE_HINT` entry for web (no file-kind sniff path).

## MCP supply (mcp_probe)

- Manifest carries `camoufox-reverse`: tier WARN, `types=("web",)`,
  purpose names browser JS reverse engineering, register template is
  `claude mcp add camoufox-reverse -- python -m camoufox_reverse_mcp`.
- `MANIFEST_GROUPS["web_labs"] == ["camoufox-reverse"]`; scaffold JSON
  derives the group (set-equality pin stays green).
- NO manifest item of tier HARD applies to web (web can never FAIL-HARD on
  MCP supply).
- Desktop entries (ghidra, sequential-thinking, ida-pro-vm, virustotal)
  apply to windows/linux/android only — behavior for existing types is
  byte-identical.

## CLAUDE.md (web workspace)

- `OS_SECTIONS["web"]` renders: hard-constraints header (web), docker
  channel default, camoufox MCP pointer, the A–E solution-pattern decision
  tree, camoufox ops card.
- `write_claudemd` for web appends the quick-reference content from
  `references/re-library/web-re-quickref.md`; missing file → fail-closed
  render error (never a silently partial CLAUDE.md).
- Rendered web CLAUDE.md mentions ONLY camoufox tool names from the
  upstream-verified snapshot set (anti-fabrication).
- Non-web types render byte-identical to pre-change (golden pins hold).

## Quick-reference single source

- `references/re-library/web-re-quickref.md`: English, kunglao
  terminology, six sections (hook/breakpoint quickref; parameter-location
  workflow; obfuscation recognition; crypto-algorithm signatures;
  anti-patterns; advanced-topic index). Zero verbatim upstream text.
- `references/_INDEX.md`: web-labs domain row, scenario row, per-domain
  index row for `_index-web-labs.md`; `_INDEX.yaml` re-pinned.

## Channel default (#698-compatible token)

- Init for web writes `KUNGLAO_CHANNEL=docker` to analysis_state.txt when
  no channel line exists (idempotent; existing value never overwritten).
- Setup guidance (stderr, same channel as MCP notices): docker hint, one
  camoufox line, register command. No HARD validation, no auto-register.

## toolchain `_check_web`

- WARN-only: camoufox MCP probe (via `_check_mcp`) + `channel:docker`
  presence probe. Absent docker → WARN with fix text, never FAIL/HARD.
- `toolchain.check(ws, "web")` never returns overall FAIL due to absent
  labs tooling; exit code ≤ 2.

## SKILL.md

- Init usage line lists web; one web line documents labs positioning,
  docker default channel, camoufox supply pointer.

## Out of scope (labs)

Robust web toolchain validation; upstream skill scripts; delivery project
templates; 35-tool cookbook; camoufox auto-registration; KUNGLAO_CHANNEL
matrix semantics (#698).
