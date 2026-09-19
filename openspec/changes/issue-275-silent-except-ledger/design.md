# design — issue-275-silent-except-ledger

## Verified anchors (2026-09-19, worktree @ 658468d)

| Question | Actual | Drift |
|---|---|---|
| Issue says ~170 exact `except: pass` sites | Crude grep proxy reproduces at 201; calibrated AST rule seeds 199 across 83 files | near (within ~15%; per-file tops match) |
| Issue names convergence_check.py worst (10) | Calibrated count: convergence_check.py = 10 | none |
| comment_hygiene_lint scans scripts/+tests/ | SCAN_ROOTS = ("scripts", "tests"), AST + tokenize over .py | none — mirrored |

## The detector rule (exact)

An `ast.ExceptHandler` (under `ast.Try` or `ast.TryStar`) is a
SILENT SWALLOW iff every statement in its body is a no-op shape:

- `ast.Pass`
- `ast.Expr` whose value is `ast.Constant` (`...`, a bare string)

with the belt-and-suspenders audit face: the body walk must find no
`ast.Raise` and no `ast.Call` with a terminal callee identifier in
TRACE_TERMINALS (emit/log/warn/print family). A no-op body admits
neither, by construction.

### Decisions taken during calibration (each tested)

1. **Comments do NOT exempt a handler.** Tested both variants against
   the real tree: comment-exemption collapses the inventory 220 -> 97
   (probe tolerance: bare-call expressions in handler bodies were the
   difference at the 220 end; strict Constant-only no-op bodies give
   199) and inverts the issue's worst-file table — convergence_check.py
   drops 10 -> 2, and the issue names convergence_check.py the worst
   file precisely for its annotated pass sites. A comment records
   intent; it is not a runtime trace. The documented-contract exemption
   is reserved for owner-blessed cases; per the issue, none exist.
2. **Bare call expressions are NOT no-ops.** `self._cache.clear()` in
   a handler body is an observable action, not silence — the strict
   Constant-only Expr shape (199) is the honest rule; the looser
   any-Expr rule (220) counted observable no-op-free calls as silence.
   The final rule requires the Expr value to be a Constant.
3. **Shape-set boundary**: `continue`/`break`/`x = None`/`return []`
    bodies are out of scope — they are real statements with real
    control effects, not silence-shaped. Including them jumps the
    count 199 -> 332+ and leaves the issue's quantified surface.
4. **Scan roots = scripts/ + hooks/** — the issue's sweep surface.
   tests/ is not scanned; test fixtures legitimately stage silent
   handlers as string payloads (inert for AST).

## Ledger mechanics (house pattern)

Mirrors `scripts/hygiene_baseline.yaml` + `comment_hygiene_lint.py`
exactly: schema
`silent-except-baseline/1`; per-file counts; only-shrinks ratchet with
the four violation kinds (increase / cleared-entry / loose-entry /
stale-entry / unbaselined / no-baseline); `--emit-baseline` writes only
debt files, sorted, deterministic; emit refuses on structural errors
(syntax/unreadable, fail-closed); `--json` payload
`{violations, exit, summary}`; exit 1 on any violation.

## CI / deploy surface (smallest-surface ruling)

- One step appended to the `lint-hygiene` job
  (.github/workflows/release-check.yml) after the comment-hygiene
  step. No new CI leg, no quality-gates registry entry (a new gate
  number ripples into every numeric gate-count claim that Gate 7
  doc-sync polices).
- `scripts/silent_except_lint.py` rides the auto-included
  `scripts/*.py` scaffold deploy set (manifest regenerated: 399
  entries, verified); the ledger YAML stays repo-side, exactly like
  `hygiene_baseline.yaml` is not deployed.
- ext-scan auto-registered the script in tools/_INDEX.ext.yaml from
  the docstring first line.
- scripts/README.md catalog row added (test_declaration_scan
  enforces every scripts/*.py is cataloged).
