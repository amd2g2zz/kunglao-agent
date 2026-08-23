# Design — init deploy_env 四层闭环 (#478)

## D1 — L1 hooks: create-then-deploy, skip is opt-out only

The deadlock: `deploy_hooks` targets `<ws>/.claude/settings.json` ONLY if
it exists; nothing creates it. Fix in `initialize()`:

```
if deploy_env_enabled:            # default True; --no-hooks flips it
    settings = ws / ".claude" / "settings.json"
    if not settings.exists():     # L1 creation (unless --hooks-json names
        atomic_write(settings, '{"hooks": {}}')   # an operator target)
    hook_report = deploy_hooks(ws, hooks_json)    # #445 path unchanged
    rc = hook_deploy_rc(hook_report)              # mismatch -> 7
```

- `--hooks-json` keeps operator-declared semantics (creation skipped — the
  operator's file is theirs).
- Failure maps to the EXISTING `RC_HOOK_WIRING=7`; no new constant.
- The "hooks skipped — no settings.json" message becomes reachable ONLY
  via `--no-hooks` ("hooks skipped (--no-hooks)").
- `--no-mcp` stays orthogonal (scaffold skip), untouched.

## D2 — L2 subagents: sha256-guarded idempotent copy

Source: `<repo>/agents/<name>.md` (deployment source — the repo's own
tracked files; a workspace copy is a runtime artifact of the USER's
workspace, not of this repo). Target: `<ws>/.claude/agents/<name>.md`.

- CORE_AGENTS = kunglao-worker, kunglao-redteam, kunglao-init-worker
  (deployed for every type). RE specialists (ghidra-light, go-symbols,
  pefile-signature, floss-filter, verdict-scorer) stay
  orchestrator-dispatched — dispatching does not require a
  workspace-level copy, and #478's text names exactly the core 3.
- Idempotence: target sha256 == source sha256 → skip; differs → overwrite
  (update); absent → create. Rerun hash invariance is test-pinned.
- README:53's manual `cp agents/*.md ~/.claude/agents/` line is corrected
  to state init deploys workspace-level agents automatically.

## D3 — L3 MCP: probe-and-record, never execute registration

Per item applicable to `project_type` (mcp_probe.MANIFEST + the #407
decompiler rule are reused via `mcp_probe.check_mcp`), classify:

- registered (via `mcp_probe.registered_names` — the ONLY enumeration) →
  status `pass`
- unregistered → status `manual` with the item's `register` command
  recorded in env-manifest.yaml; stderr prints a per-item manual line
  (HARD items prefixed `[HARD-missing]`, WARN items `[warn]`).

Init NEVER executes `claude mcp add` (no subprocess to the claude CLI —
headless correctness first; the interactive consent flow is #451's
AskUserQuestion change). `--assume-yes` therefore changes nothing here
today: auto-registration is explicitly out of scope for this change. The
degradation is always WRITTEN (manifest) — never silent, per #474.

## D4 — L4 skills: explicit flag only

`--skills name1,name2` copies `<repo>/skills/<name>` →
`<ws>/.claude/skills/<name>/` (recursive). Unknown name → RC_ERROR (fail
fast, list available). No flag → nothing deployed, manifest records
`skills: none (opt-in)`. No interactive picker (that is #451).

## D5 — env manifest carrier

`<ws>/env-manifest.yaml` at the workspace ROOT — NOT under facts/:
compute_state_hash folds every facts/ filename into `facts-manifest:`,
so a facts/ ledger would change the digest every init run and trip the
resume drift WARNING forever. Schema (deliberately simple — #450 may
evolve):

```yaml
generated: 2026-08-19T..Z
project_type: windows
components:
  - name: hooks
    path: .claude/settings.json
    sha256: <hash of written file>
    status: deployed|skipped|manual|pass
    detail: ...
  - name: agent:kunglao-worker
    path: .claude/agents/kunglao-worker.md
    sha256: ...
    status: deployed|unchanged
  - name: mcp:ghidra
    status: pass|manual
    detail: registered (user-global) | register command
  - name: skills
    path: .claude/skills/
    status: none|deployed(a,b)
```

Rewritten atomically on every init run (idempotent). NOT part of the
state_hash digest inputs (it is a deployment ledger, not analysis state) —
verified by the resume test not flagging drift.

## D6 — plugin_mode seam (#364 future)

`deploy_env(ws, ..., plugin_mode: bool = False)`; True → skip L1 + L2
(a plugin's hooks.json declares them) but keep L3 record + manifest. One
test pins the skip. No plugin is implemented.

## D7 — rejected alternatives

- Executing `claude mcp add` under --assume-yes: the register templates
  contain `<path>` placeholders that only a human can fill (ghidra bridge
  path, IDA URL) — executing them verbatim would register broken servers
  that SHADOW working user-level ones (the exact hazard the empty
  `mcpServers:{}` scaffold exists to avoid).
- New RC_ENV_DEPLOY: deploy failure already has a precise home (7 for
  hooks; agents/skills copy failures are OSError → RC_ERROR=1, generic).
- Deploying ALL agents/: the specialists' contract is
  orchestrator-dispatch, and unfiltered copies would drift from the
  specialist-registry (#135) routing table.
