# Tasks — feat-478-deploy-env

## 1. SDD
- [x] 1.1 proposal.md
- [x] 1.2 design.md
- [x] 1.3 tasks.md
- [x] 1.4 specs/deploy-env/spec.md

## 2. RED (tests/test_init_deploy_env.py)
- [x] 2.1 no-flag init -> <ws>/.claude/settings.json EXISTS with registry
      hooks (RED: file never created; witness 2026-08-19 /tmp sandbox:
      "hooks skipped — no <workspace>/.claude/settings.json", RC 0)
- [x] 2.2 --no-hooks -> skip legal, message names the flag
- [x] 2.3 core 3 agents land in <ws>/.claude/agents/
- [x] 2.4 idempotent rerun: agent hashes unchanged
- [x] 2.5 plugin_mode=True skips L1+L2 (seam test)
- [x] 2.6 non-interactive MCP unregistered -> manifest records manual, no crash, RC 0
- [x] 2.7 --skills flag deploys; no flag installs nothing; bad name -> RC_ERROR
- [x] 2.8 env-manifest.yaml written with component ledger
- [x] 2.9 RED run output recorded (2026-08-19: 12 failed / 3 passed —
      12 = the 12 gap behaviors; witness /tmp sandbox RC=0 + 'hooks skipped
      — no <workspace>/.claude/settings.json' + no .claude/ dir)

## 3. GREEN
- [x] 3.1 deploy_env() + L1 create-then-deploy wired into initialize()
- [x] 3.2 L2 agents deploy (sha256 idempotent)
- [x] 3.3 L3 mcp probe+record (mcp_probe reuse)
- [x] 3.4 L4 --skills flag
- [x] 3.5 env-manifest.yaml writer
- [x] 3.6 --no-hooks / --skills argparse
- [x] 3.7 quick gate green: init/hook/mcp/exit-code suites

## 4. Docs + consistency
- [x] 4.1 README:53 manual cp line corrected
- [x] 4.2 specs/phase-3.5/contract.md hooks line: skip only via --no-hooks
- [x] 4.3 skills/init/SKILL.md flag surface
- [x] 4.4 full suite `-m "not load_sensitive"` + release_receipt --check
