# Auto-update (marketplace version sync)

User-side: when Claude Code loads a marketplace plugin with a `git` source, it
compares the installed `version` against the marketplace's current `version`
on each invocation that resolves the plugin. Bump the marketplace `version`
on the server and every install sees the upgrade prompt on next use.

This plugin had version drift risk: a new `v*.*.*` tag landed, but the manifest
`version` was hand-bumped, easy to forget. Closing that gap.

## Path

```
git tag v0.1.4          →  .github/workflows/auto-update.yml
                       →  opens PR "auto-bump plugin manifest to 0.1.4"
                       →  master merges   →  Claude Code marketplace fetch
                                            →  install sees newer version
                                            →  user prompted on next /kunglao-agent
```

## Why a PR and not a direct push

- Master is the production line; auto-bump should ride the same review gate
  as any other change (diff is small, but the contract is the contract)
- Tag-triggered workflows that push directly to master can race with other
  maintenance commits; the PR model gives the maintainer a single-look
  diff to glance at

## Manual override

If a release needs to land without going through `git tag` (e.g. security
fix mid-cycle), edit `version` in `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` directly and push — the workflow only
triggers on `v*.*.*` tags.
