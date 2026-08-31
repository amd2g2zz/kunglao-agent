# Proposal: project type `web` (labs) — camoufox MCP supply, docker-default channel, CLAUDE.md template, setup/init handlers

## Why

Issue #728 (user directive 2026-08-26): browser JS reverse engineering has no
first-class project type. The upstream MCP server
[camoufox-reverse-mcp](https://github.com/WhiteNightShadow/camoufox-reverse-mcp)
(anti-detection Firefox + JS hook/trace/network tooling) is the missing supply
piece; a web workspace needs its own CLAUDE.md guidance (JS-RE workflow differs
radically from binary RE) and a channel default (docker — no VM channel).

## What Changes

1. `web` joins the project-type union (`init_state.VALID_TYPES`,
   `toolchain.VALID_TYPES`); usage/help/error strings derive or add it.
2. mcp_probe manifest: `camoufox-reverse` (WARN, `types=("web",)`); new
   `web_labs` group. Desktop-only entries (ghidra, sequential-thinking,
   ida-pro-vm, virustotal) pin to `DESKTOP_TYPES` so `web` carries **zero HARD
   MCP requirements** (labs: no binary-RE gate on a browser workspace).
3. CLAUDE.md: `OS_SECTIONS["web"]` delta (constraints + A–E solution-pattern
   decision tree + camoufox ops card) + render-time injection of the
   quick-reference file into the workspace CLAUDE.md (web only).
4. Quick-reference single source:
   `references/re-library/web-re-quickref.md` (six sections + advanced-topic
   index; English; kunglao terminology; upstream facts only as source
   material — expression fully rewritten per the zero-copy discipline).
   `references/_INDEX.md` domain/scenario/per-domain rows +
   `references/_index-web-labs.md`; `_INDEX.yaml` re-pinned.
5. Channel default: web setup handler writes `KUNGLAO_CHANNEL=docker` into
   `analysis_state.txt` when unset and emits setup guidance (docker + one-line
   camoufox + register command). Contract-compatible with #698 (env var name;
   matrix itself stays #698 scope).
6. toolchain: `_check_web` — WARN-only (camoufox MCP probe + docker channel
   presence probe). No HARD item for web (labs).
7. SKILL.md: init usage line + one web line (labs, docker default, camoufox).

## Labs boundary (in scope vs explicitly NOT done)

In scope (minimal integration): type registration, MCP supply declaration,
CLAUDE.md template + quickref, setup/init handler, WARN-only probes,
references/SKILL doc wiring.

NOT done (recorded, not implemented):
- Full reverse toolchain validation for web (real-usage follow-up)
- Upstream skill scripts (sandbox-runner / hook-generator / crypto-identifier /
  check-deps) — capability tools needing CLI discipline
- Upstream delivery-project templates (node-request / python-request /
  vm-sandbox / wasm-loader / browser-auto) — worker deliverables, not scaffold
- Full 35-tool mcp-cookbook manual (wait for real usage)
- Camoufox auto-registration at init (registration stays manual, like every
  other manifest entry)
- KUNGLAO_CHANNEL matrix semantics (#698 in flight)

## Impact

- `scripts/init_state.py`, `scripts/toolchain.py`, `scripts/mcp_probe.py`,
  `scripts/kunglao-init.py`, `scripts/kunglao_resume.py`,
  `scripts/env_check.py` (comment), `hooks/env_check_gate.py`
- `references/` (new quickref + domain index + _INDEX.md + _INDEX.yaml pin)
- `SKILL.md`
- tests: new `tests/test_web_labs_type_728.py`; existing type-triple pins
  updated where the contract legitimately widens (decision options,
  help-text tokens)
