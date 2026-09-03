# init deploy_env 四层闭环 — hooks 死锁解除 + agents 部署 + MCP 注册流 + skills opt-in (#478)

## Why

Issue #478 evidence (sandbox reproduce, baseline dev 8e85dfa): a standard
init (`kunglao-init.py <ws> --type windows --skip-toolchain`) exits 0 with
the full scaffold — but prints `hooks skipped — no
<workspace>/.claude/settings.json (HOME settings never written)` and no
`.claude/` directory is ever created. Three gaps:

1. **hooks deployment deadlock (heaviest)**: `deploy_hooks` targets
   `<ws>/.claude/settings.json` only when it already exists; the scaffold
   (`SCAFFOLD_DIRS = facts/blockers/runs`) never creates `.claude/`.
   Deployment requires the file to exist → nobody creates it → the normal
   flow ALWAYS skips → worker_budget / dispatch_gate / env_check_gate never
   fire for that workspace. The irony: #445 just defined
   `RC_HOOK_WIRING=7` ("a failed deployment self-check must FAIL") — but an
   ABSENT deployment is silently RC 0.
2. **subagents zero deployment**: init never references `agents/`;
   README:53 asks the user to hand-copy `cp agents/*.md ~/.claude/agents/`;
   nobody writes a workspace-level `.claude/agents/`.
3. **.mcp.json empty scaffold**: mcp_probe.py:242 intentionally writes an
   empty `mcpServers:{}` (correct intent), but the first user must hand-run
   N `claude mcp add` commands whose templates sit in the manifest.

## What Changes

A unified **deploy_env** layer in `scripts/kunglao-init.py`, run inside
`initialize()` after the toolchain gate and before the pending-decision
branch, with a uniform contract per component: 落位 +
probe 验证 + 登记 env manifest + 降级明示.

- **L1 hooks (default ON, non-interactive)**: create
  `<ws>/.claude/settings.json` (minimal `{"hooks": {}}`) when absent, then
  deploy via the EXISTING `deploy_hooks` path (canonical construction +
  self-check from #445, reused — not copied). The silent skip branch is
  REMOVED: absence is no longer a legal default. `--no-hooks` is the only
  explicit opt-out; failure maps to the existing `RC_HOOK_WIRING=7`.
- **L2 subagents (default ON, type-filtered, idempotent)**: deploy the
  core 3 agents (`kunglao-worker`, `kunglao-redteam`,
  `kunglao-init-worker`) to `<ws>/.claude/agents/` for every type, plus
  `gitnexus`-related flow only via the android manifest item (no extra
  agent file today — the repo carries exactly the three core agents plus
  RE specialists; specialists stay orchestrator-dispatched, not
  workspace-deployed). Same sha256 → skip; different → update.
- **L3 MCP registration (three-way, non-TTY-safe)**: per manifest item
  applicable to the type, enumerate registered names via the SINGLE
  existing implementation `mcp_probe.registered_names` (three sources);
  registered → PASS; unregistered → register command is recorded in the
  env manifest as the manual step. Auto-registration (executing `claude
  mcp add`) is deliberately NOT executed by init: `claude` CLI execution is
  interactive-user territory (#451 owns the AskUserQuestion flow). The
  non-interactive default therefore records the degradation explicitly
  (HARD missing → WARN-level manifest entry + stderr line), never silently
  passes.
- **L4 auxiliary skills (pure opt-in, one flag)**: `--skills a,b` deploys
  `<skill_repo>/skills/<name>` directories to `<ws>/.claude/skills/`;
  no flag → nothing installed. The interactive picker belongs to #451.
- **登记 env manifest**: every deployment lands in
  `<ws>/env-manifest.yaml` (component name + path + sha256 +
  timestamp + status). #475 drift detection will diff against this file;
  the schema is intentionally simple (a #450 carrier may evolve it).
- **plugin_mode seam**: `deploy_env(..., plugin_mode=False)` — when True,
  L1/L2 are skipped (a future #364 plugin's hooks.json declares them).
  Locked by test; NOT implemented beyond the seam.

## RC contract

No new RC constant. L1 failure reuses `RC_HOOK_WIRING=7` (its semantic:
hook deployment failed). L3 degradation is WARN (informational), not a
FAIL RC — init still exits 0 with an explicitly recorded degradation
(#474 semantics: registered ≠ usable, WARN never silent).

## Impact

- affected: `scripts/kunglao-init.py` (deploy_env + flags), 
  `tests/test_init_deploy_env.py` (new), `README.md` (manual cp path
  correction), `specs/phase-3.5/contract.md` (hooks line contract —
  "skipped" only via --no-hooks), `skills/init/SKILL.md` (flag docs)
- reused untouched: `scripts/hook_activation.py` (register/selfcheck),
  `scripts/mcp_probe.py` (registered_names/manifest), `agents/*.md`
  (deployment source), `scripts/wire_up_settings.py` (registry)
- NOT touched: toolchain probes (chain B #474 owns them); no plugin form
