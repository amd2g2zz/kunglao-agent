# Design: issue-755 — upgrade 部署面补齐 (+ issue-758 G2/G3)

## D0. Wave-1 reuse (no new machinery)

- A2 imports `hook_activation.canonical_install_root()` (#752) for the
  executing-install source face; `_deploy_agents` semantics (#478) are
  mirrored, not re-invoked through init (upgrade stays a light process).
- G3 merge rides #758's `template_version.frame_section_current /
  frame_headings_from_text / expected_frame_headings` for all
  frame-ownership decisions — one heading-skeleton authority.
- New migration items slot into the #753 driver untouched: git anchor →
  migrations → iron-rule digest → guarded tail. All items are WARN-only by
  construction (item-internal try/except → label suffix), so no new exit
  codes exist.
- The A7 local-python WARN rides the #758 `_warn_python_version` channel;
  failure WARNs ride `_emit_event` (#753 B2).

## D1. T6 version-number ruling: NEW ENTRY "0.1.4"

Prompt decision point ("选新 entry 0.1.3.1 或 0.1.4"). Chosen: **0.1.4**.

Rationale:
- `MIGRATIONS` compares with tuple-of-int keys (`_vkey`); a four-segment
  "0.1.3.1" would work mechanically but breaks the three-segment release
  lattice that pyproject/plugin.json/release-manifest share (target bump is
  owned by the release flow; a tri-segment entry needs zero special cases).
- Live-run-style workspaces already stamped 0.1.3 currently short-circuit
  (`origin_key >= target_key` + empty plan). With entry "0.1.4" present,
  `plan=[("0.1.4", …)]` even while the skill target string is still 0.1.3 —
  the items run today and remain reachable until the release flow bumps the
  skill to 0.1.4, after which stamps converge naturally. Re-runs of an
  already-applied plan are noop-by-construction (every item idempotent).
- Transitional honesty note: a 0.1.2→run executes migrate_to_0_1_3's stamp
  item BEFORE the 0.1.4 merge fixes the frame; its gate then skips
  (frame-drift), and the belt-and-braces tail re-stamps AFTER the merge —
  the end state is the honest one. Documented transient, not bypassed.

## D2. G2 — frame markers

Marker pair (versioned open):
```
<!-- kunglao:frame:v<skill-version> -->
<!-- /kunglao:frame -->
```
- init `write_claudemd` wraps the ENTIRE final text (post python-note +
  quickref steps) — the goldens are regenerated from the same sentinel path.
- Version = current skill version at render time (single source:
  `template_version.read_skill_version`).
- Unmarked scanners are unaffected: HTML comments carry no heading syntax.

## D3. G3 — collect-and-merge (`scripts/claudemd_frame.py`)

Three segments per the prompt: 需求段 / 定制段 / 新框架段.

Split strategies:
1. MARKED doc → regions are byte ranges around the markers; out-of-marker
   bytes are user content, preserved verbatim in order.
2. LEGACY (unmarked) doc → heading-walk classifier against
   `expected_frame_headings()`: in-order matches own their span
   (heading→next-heading) as frame; any OTHER *headed* section is user
   content. Untitled prose captured inside a would-be frame span cannot be
   distinguished from template paragraphs, so it is RELOCATED verbatim to
   the post-frame tail — unless it appears verbatim inside the freshly
   rendered frame (dedup), which keeps today's real v0.1.2 renders clean.
3. If neither split can place every expected heading of the current frame
   (hand-written bodies like "# old workspace"), the merge REFUSES:
   skip + WARN, body byte-untouched — 宁可旧也不要错删 (mirrors the #758
   stale-body posture). This is what keeps Wave-1's synthesized-workspace
   tests honest.

Requirement segment: the exact `## Task constraints (task_spec)` block is
extracted wherever it sits (marked or legacy), removed from its position,
and injected into the fresh frame's `{{task_spec_section}}` slot — bytes
unchanged.

Frame rebuild params are derived workspace-side (init parity):
project_type ← `.kunglao-init.json` → `analysis_state.txt project_type=` →
default; sample name/sha256 ← single-file `bins/`; type row parsed back
from the old Sample table when present; skill_dir ← canonical install root
(#752); venv_path ← `.venv/` existence (init rule). Rendering goes through
the SAME strict engine and post-render steps as init (extracted helper,
no copy).

Assembly order: [pre-frame preamble minus scrubbed stamp lines] →
[new marked frame incl. requirement slot] → [user sections in original
relative order] → [relocated legacy prose]. Stamp refresh itself stays
owned by the G4 gate afterwards.

## D4. T3 config trio

- `.mcp.json`: missing → `mcp_probe.build_scaffold_json()` scaffold
  (single source — the same builder init's `scaffold_mcp` writes);
  existing → report-only (users may have registered servers there).
- `env-manifest.yaml`: missing → #478 LEDGER shape written (generated /
  project_type / components) — NEVER the env-facts manifest shape (the
  loader's discriminator rejects ledger-shape facts files; a fabricated
  "version:" key would be a lying artifact). Channel component row comes
  from `init_channel_default.resolve_init_channel` (#727 fail-open);
  defaulted-local records the WARN on the row + event. Existing → refresh
  the additive `kunglao_version` field only (a `version:` key must never
  exist on this file — see discriminator). Deep channel semantics stay with
  parallel-wave #757; upgrade only ever CREATES or bumps metadata here.
- Toolchain manifest (A6, code-reality ruling): init deploys NO dedicated
  toolchain lock/manifest file today (checked kunglao-init deploy surface).
  The durable faces ARE `runs/.init-report.json` telemetry (iron-rule-exempt)
  and `.kunglao-init.json`. Item contract: existence check + report event;
  an existing .init-report gets its `skill_version` field refreshed — and
  upgrade NEVER fabricates either artifact (an invented state_hash /
  probe record would be a lying marker; absence reports point at re-init).

## D5. A7 venv sync

`uv sync --locked --project <canonical_install_root>`, subprocess timeout
120 s, `shutil.which("uv")` pre-check. Binary-missing / timeout / non-zero
→ stderr `[event] uv_sync warn …`, exit code untouched (git-binary-WARN
precedent of #753).

## D6. A1 staleness detection (minimal wave)

Detection+report ONLY (self-update explicitly out of scope — installs move
by git pull). When the executing install carries `.git`: read HEAD + the
locally-known remote ref (`origin/<upstream-or-current-branch>`), count
`rev-list --count HEAD..origin/<branch>`; emit
`[event] name=skill_install_staleness status=warn detail=behind=N` (or
status=ok at parity, status=skip when not a clone). No network fetch.
Documented in skills/upgrade/SKILL.md.

## D7. Iron-rule surface

All writes stay outside the seven user-data dirs (agents/.claude/,
CLAUDE.md, .mcp.json, env-manifest.yaml, runs/.init-report.json exempt,
install root external). Requirements/custom-section preservation asserts
byte identity of extracted blocks in tests.

## D9. Integration findings (T6 follow-through)

- Warn-once discipline across a MULTI-entry plan: only the FIRST stamp
  gate warns; `migrate_to_0_1_4` carries a silent variant
  (`_item_template_stamp_refresh_quiet`) so a 0.1.2 origin running
  0.1.3+0.1.4 emits exactly one stale-frame WARN (#758 pin).
- Dry-run zero-telemetry rule (extends #726's zero-write pin): dry runs of
  every new item emit NO kunglao_log lines and no stderr WARNs — the
  726 byte-diff test counts runs/logs/ too.
- Fast-path print pins isolate with an empty registry: the already-current
  print / no-reload-hint contracts are driver behavior, now that patch
  entries stay permanently reachable above the release stamp.
- `_item_uv_sync` honors KUNGLAO_UPGRADE_NO_UV_SYNC=1 — the operational
  opt-out doubles as the test-hermeticity switch (offline determinism).
- Post-merge CLAUDE.md layout: `[stamp line][open marker]…[close marker]
  [user sections/relocations]` — the stamp refresh re-prepends the #536
  comment above the fresh marker pair, mirroring init's final state.

## D8. Event vocabulary additions (EMIT_ACTIONS, sorted)

`agents_refresh`, `claudemd_merge`, `env_ledger_refresh`,
`mcp_scaffold_refresh`, `skill_install_staleness`,
`toolchain_manifest_check`, `uv_sync`.
