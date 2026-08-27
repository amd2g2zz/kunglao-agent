# Design: web (labs) project type

## D1 — Type union is three call sites, one source per layer

`init_state.VALID_TYPES` feeds init CLI choices, decision-pending options and
the init-marker guard (single source, #304 F6). `toolchain.py` keeps its own
copy (deliberate layer split, comment at :85). Both gain `"web"`; error
guidance strings switch from the hand-written triple to `|`.join(VALID_TYPES)
so the next type addition cannot leave fix-guidance drift behind.

No `KIND_TYPE_HINT` entry for web: web targets are URLs/pages, not sniffable
bin file kinds. Type stays an explicit human choice.

## D2 — MCP manifest: DESKTOP_TYPES decoupling (zero HARD for web)

`mcp_probe.ALL_TYPES = VALID_TYPES` today equals the desktop triple. Once
`web` joins VALID_TYPES, ghidra (HARD) and sequential-thinking (HARD) would
gate a browser workspace — wrong for labs and wrong semantically (browser JS
RE has no decompiler/reasoning-server dependency contract yet).

Decision: define `DESKTOP_TYPES = ("windows", "linux", "android")` in
mcp_probe; ghidra, sequential-thinking, ida-pro-vm and virustotal pin to it
(byte-identical behavior for all existing types); `camoufox-reverse` is the
only web-facing entry, tier WARN. Net effect: web's manifest check can never
FAIL-HARD — matches the labs "no robustness validation" contract and keeps
`overall_status` at PASS/WARN.

virustotal-on-web (URL/domain reports) is a real future use case — recorded
as future-work, not smuggled in.

Registration shape is taken verbatim from the upstream README (verified
2026-08-26): server `camoufox-reverse`, `python -m camoufox_reverse_mcp`,
optional `--proxy/--geoip/--humanize`. Optional flags live in `purpose` text
(placeholder-free register template, same rule as gitnexus).

## D3 — CLAUDE.md: delta in OS_SECTIONS, quickref injected at render

The web delta (constraints + decision tree + ops card) lives in
`OS_SECTIONS["web"]`, same mechanism as the other three deltas (#356 W2). The
six-section quick-reference is a separate single source at
`references/re-library/web-re-quickref.md` — it serves BOTH repo-level
progressive disclosure (domain read path) and the workspace CLAUDE.md
(`write_claudemd` appends its content for web only, fail-closed if missing).
One file, one source, no templates/ duplicate (the drift defect class #356
killed). Quickref content language: English, kunglao terminology
(dispatch/verify, facts/notes, claim, channel, provider) — zero Chinese,
zero sentence-level correspondence to upstream (facts only as source).

## D4 — Channel default: state line, #698-compatible token

KUNGLAO_CHANNEL is #698's env contract (matrix in flight, not on dev). The
labs-scope piece is the default: `_setup_web_env(ws)` writes
`KUNGLAO_CHANNEL=docker` to `analysis_state.txt` via `write_state_line`
(upsert, idempotent) when no channel line exists, and returns the setup
guidance lines (docker hint + one-line camoufox + the register command).
`deploy_env` calls it for `project_type == "web"` right after `_record_mcp`
(guidance prints through the same stderr channel as MCP-missing notices).
The exact env-var token in the state line is the interlock: #698's reader
finds a ready default; nothing here implements matrix semantics.

## D5 — toolchain `_check_web`: WARN-only

Mirrors `_check_linux` shape, minimal surface: `_check_mcp` (camoufox WARN)
plus one docker-channel presence probe (`docker --version` via
`shutil.which`-then-subprocess, timeout-bounded). Absent docker → WARN with
fix text, never FAIL, never HARD. No VM channel check (web's dynamic surface
is the browser, not a VM). No caps path (decompiler trials are meaningless
for web).

## D6 — Test strategy

New `tests/test_web_labs_type_728.py`: type-union, manifest (incl.
anti-fabrication snapshot: every camoufox tool name mentioned anywhere in the
rendered web CLAUDE.md ⊆ upstream-verified tool set), web CLAUDE.md delta
(decision tree + ops card + quickref sections), setup handler state write +
idempotence, toolchain WARN-only, doc wiring (_INDEX.md rows, SKILL.md line),
CLI accepts `--type web` / rejects bogus. Existing triple pins widen where
the contract widens: decision options, help-text tokens. Golden-equivalence
tests keep their windows/linux/android parametrization (web has no pre-#356
reference — excluded on purpose).

## Risks

- #698 worker also edits `tests/test_mcp_supply.py` expected sets — same-file
  merge collision, orchestrator arbitrates at merge time.
- MANIFEST_GROUPS order is pinned as a set-vs-scaffold-key check
  (test_mcp_supply:367) — `web_labs` appended last flows automatically.
- Upstream camoufox tool list (35 tools, v1.1.0) can drift — snapshot test
  documents the verified set and the verify date; refresh is a one-constant
  edit with a re-fetch.
