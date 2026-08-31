# Tasks — 派发协议结构化 (issue #452)

## Phase 1 (this PR)

- [x] 1.1 Define v1 JSON protocol schema + `parse_dispatch_json()`
- [x] 1.2 `parse_dispatch()` 优先 v1,fallback v0
- [x] 1.3 `dispatch_gate.py` 用共享解析器 + `_warn_unparseable()`
- [x] 1.4 Write `docs/dispatch_protocol.md`
- [x] 1.5 Write `tests/test_dispatch_protocol.py` (17 tests, all green)
- [x] 1.6 openspec/{proposal,design,spec}.md
- [ ] 1.7 Commit + push + open PR