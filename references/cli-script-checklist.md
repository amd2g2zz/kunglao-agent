# CLI script spec checklist (issue #277)

> Script-discipline contract: any reusable tool logic lives as a parameterized
> CLI script — worker-facing analysis tools in `<SKILL_DIR>/tools/<category>/`
> (registered in `tools/_INDEX.yaml`, see §0), skill infrastructure CLIs in
> `<SKILL_DIR>/scripts/` — never as `python -c "..."` / heredoc `<<'EOF'`
> inline execution. A new script
> is acceptable only if it satisfies every line below. Canonical exemplar:
> `scripts/shell_defaults.py` (idempotent shell env-default management —
> `--var/--value/--profile/--shell`, check/apply/remove, exit codes, `--json`).

## 0. 先查目录 — check the catalog first (issue #294)

Before writing any new script, check in this order:

1. `tools/_INDEX.md` — the 6-category capability-domain table; find the task's domain (crypto/static/ghidra/dynamic/pipeline/aux)
2. `tools/_index-<category>.md` — the domain's one-line contract skeletons; see whether an existing tool already covers the same capability
3. `tools/_INDEX.yaml` — the machine contract; confirm tool name/subcommands/input-output

Matching tool found → **prefer solving it with that tool's CLI** (see each tool's `--help` / `input_output` contract); do not write a new script. Only when nothing matches do you proceed to items 1-8 below to write one. The `toolfirst` gate in `hooks/worker_budget.py` checks that every dispatch carries a `tool-catalog: <name>` or `tool-catalog: none (reasoning: <why not>)` marker — hitting a registered tool's capability keywords without the marker gets REJECTed.

**Hard encoding / naming conventions (issues #317, #314 A1-A3 — missing any one is caught by a mechanical test):**

4. **UTF-8 stdout is mandatory**: every new CLI (a .py with `if __name__ == "__main__":`) must, right after `import sys`, run `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`, wrapped in `try/except (AttributeError, ValueError): pass`. Reason: when the output contains U+FFFD (a decode errors="replace" artifact) or any non-ASCII, a GBK console cannot encode it → a bare UnicodeEncodeError traceback + exit 1, breaking the "structured error, never a traceback" contract (hit independently by three batches: 1b/1c/2b). Standardize on UTF-8; this is not an errors="replace" patch. Mechanical enforcement: `tests/test_utf8_stdout_convention.py` scans every CLI under tools/; a missing call turns red.
5. **Test helper decoding is mandatory**: a test helper's `subprocess.run` must carry `encoding="utf-8", errors="replace"` (do not use bare `text=True` — it decodes by locale/GBK by default; once tools are uniformly UTF-8, GBK decoding of multi-byte characters → reader-thread UnicodeDecodeError, stdout=None; hit by 1c).
6. **Directory naming avoids Windows reserved device names**: the tool directory must be `tools/auxiliary/`, not `tools/aux/` (AUX is a Windows reserved device name; git cannot track that path; #307 just hit this, and a rename precedent exists). Mechanical enforcement: `tests/test_windows_reserved_names.py` scans every path component in the repo (CON/PRN/AUX/NUL/COM1-9/LPT1-9).

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
