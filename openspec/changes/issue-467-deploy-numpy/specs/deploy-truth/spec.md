# deploy-truth delta — issue-467-deploy-numpy

## ADDED Requirements

### Requirement: Manifest-vs-imports consistency gate (package self-check, CI-enforced)

The system SHALL compute the hard import surface of a package's deployed
Python surface (hooks/, scripts/ including package subdirectories such as
scripts/rlvr/, tools/) — hard meaning third-party imports that are NOT
guarded by a `try/except ImportError`-class handler (degrade-by-design
imports are exempt) and NOT stdlib or in-tree modules — and SHALL fail
(Non-zero exit in CI) when any hard import's distribution is absent from
that package's `pyproject.toml` `[project].dependencies`. Import names
SHALL be normalized to distribution names (PEP 503 plus an explicit alias
table, e.g. `yaml` -> `PyYAML`, `z3` -> `z3-solver`).

#### Scenario: numpy hard import with numpy-less manifest fails

- **WHEN** a package's scanned surface contains an unguarded module-level
  `import numpy` and its pyproject declares no numpy distribution
- **THEN** the gate reports missing numpy with the needing files and
  exits non-zero

#### Scenario: the repository's own package passes

- **WHEN** the gate runs over the repository tree with the repository
  pyproject as manifest
- **THEN** every hard import is covered (numpy, PyYAML via yaml, pefile,
  capstone) and the gate exits zero

#### Scenario: guarded imports are exempt

- **WHEN** a module imports an undeclared third-party distribution
  inside `try/except ImportError` (the degrade-by-design idiom)
- **THEN** the gate does not fail; the module appears only in the
  informational guarded-undeclared listing

#### Scenario: import-name to distribution-name mapping

- **WHEN** the surface imports `yaml` (or `z3`) and the manifest declares
  `PyYAML>=6.0` (or `z3-solver>=4.12`)
- **THEN** the gate treats the import as covered

### Requirement: Deploy-time env-coverage refusal

The system SHALL refuse a workspace deployment whose env project root
does not cover the deployed code's hard imports. When a workspace
deployment is materialized (init's deploy face), the
system SHALL verify that the framework env project root — the same
root the hook commands resolve as their `uv run --project` target —
declares every hard import of the tree being deployed, and SHALL refuse
the deployment (fail-loud, non-zero init exit, no partial workspace
writes) when a hard import is uncovered. The refusal SHALL name the
missing modules, the env project root, and the remediation (update the
skill package).

#### Scenario: #467 mixed-drift refusal

- **WHEN** init runs from a tree whose surface imports numpy at module
  level while the resolved framework env root's pyproject lacks numpy
- **THEN** deploy_workspace_copy raises before copying any file, no
  deployment carrier is written, and the error names numpy, the env
  root, and the update-the-skill-package remediation

#### Scenario: consistent roots deploy unchanged

- **WHEN** the env root's manifest covers the surface (env root equals
  the executing tree, or a same-generation install)
- **THEN** the deployment proceeds and its return shape is unchanged

#### Scenario: unresolvable env root fails open

- **WHEN** no framework project root can be resolved
- **THEN** the gate emits one canonical warn and the deployment proceeds
  (mirroring the hook-entry resolution fallback posture)

### Requirement: Upgrade refresh surfaces the gap without raising

The upgrade-side framework-copy refresh SHALL run the same gate and, on
an uncovered hard import, SHALL record the gap as a warn (canonical
kunglao_log warn face, day-log observable) and in its returned detail —
and SHALL NOT raise into the migration (the never-raise migration
contract stands; the broken-env evidence rides the warn channel).

#### Scenario: stale env root on upgrade refresh

- **WHEN** deployed_refresh deploys a surface whose hard imports exceed
  the env root's declared dependencies
- **THEN** the refresh completes, the returned detail carries the
  dep gap, and a warn names the missing modules and the env root
