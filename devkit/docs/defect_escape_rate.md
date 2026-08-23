# Defect Escape Rate — quarterly

## Formula

```
defect_escape = issues_with_label("post-release-bug")
                / total_issues_for_release × 100%
```

A "bug" issue is one labeled `bug`. "Post-release" means filed AFTER
the corresponding release tag was pushed. "Total" includes all bugs
filed against that release cycle (pre + post).

## Target: <10% (TBD after first measurement)

If escape rate > 10% for a release, the next release's test gate MUST
include a regression test for the escaped defect (the issue links to
the PR that adds the test).

## Releases

### v0.1 (released 2026-08-16)
- Pre-release issues: TBD
- Post-release issues: TBD
- Escape rate: TBD
- Notes: (link to most impactful escaped defect)

### v0.1.1 (released 2026-08-17)
- Pre-release issues: TBD
- Post-release issues: TBD
- Escape rate: TBD
- Notes: (one-line retro per release)

### v0.1.2 (in flight)
- Pre-release issues: TBD
- Post-release issues: TBD
- Escape rate: TBD

## Manual workflow

Quarterly (or per-release), the release owner:

1. List all issues for the release cycle (`gh issue list --label bug --search "..."`)
2. For each, check createdAt vs release tag date
3. Compute escape rate
4. Update this file

## Future automation

Phase 3 introduces a labeler bot or release.yml hook that auto-tags
issues at release time. Until then, this is a manual quarterly ritual.

## See also

- `devkit/docs/quality_roadmap.md` — coverage / mutation / pass-rate targets
- `openspec/changes/issue-463-coverage-gate/` — full design
