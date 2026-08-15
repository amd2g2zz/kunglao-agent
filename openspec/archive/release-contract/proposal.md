# release-contract

## What

Make the checked-out revision reproduce the documented install and CLI surface from a clean clone, as a single versioned release artifact.

At this revision the README documents a release contract the repo does not own:

- Installation (README L101-L132) requires `pyproject.toml` / `uv.lock` (`uv sync`) and ships `agents/*.md` — `git ls-files pyproject.toml uv.lock 'agents/**'` = 0, all three absent.
- `uv sync --locked` fails (`No pyproject.toml found`); the default eval command fails on `ModuleNotFoundError: No module named 'yaml'` without an ad-hoc `--with pyyaml`.
- `scripts/kunglao.py` (the "unified entry point") registers only `decide` / `tick` / `health` while its docstring advertises `verify` and `record` as "next" (L12-L17, L60-L79).
- README claims 269 tests and a shipped state (L260-L322) — actual suite: 618 passed / 6 known-failing / 1 skipped at dev `105f6ff`.

## Why

A clean clone cannot run the documented installation command, cannot reproduce the test/eval baseline, and cannot reconstruct evidence about unattended operation in another environment. Agent definitions, runtime dependencies, the documented CLI surface, and claimed status are not revision-owned as a single release artifact — a reproducibility and trust gap for a tool whose core value is verifiable convergence.

## Scope

- `pyproject.toml` — minimal real manifest declaring the dependency set actually imported (`PyYAML`, `pefile`, `capstone`, `jsonschema`; `pytest` dev extra), `requires-python >=3.11`.
- `uv.lock` — generated via `uv lock`, committed; `uv sync --locked` becomes the documented install command.
- `agents/` — vendor the 10 documented agent definitions (kunglao-worker, kunglao-redteam, ghidra-light, floss-filter, pefile-signature, cti-correlator, go-symbols, shodan-host, verdict-scorer, verdict-redteam) as repo-owned assets (decision D1).
- `release-manifest.yaml` — declarative release inventory: version, dependencies, asset paths (agents/hooks/templates/openspec), CLI inventory, router subcommands, standard test command.
- `scripts/release_receipt.py` — machine-readable receipt (revision, lock digest, asset inventory with sha256, CLI inventory with `--help` exit codes, test result) runnable locally and in CI; `--check` mode = manifest validation gate.
- `scripts/kunglao.py` — register `verify` + `record` subcommands (thin delegation to `kunglao_verify.main` / `kunglao_record.main`) so the documented router surface (`decide` / `tick` / `verify` / `record` / `health`) actually exists.
- `schemas/release-receipt.json` — frozen receipt schema (repo convention: `contract_validator` fixture).
- `.github/workflows/release-check.yml` — clean-env CI: `uv sync --locked` → manifest/CLI validation → standard test command → receipt artifact. Replaces the boilerplate `python-package.yml` (which never used uv and contradicts the contract).
- README reconciliation — replace hand-maintained counts (269 tests, shipped claims) with receipt-linked statements; correct the dependency list (`cryptography` is not imported); document `uv sync --locked` and the real CLI surface.
- `tests/test_release_receipt.py` — TDD suite: manifest honesty, receipt shape, CLI inventory, README reconciliation guard, no-secrets guard.
- `.gitignore` — add `.venv/` and `release-receipt.json` (generated, not revision-owned).

## Deferred

- Syncing vendored `agents/` copies with the live `~/.claude/agents/` install (receipt records digests so drift is observable, not silently fixed).
- `kunglao.py` subcommand → pure loop-entry refactor (phase8-cli-convergence deferred item; the 8 independent CLIs remain the primary documented interface).
- Fixing the 6 pre-existing suite failures (parallel #77/#78/#82 work — receipt records them as data, CI gates on them).
- Publishing a versioned distribution (wheel/sdist) — the contract here is the repo-as-release, not a package.

## Acceptance

- Fresh clone in an empty environment runs `uv sync --locked` with no hidden local state, then `uv run python -m pytest -q` (the documented test command) and the eval self-check without ad-hoc flags.
- `release-manifest.yaml` + receipt validate: every declared asset exists, every declared CLI's `--help` exits 0, router exposes `decide` / `tick` / `verify` / `record` / `health`.
- CI (`release-check.yml`) on PR/push-to-dev produces a machine-readable receipt artifact (revision, lock digest, asset inventory, CLI inventory, test result).
- README contains no hand-maintained test counts; claims point at the receipt.
- `openspec validate release-contract` prints valid; full suite: 6 pre-existing failures unchanged, all new tests green.
