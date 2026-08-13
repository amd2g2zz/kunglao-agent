# CLI script spec checklist (issue #277)

> Script-discipline contract: any reusable tool logic lives as a parameterized
> CLI script in `<SKILL_DIR>/scripts/` (or `scripts/re/` for worker tools) —
> never as `python -c "..."` / heredoc `<<'EOF'` inline execution. A new script
> is acceptable only if it satisfies every line below. Canonical exemplar:
> `scripts/shell_defaults.py` (idempotent shell env-default management —
> `--var/--value/--profile/--shell`, check/apply/remove, exit codes, `--json`).

## 1. Parameterized, never hardcoded

- All targets come from CLI args, not string literals: `--binary PATH`,
  `--rva`, `--var`, `--value`, `--profile`, `--shell`, `--port`, ...
- No sample path, VM IP, workspace path, or hook address embedded in the body.
- Use `argparse` (self-describing): `--help` must render without reading source.

## 2. Input injectable / mockable

- Inputs (paths, env names, values, file handles) are passed in, so tests can
  drive the script with a tmp workspace / temp files / synthetic data.
- No implicit dependency on `cwd` or ambient environment unless documented;
  read workspace state from the argument, not from `os.getcwd()`.

## 3. Idempotent

- Re-running the same invocation converges to the same final state.
- apply = no-op when the target state already exists (`unchanged`), rewrite when
  it differs, append when absent — never duplicate, never error on no-op.
- remove = no-op when the target is already absent.

## 4. Three-state semantics (check / apply / remove or equivalent)

- A mutating CLI exposes at least `check` (read-only probe), `apply` (make
  state), and `remove` (unmake state) subcommands — or an equivalent dry-run /
  commit split.
- `check` never writes; `apply`/`remove` report what they did.

## 5. Exit codes distinguish state

- `0` = OK / desired state; distinct non-zero codes for each distinct outcome
  (e.g. `1` = truthy/tainted, `2` = absent, `3` = error).
- Callers (hooks, kunglao.py) branch on exit codes, not on stderr text.

## 6. Output: explicit text or JSON

- Human-readable default (one line per result) plus a `--json` flag emitting a
  single JSON object with stable keys (no trailing junk on stdout).
- No stray `print()` debugging; structured results only.

## 7. Errors carry guidance

- Every error message says what went wrong AND what to do next (the exact
  command to run, the file to fix, the env var to set).
- Never fail silently; never print a bare traceback to the caller as the
  primary message.

## 8. Reusability bar

- Reusable iff: (a) takes the sample/input as an argument, (b) the only
  sample-specific constant is the input, (c) the output schema is fixed.
- Sample-specific one-shots go in `scripts/sample_specific/`, never `scripts/`.
- Naming: `<verb>_<object>.py` — no fact-ID / claim-ID prefixes
  (`f046_*.py` is forbidden).
