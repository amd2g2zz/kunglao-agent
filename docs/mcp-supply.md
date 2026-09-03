# MCP supply policy — why no root `.mcp.json`

External harness auditors flag the missing root `.mcp.json` as low Context
Efficiency. This is an explicit deviation, documented here.

kunglao-agent workspaces are per-sample; each workspace's MCP surface is
injected BY `kunglao-init` INTO `<workspace>/.claude/settings.json` /
`.mcp.json` at init time (type-aware supply matrix — see
`scripts/mcp_probe.py`, issue-tracked supply manifest). A repository-root
`.mcp.json` would:

1. leak analysis-phase servers (ghidra/x64dbg/frida/volatility) into every
   unrelated session opened at the repo root;
2. drift from the type-aware matrix that init computes per project type
   (windows/linux/android/web/macos);
3. duplicate a decision that already has a single mechanical source.

Auditors: treat `scripts/mcp_probe.py` + init's injection step as the
authoritative control point; the expected artifact is
`<workspace>/.mcp.json`, not `<repo>/.mcp.json`.
