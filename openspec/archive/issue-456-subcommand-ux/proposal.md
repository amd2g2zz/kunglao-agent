# Subcommand zero-args behavior + hint richness (#456)

## Why

#413 built the UX guard at the PARENT router only: `/kunglao-agent` with no
args prints the menu and waits. But every sub-skill is an independent slash
command in Claude Code — `/kunglao-agent:init` and `/kunglao-agent:analysis`
called bare bypass the router guard entirely, and their SKILL.md files define
no no-args branch. Agent behavior on a bare call is improv (ask? guess cwd?
forward an env_check error?), i.e. unreproducible — exactly the D2/D3 gap
issue #456 documents:

| Command | zero-args behavior today |
|---|---|
| `/kunglao-agent` (parent) | defined — menu + WAIT |
| `/kunglao-agent:init` | UNDEFINED (no no-args section) |
| `/kunglao-agent:analysis` | UNDEFINED (`grep -c "no.arg\|empty.*ARGUMENTS\|missing.*workspace"` = 0) |
| `/kunglao-agent:help` | defined (`arguments: []`) |

Two more defects from the issue evidence:

1. **Router self-contradiction**: the same SKILL.md says
   `The workspace is never a parameter: workspace detection runs in Phase 0`
   while its own menu and Routing sections say `analysis <workspace>`. The
   workspace's parameterhood depends on which paragraph you read. The same
   sentence lives in `skills/kunglao-agent/SKILL.md` (Arguments section), so
   the contradiction is duplicated, not isolated.
2. **Hint/menu thinness**: `analysis` argument-hint is bare `<workspace>`
   (no alias `analyze`, no zero-args guidance); `init` hint has no zero-args
   guidance either. The menu is 3 commands x 1 line: no per-command argument
   example, no next-step guidance (uninitialized -> init / initialized ->
   analysis / unsure -> help), no partial-args recovery entry.

Root cause: hints/menu copy live in each SKILL.md with no single data
source, so init got a hint and analysis did not, and the router drifted into
two answers for one question.

## What Changes

- **`skills/subcommands.yaml` (NEW, the single source)**: one machine-
  readable record per subcommand (init / analysis / help): invocation,
  argument-hint, zero-args action, missing-arg action, example, next-step.
  Mirrors the hook-registry single-source pattern (#372/#381: one THE
  registry, every render linted against it).
- **Zero-args + partial-args branches defined in every subcommand SKILL.md**
  (agent-layer prescribed actions, consistent with #455's "scripts never
  input()" architecture): guided prompt / menu — never a bare argparse
  error, never silently guessing cwd. `init` missing `--type` routes into
  the #455 intake/type-alignment sequence (referenced, not implemented
  here).
- **Router contradiction eliminated**: "workspace is never a parameter"
  removed from both SKILL.md copies; replaced by ONE semantics — the
  workspace is an explicit positional argument, absent -> guided prompt,
  never silent default. Phase 0 stays an environment probe of the GIVEN
  workspace.
- **Menu/hint richness**: menu gains per-command argument examples and a
  next-steps block; `analysis` hint gains the `analyze` alias and zero-args
  guidance; `init` hint gains zero-args guidance.
- **Lint tests (`tests/test_subcommand_zeroarg_ux.py`, NEW)** anchor all of
  the above mechanically (issue acceptance: every checkbox has a test).

## Capabilities

### Modified Capabilities

- `skill-arguments-intent-contract` (see openspec/changes archive): the
  argument contract gains the zero-args/partial-args dimension for every
  exposed subcommand, plus a single-source lint across router SKILL.md,
  subcommand frontmatter, and the README command table.

## Impact

- `skills/subcommands.yaml`: NEW (~40 lines).
- `SKILL.md` (root router): menu block gains examples + next steps;
  workspace semantics sentence rewritten; hint updated.
- `skills/init/SKILL.md`, `skills/analysis/SKILL.md`, `skills/help/SKILL.md`:
  zero-args + missing-arg sections added; hints updated.
- `skills/kunglao-agent/SKILL.md`: the duplicated "never a parameter"
  sentence rewritten; Phase 0 step 5 retitled from "Workspace detection" to
  workspace resolution (semantics only, no flow change).
- `README.md`: Command Reference table rows align with the single source.
- `tests/test_subcommand_zeroarg_ux.py`: NEW (document-consistency lint,
  mirrors test_skill_subcommand_ux.py helpers).
- No script changes: zero-args behavior is agent-layer guidance in SKILL.md
  plus machine-checkable document assertions (issue framing for a
  doc-layer UX contract).

- NOT in scope: #455 (init target/type alignment, intake step-0 order, the
  decision_pending persistence schema — only its CONCEPT is referenced);
  #451 (AskUserQuestion architecture); the `verify`/`resume`/CLI-passthrough
  subcommands (main-contract table) — their zero-args contract is #449+
  territory; no pushes, no PRs, no remote changes.
