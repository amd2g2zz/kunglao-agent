# issue-207-venv-probe-stale-cryptography — lock-faithful venv probe

## Why

`scripts/env_check.py::check_venv_sample` still probes
`import cryptography, yaml`. `venv_sample` is a blocking Phase 0 row, so a
clean `uv sync --locked` install FAILs analysis entry even though
`cryptography` was dropped from `pyproject.toml` and is not imported
anywhere. Operator-facing copies of the leftover (`CLAUDE.md.base.tmpl`,
`skills/kunglao-agent/SKILL.md`) tell agents to install and verify a
package the lock no longer ships.

## What Changes

1. Probe the skill-root venv with `import yaml` (PyYAML is the declared,
   actually-imported runtime dep). A lock-faithful interpreter with yaml
   present and cryptography absent PASSes.
2. Align the workspace handbook venv line and the skill Phase 0 venv
   probe with the same declared set. Regen the three claudemd-golden
   fixtures through the existing sentinel path.
3. Refresh deploy-manifest digests for the touched deployed sources.

## Impact

- Producer: `check_venv_sample` → `runs/.env-check.json` `venv_sample` row.
- Consumer: `hooks/env_check_gate.py` / Phase 0 refuse analysis entry on
  a blocking FAIL.
- No probe of guarded extras (`z3-solver`, `jinja2`). No behavior change
  for a missing venv interpreter or a missing yaml install.

## Acceptance

- Lock-faithful venv (yaml present, cryptography absent) → `venv_sample` PASS.
- Source pin: `env_check.py` no longer contains `import cryptography`.
- Goldens byte-identical to the sentinel render after the handbook line change.
