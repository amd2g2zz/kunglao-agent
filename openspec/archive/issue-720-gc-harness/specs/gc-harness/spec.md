# GC Harness v1 — Behavioral Spec (#720)

## Spec lifecycle states (registry-only, .agent/specs.yaml)

- NEW → ACTIVE → SUPERSEDED → ARCHIVED；大量 ACTIVE 并存视为违规信号（报告，不自动合并）

## spec_gc.py contract

```
search <query>   → prints ACTIVE specs matching id/path tokens + "Decision: modify (default) | create (new domain capability only)"
scan [--apply]   → per spec: code_refs (scripts/ hooks/ tools/ gc-harness/ grep) + test_refs (tests/ grep)
                   Rule 1: code_refs==0 AND last_modified older than orphan_days → status=ARCHIVED (apply only)
                   Rule 2: test_refs==0 → flag SUSPECT (report only)
                   Rule 3: duplicate path-stems → report only, never auto-merge
init             → register every openspec/changes/<dir> with proposal.md as ACTIVE (registration only, no adjudication)
```

Fail-open: registry missing → empty; grep errors → count 0 + WARN.

## test_gc.py contract

```
scan             → CANDIDATE_DELETE if (registered last_failure older than 180d) OR (identical test function name in 2+ files)
quarantine <path>→ git mv to tests/quarantine/ + record {id, original_path, quarantined_at}
restore <id>     → move back + status ACTIVE
expire [--apply] → quarantine entries older than quarantine_days → DELETE candidates; --apply removes file + status REMOVED
experiment <p>   → prints removal-experiment protocol (mutmut before/after commands); no built-in runner
record <id> [--failed] → maintain last_failure in registry
init             → register tests/test_*.py as ACTIVE (registration only)
```

Fail-safe: no registered last_failure ⇒ never a candidate by condition ①.

## worktree_gc.py contract

```
scan [--apply]   → merged: branch is ancestor of origin/dev AND last commit older than merged_days → candidate
                   abandoned: zero own commits AND dir mtime older than abandoned_days → candidate
                   --apply: git worktree remove + branch -D + record {commit_hash, branch, pr_link} in .agent/worktrees.yaml
                   main worktree never a candidate; default dry-run
```

## Artifact Budget observation (devkit/quality_gates.py, observation section — WARN, not a gate)

- diff base: origin/dev (fallback HEAD); counts added: new spec dirs (openspec/changes/), new tests (tests/test_*.py), total files
- budgets from gc-harness/config.yaml: max_new_spec=1, max_new_test=5, max_new_files=20
- over budget AND .agent/budget_justification.md empty → `[warn]` + required justification template
- over budget WITH justification → `[observe]` + note; exit code unchanged

## Metadata schema (.agent/*.yaml, gitignored — identity/status/linkage ONLY)

```yaml
specs:   [{id, path, status, created, last_modified, linked_tests: []}]
tests:   [{id, path, status, created, last_modified, last_failure, quarantined_at, original_path}]
worktrees: [{branch, path, status, commit_hash, pr_link, last_modified}]
```

Forbidden fields: score, embedding, any AI-judgment result.
