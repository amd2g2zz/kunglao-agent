# Design — subcommand zero-args UX (#456)

## Design Decisions

### D1. Zero-args behavior = agent-layer prescribed action in SKILL.md, machine-checked by document lint

The subcommands are skill invocations, not CLIs — there is no argv parser to
raise. The defect is that the SKILL.md files prescribe NO action for an
empty `$ARGUMENTS`, so the agent improvises. The fix is therefore
document-layer: every subcommand SKILL.md gains an explicit no-args section
prescribing one deterministic action, and a lint test pins its existence and
its key phrases (so the contract cannot silently rot — same document-lint
family as test_skill_subcommand_ux.py, which is #413's contract file).

Prescribed actions (all follow the #455 architecture: the SKILL layer
guides, scripts never `input()`):

| Subcommand | zero args | partial args |
|---|---|---|
| `init` | guided prompt: state that `<workspace>` is required, show the canonical invocation + `--type` choices, offer `help`; if cwd already looks initialized (`claim-register.yaml` present) say so and point to `analysis` or resumable `init` | workspace given, `--type` absent -> enter the #455 intake/type-alignment sequence (sniff -> CONFIRM, never silent default); workspace absent is the zero-args case |
| `analysis` | guided prompt: `<workspace>` required; if cwd looks initialized, propose exactly `<cwd>` and CONFIRM (one question, enumerated options); otherwise show canonical invocation + `init` pointer | `analysis` takes exactly one positional, so partial == zero |
| `help` | print the usage list (already defined; now linted) | n/a — `arguments: []` |

Guards stated in every subcommand file: no bare-argparse-style error dump,
never guess, never silently default to cwd. A guided prompt that CONFIRMS a
cwd-derived candidate is allowed; silently RUNNING on it is not (the #413
"menu, WAIT, never guess" rule extended below the router).

### D2. `init` missing `--type` routes to #455's sequence — concept-aligned, not implemented here

The #455 issue owns intake step 0 (target/type alignment: sniff is a
suggestion, confirmation is mandatory, ambiguity is surfaced, decisions are
recorded). #456 defines only the ROUTING: when `init` receives a workspace
without `--type`, the SKILL.md says "do not default silently; run the #455
intake type-alignment step". Concept alignment: if that interaction yields
an unresolved decision that must persist (e.g. type ambiguous across a
multi-file `bins/`), the placeholder for it is #455's `decision_pending`
schema entry — referenced by name in the subcommand SKILL.md as the
hand-off point. This change adds no persistence, no schema file, no intake
ordering: those are #455's deliverables.

### D3. Workspace semantics unified to EXPLICIT positional argument

Two copies of the contradiction exist today: root `SKILL.md` ("The workspace
is never a parameter: workspace detection runs in Phase 0") next to a menu
that says `analysis <workspace>`, and the same sentence in
`skills/kunglao-agent/SKILL.md` (Arguments + Phase 0 step 5 "Workspace
detection ... detect it here from the local defaults").

Decision: the menu/hints/README/frontmatter (`arguments: [workspace]`)
position wins — the workspace IS an explicit positional argument. Reasons:
(a) three of the four surfaces already say so (frontmatter, hints, README);
(b) #413's guided-entry direction is richer hints, not hidden state;
(c) "detect from local defaults" is a cold-start recovery path, not an
interface contract — modeling it as the primary contract is what created
two answers.

Concretely:
- The sentence "The workspace is never a parameter..." is deleted from BOTH
  files and replaced by one anchor sentence: the workspace is an explicit
  positional argument; when absent the subcommand runs a guided prompt and
  never silently defaults (link to its zero-args section).
- Main-contract Phase 0 step 5 is retitled "Workspace resolution + path
  reachability": confirm the GIVEN workspace (explicit arg or confirmed
  cwd candidate), resolve state files cwd-relative — the path-reachability
  mechanics are untouched.
- A lint test asserts: (1) the phrase "never a parameter" appears in NO
  SKILL.md; (2) the anchor sentence appears in BOTH the root router and the
  main contract (identical semantics, one answer).

### D4. Menu/hint single data source: `skills/subcommands.yaml` + render lint (no generator)

`skills/subcommands.yaml` is THE registry (the #372/#381 hook-registry
pattern applied to UX text): one record per subcommand with fields
`invocation`, `argument-hint`, `zero-args`, `missing-args`, `example`,
`next-step`. The three render surfaces are linted against it:

1. root `SKILL.md` menu: every registry invocation line present; menu block
   carries a next-steps entry per command and the shared next-step guidance
   (uninitialized -> `init`, initialized -> `analysis`, unsure -> `help`);
2. each `skills/<cmd>/SKILL.md` frontmatter `argument-hint` equals the
   registry hint exactly;
3. `README.md` Command Reference table: one row per registry command, args
   cell consistent with the registry invocation.

Why lint and not a generator: SKILL.md files are handwritten contracts; a
generator would either own the whole file (unacceptable — they carry far
more than the menu) or template a marked block (a second rendering engine
for 4 files, KISS/YAGNI). The registry + lint gives the property that
matters — a drift in any surface fails a test — without a build step.

### D5. Hint enrichment exactly as the issue lists

- `analysis`: `<workspace> (alias analyze) — no args: guided workspace prompt`
  — covers the undocumented alias, the missing-workspace guidance, and the
  zero-args entry point.
- `init`: `<workspace> [--type windows|linux|android] — no args: guided setup`
  — existing choices preserved, zero-args guidance added.
- `help`: unchanged (`[no args] — print the subcommand usage list`).
- Root router hint: unchanged shape (`init <workspace> | analysis <workspace> | help`)
  — it already lists every subcommand.

Menu block gains, per command: argument example line (registry `example`)
and a one-line next-step; plus a shared "Next steps" footer mapping operator
state to command. Unknown subcommand handling (menu + `unknown: <x>`) is
already #413-defined and stays.

## Rejected Alternatives

- **R1: make the router intercept subcommand calls**: impossible — Claude
  Code exposes each sub-skill as an independent command; the router cannot
  see a bare `/kunglao-agent:analysis` invocation. The guard must live in
  each subcommand file.
- **R2: implement zero-args in `kunglao-init.py` / CLIs**: wrong layer and
  #455 territory (its evidence 4 is exactly the bare `input()` non-
  interactive failure); the UX contract here is the SKILL layer.
- **R3: workspace as hidden Phase-0 detection (keep the "never a
  parameter" sentence, change the menu instead)**: would rewrite three
  surfaces (frontmatter/hints/README) to remove an argument that operators
  demonstrably type; also breaks #455's own intake flow which needs an
  explicit workspace. Rejected — D3.
- **R4: generator script rendering SKILL.md blocks from the YAML**: second
  rendering engine, build step, merge hazards with handwritten contract
  prose. Lint-only (D4) achieves drift detection without generation.
- **R5: extend `verify`/`resume`/CLI-passthrough zero-args in this change**:
  scope creep; those are main-contract-table commands, #449+ territory.
  Only init/analysis/help (the skills/ exposed surface) are in #456.

## File layout

| File | Action | Purpose |
|---|---|---|
| `skills/subcommands.yaml` | NEW | THE single source: invocation / hint / zero-args / missing-args / example / next-step per subcommand |
| `SKILL.md` | EDIT | menu examples + next steps; D3 sentence swap; hint unchanged |
| `skills/init/SKILL.md` | EDIT | no-args + missing-type sections; hint per D5 |
| `skills/analysis/SKILL.md` | EDIT | no-args/missing-workspace section; hint per D5 |
| `skills/help/SKILL.md` | EDIT | no-args statement pinned (minimal) |
| `skills/kunglao-agent/SKILL.md` | EDIT | D3 sentence swap (Arguments + Phase 0 step 5 retitle) — semantics only |
| `README.md` | EDIT | Command Reference rows align to the registry |
| `tests/test_subcommand_zeroarg_ux.py` | NEW | RED-first document lint: registry completeness, render consistency, zero-args/partial-args definitions, contradiction removal |

## Out of scope

- #455: intake ordering, sniff semantics, `decision_pending` persistence
  (D2 references the concept only).
- #451: AskUserQuestion architecture.
- Any script/CLI behavior change; any push/PR/remote mutation.
