# Acceptance — supply gate + camoufox face ruling (#767)

One-page acceptance for the #767 supply-gate PR. Ruling executed:
**re-point** the `camoufox-reverse` MCP face to a pinned installable
source. Evidence: origin = public repo
`https://github.com/WhiteNightShadow/camoufox-reverse-mcp` (MIT, tags
through v1.8.0; proven by the local clone
`~/projects/camoufox-reverse-mcp` at v1.1.1 and the editable install in
`~/pentests/OneForAll/.venv`). The distribution is on no public index
(PyPI 404). Vendoring rejected: the dep closure (mcp,
camoufox[geoip] + browser download, playwright, esprima) cannot ride
in-tree, so "self-contained" would be illusory.

## What to accept

1. The declared face resolves: `.claude-plugin/plugin.json` mcpServers
   runs `uv run --no-project --with git+https://github.com/WhiteNightShadow/camoufox-reverse-mcp.git@v1.1.1 python -m camoufox_reverse_mcp`.
2. The gate is RED on the old vapor face, GREEN post-ruling.
3. Every remediation string names the pinned source (no vapor
   `uv pip install camoufox-reverse-mcp` — that distribution does not
   exist).
4. CI runs the gate as one step in the lightest job.

## Commands

```bash
# gate green on this repo (exit 0)
uv run python devkit/supply_gate.py
# RED demo: fixture with the old face (`python -m camoufox_reverse_mcp`)
# → exit 1, "[VAPOR] plugin-mcp/camoufox-reverse … no pinned installable source"
uv run pytest tests/test_supply_gate.py tests/test_mcp_scope_408.py \
  tests/test_uv_mandate_766.py tests/test_upgrade_016_sweep.py \
  tests/test_web_labs_type_728.py tests/test_mcp_supply.py -q -n 4
uv run python devkit/quality_gates.py --quick
uv run python tools/ext-scan.py --check   # ext index stays fresh (devkit/ not scanned)
uv run python scripts/deploy_manifest.py --verify
```

## Where it plugs in (file:line) + before→after chain

| Plug point | Where | Before → After |
|---|---|---|
| Declared face | `.claude-plugin/plugin.json:11-20` | `python -m camoufox_reverse_mcp` (vapor: no index, not in tree) → `uv run --no-project --with git+…@v1.1.1 python -m camoufox_reverse_mcp` |
| Env-table row | `scripts/mcp_probe.py:172-185` (MANIFEST camoufox row) | remediation named a nonexistent PyPI dist → names the pinned git source |
| Init guidance (4 sites) | `scripts/kunglao-init.py:1750-1751, 1771, 1866-1868, 2167` | same vapor text → pinned source + uv verify line |
| README MCP rows | `README.md:528`, `README.zh-CN.md:468` | same → pinned source |
| CI face | `.github/workflows/plugin-scan.yml:19-26` | (none) → one step: `uv run --no-project python devkit/supply_gate.py` |
| The gate | `devkit/supply_gate.py` (`resolve_face` :100, `_check_agents` :159, `_check_env_table` :179, `violations` :211) | — |

Chain: plugin declares face → mcp_probe carriage/PASS stays name-keyed
(unchanged behavior) → supply_gate re-reads the SAME plugin.json and
requires each face to resolve → CI enforces on every PR/push.

## Boundary schemas

- Gate verdict document (`--json`):
  `{"violations": [{family, name, status: "VAPOR", reason}], "faces": [{family, name, status: "ok"|"VAPOR", reason}]}`
  family ∈ `plugin-mcp | agents | env-table`.
- Resolution classes (a face PASSES iff it lands in one):
  A pinned-installable (`git+URL@<ref>`, ref ∉ {main, master, head});
  B in-tree artifact (repo-relative script path exists, or `-m <mod>`
  package dir under a repo source root).
- Exit codes: 0 resolve / 1 vapor / 2 usage.

## Assembly fingerprints

`git diff -- devkit/liveness_fingerprints.json scripts/event_taxonomy.py`
is empty — no liveness fingerprint touched (PR declares: none), no new
EMIT words. Release train still runs
`uv run python devkit/liveness_gate.py --ledger <ws>` (unchanged;
requires `KUNGLAO_LIVENESS_WS`).
