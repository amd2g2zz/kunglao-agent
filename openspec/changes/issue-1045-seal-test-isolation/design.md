## Context

The diagnostic workspace override is a mutable global box. The key fixture resets seal state and logging dedupe but previously inherited the workspace pinned by unrelated tests. Two seal tests can then share an on-disk once-marker despite separate temporary keys.

## Decision

Use pytest monkeypatch to replace the workspace override with a fresh empty list for each invocation of the key fixture. Tests that explicitly exercise persisted workspace notices continue to pin their own workspace. Monkeypatch restores the previously existing list object at teardown. No logger or seal implementation is modified.

## Integration contract

Caller: pytest creates the key fixture for learning-seal tests. Trigger: each fixture setup before its test runs; teardown restores the prior workspace override. Fingerprint: the ordered jadx and two seal tests each exercise the real warning path and the final unarmed warning is emitted exactly once; separate real workspace marker tests verify persistence and changed-state rearming.

## Invariant coverage

The current registry has no invariant about logging warning isolation. The direct single-change spec-coverage check reports one missing citation; no unrelated invariant is cited. Existing once-marker behavior remains covered by the relevant production-facing tests.
