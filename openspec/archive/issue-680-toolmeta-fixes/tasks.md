## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-680-toolmeta-fixes` branch `issue-680-toolmeta-fixes` off origin/dev (b2b3661 — #685 merged; PR #685 file list does NOT touch scripts/toolchain.py, no FIXES conflict)
- [x] 1.2 Baseline recon: FIXES = 23 static entries + 7 mcp:* derived; string consumers = toolchain.py (3), toolchain_install.py, kunglao-init.py, toolchain_negotiation.py (2), deploy_shim.py (2)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D1-D8)
- [x] 2.3 specs/toolmeta-fixes/spec.md
- [x] 2.4 tasks.md

## 3. RED tests (`tests/test_toolchain_metadata.py`)

- [ ] 3.1 RED1: schema shape — ToolMeta fields, FIXES values typed, fix non-empty
- [ ] 3.2 RED2: all 23 static entries have url + description
- [ ] 3.3 RED3: install-able tools (INSTALL_PLANS kind=auto ∩ FIXES) carry verify_cmd
- [ ] 3.4 RED4: url-unknown fallback — no crash, degraded output (no url line)
- [ ] 3.5 RED5: backward compat — str(FIXES[name]) == legacy guidance == fix_text(name)
- [ ] 3.6 RED run output captured verbatim

## 4. Implementation (GREEN)

- [ ] 4.1 scripts/toolchain.py: ToolMeta dataclass + fix_text() accessor
- [ ] 4.2 scripts/toolchain.py: FIXES → dict[str, ToolMeta], 23 entries with url/description (+repo/package/verify_cmd where applicable)
- [ ] 4.3 scripts/toolchain.py: mcp:* derivation wraps register text into ToolMeta(url=None)
- [ ] 4.4 scripts/toolchain.py: next_action_for mcp branch reads meta.fix
- [ ] 4.5 scripts/toolchain.py: format_human url:/verify: own lines; format_json additive fix_url
- [ ] 4.6 scripts/kunglao-init.py: refuse_toolchain fix_text + url line
- [ ] 4.7 scripts/toolchain_negotiation.py + scripts/deploy_shim.py: fix_text fallbacks
- [ ] 4.8 scripts/toolchain_install.py: structured guidance (url:/verify: lines; verify after install)
- [ ] 4.9 Target tests 5/5 GREEN; toolchain suites no regression

## 5. Gate + PR

- [ ] 5.1 `uv run python devkit/quality_gates.py` (7 gates; Gate 2 per baseline ledger — no new out-of-ledger failures)
- [ ] 5.2 3-commit sequence: openspec / RED / GREEN (no WIP fragments)
- [ ] 5.3 push + PR to dev (Closes #680), body carries RED+GREEN outputs
- [ ] 5.4 Report: PR number, RED sha, entry count, gate summary
