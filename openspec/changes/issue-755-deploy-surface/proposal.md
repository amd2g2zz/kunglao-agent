# Proposal: issue-755 — upgrade 部署面补齐 (A1-A7) + issue-758 G2/G3 尾巴

## Why

Wave 1 (#752/#753/#756/#758-G1G4) built the upgrade safety skeleton but the
v0.1.2→current migration registry still leaves the workspace DEPLOY SURFACE
behind:

- `.claude/agents/*.md` copied at init is never re-synced when CORE_AGENTS
  move forward (A2).
- CLAUDE.md has no framework-boundary markers (G2), so upgrade cannot
  collect-and-merge template refreshes without clobbering user edits (G3),
  and #758's G4 stamp gate stays stuck refusing to re-stamp honest-old
  workspaces forever.
- Missing deploy artifacts (`.mcp.json`, `env-manifest.yaml`) are never
  backfilled by upgrade (A4/A5); no toolchain-manifest face exists (A6).
- The install venv (`uv sync --locked`) is never refreshed by upgrade (A7).
- The canonical skill install itself can silently trail origin (A1) with
  zero detection surface.

## What Changes

upgrade gains a NEW migration entry **0.1.4** (T6 ruling: see design.md)
whose items are all idempotent + warn-only:

| item | task | behavior |
|------|------|----------|
| `_item_agents_refresh` | A2/T1 | md5-compare ws `.claude/agents/` vs executing-install `agents/` for CORE_AGENTS; mismatch → re-copy (init `_deploy_agents` semantics); report via env-manifest component row + event |
| `_item_claudemd_merge` | G3+T2/A3 | three-segment collect-and-merge (frame markers G2; legacy heading-walk fallback; requirement block + user sections byte-preserved) |
| `_item_mcp_refresh` | A4/T3 | missing `.mcp.json` → init-parity scaffold rebuild; existing → report-only |
| `_item_env_manifest_refresh` | A5/T3 | missing `env-manifest.yaml` (#478 ledger shape) → backfill per #727 channel resolution; existing → version-field refresh |
| `_item_toolchain_manifest` | A6/T3 | code-reality toolchain manifest face (see design ruling) |
| `_item_uv_sync` | A7/T4 | `uv sync --locked --project <executing install>`; WARN-only |
| `_item_skill_staleness_check` | A1/T5 | detect+report executing-install git staleness; stderr event |

Init side: `write_claudemd` wraps every render in frame markers
(`<!-- kunglao:frame:v<version> -->` … `<!-- /kunglao:frame -->`);
the three claudemd goldens are regenerated (SOP guard scan).

## Capabilities

### Modified
- upgrade deployment completeness: workspaces upgraded by
  `/kunglao-agent:upgrade` end up with CURRENT agents, a marked+current
  CLAUDE.md frame, and the full artifact set init would have produced.
- CLAUDE.md lifecycle: frame/versioned section marking; upgrade merge never
  deletes needful (task_spec constraints) or custom (out-of-frame) bytes.

## Impact

- scripts/kunglao_upgrade.py, scripts/kunglao-init.py, new
  scripts/claudemd_frame.py, tests/fixtures/claudemd-golden/*,
  skills/upgrade/SKILL.md, tests/{test_deploy_surface_755,test_claudemd_g2g3_758}.py
- Closes #755 and closes #758 (G2/G3 tail).
