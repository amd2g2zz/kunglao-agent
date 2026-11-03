# Acceptance — WS-4 injection admission (issue #771 remainder)

> Scope: need-driven recall queries, fresh section-level line anchors,
> injection budget, and default-off + demand gate, on branch
> `feat/771-need-driven`. Companion of `acceptance-bridge.md` /
> `acceptance-spec-amendments.md`. All commands run from the repo root;
> every fixture the tests build is SYNTHETIC.

## 1. What to accept — per deliverable

### 1.1 Need-driven queries (category expansion retired)

**Claim.** Recall queries derive ONLY from the dispatch question's
keywords (`queries_for_question`, hooks/recall_inject.py:158): the v1
envelope and red-team marker are stripped, ASCII keywords (len ≥ 3,
stopword-filtered) plus CJK runs join into ONE query. The GO_SIGNALS /
WEB_SIGNALS / WEB_QUERIES category tables and the tier fallbacks
("vm"/"dynamic"/"static analysis") are deleted; a keywordless question
yields no query and no injection.

**Acceptance command.**

```bash
uv run pytest tests/test_recall_default_771.py -q -n 4
```

Expected: exit 0, `10 passed` — `test_queries_derived_from_question_keywords_only`,
`test_no_category_default_expansion`, `test_demand_gate_closed_on_keywordless_question`.

### 1.2 Section-level locations (fresh anchors)

**Claim.** Every injected item carries `path:L<start>~L<end>`
(`_section_anchor`, hooks/recall_inject.py:180): the file is split on
`#` headings at QUERY time, the section with the best query-token
overlap wins (ties → earliest), and no offset is ever stored — a
revised file re-anchors on the next dispatch.

**Acceptance command.**

```bash
uv run pytest tests/test_recall_default_771.py::test_every_injected_item_carries_fresh_line_range tests/test_recall_default_771.py::test_line_range_computed_fresh_not_stale -q
```

Expected: exit 0, `2 passed` — items match `\S+\.md:L\d+~L\d+`; rewriting
the fixture between dispatches moves the anchor (`L5~L7` → `L8~L10`).

### 1.3 Injection budget

**Claim.** At most MAX_INJECT_FILES=3 distinct files, MAX_INJECT_ITEMS=5
located items, MAX_INJECT_CHARS=1200 chars for the whole recall block
(hooks/recall_inject.py:138-140); over-budget items are dropped whole.

**Acceptance command.**

```bash
uv run pytest tests/test_recall_default_771.py::test_budget_files_items_and_chars -q
```

Expected: exit 0, `1 passed` (8 recalled paths → ≤3 files, ≤5 items,
≤1200 chars in `<kunglao-facts>`).

### 1.4 Default OFF + demand gate

**Claim.** `evaluate()` arms ONLY on `KUNGLAO_RECALL=1`
(hooks/recall_inject.py:730); unset/other values pass through silently
(the #694 H2H receipt: default face demoted). Opted in, the demand gate
still requires extractable question keywords (hooks/recall_inject.py:755).

**Acceptance command.**

```bash
uv run pytest tests/test_recall_default_771.py::test_default_off_without_opt_in tests/test_recall_default_771.py::test_opt_in_env_arms_recall tests/test_recall_default_771.py::test_demand_gate_closed_on_keywordless_question -q
```

Expected: exit 0, `3 passed`.

### 1.5 Migration of the old default-on pins

`tests/test_recall_inject.py` carries one autouse `KUNGLAO_RECALL=1`
fixture (opt-in fixtures, one mechanical batch); the ws5 registry pins
the opt-in explicitly per kunglao arm (`docs/design/ws5-five-arms.yaml`).
Six pins whose SUBJECT was the retired category/tier mapping are
`pytest.mark.skip` and listed in the PR body.

```bash
uv run pytest tests/test_recall_inject.py tests/test_recall_quality_814.py tests/test_gap_note_injection_391.py tests/test_xml_injection_55.py tests/test_web_knowledge_761.py tests/test_eval_matrix_ws5.py tests/test_recall_default_771.py -q -n 4
```

Expected: exit 0, `116 passed, 34 skipped`.

## 2. Where it plugs in

Integration point: `hooks/recall_inject.py:evaluate` (PreToolUse on
Agent, wired by scripts/hook_activation.py alongside dispatch_gate).

Before → after call chain (who calls recall, who consumes injections):

```
Claude Code PreToolUse(Agent)
  → recall_inject.main()                       hooks/recall_inject.py:778
    → evaluate(payload)                        hooks/recall_inject.py:699
      [before] tier_for_claim → queries_for_features (category tables)
      [after ] opt-in check :722 → queries_for_question :156
               → demand gate :742 → recall_files_batch (unchanged engine)
               → _injection_context → _guidance :566 (anchors + budget)
    → hookSpecificOutput.additionalContext JSON
      → the DISPATCHED agent reads the located sections before working
```

`references_recall.py` (engine) and `failure_analysis_gate` (sibling
consumer of `recall_files`) are call-compatible and unchanged.

## 3. How the connection works

- **Payload schema** (unchanged envelope, new body): the
  `hookSpecificOutput.additionalContext` text block stays wrapped in
  `<kunglao-facts>` (the #55 producer-tag contract); the read line now
  carries located items `path:L<start>~L<end>` and a header naming the
  query (`recall_inject: need-driven recall - query: ...`).
- **Stores**: `runs/.recall-inject.json` (per-worker dedup hash) and
  `runs/.recall-metrics.jsonl` keep their schemas; dedup keys by claim
  id over (path, content-digest) pairs — anchors are derived bytes, so
  dedup semantics are unchanged.
- **Env contract**: `KUNGLAO_RECALL` flips from opt-out ("0" disables)
  to opt-in ("1" arms). The ws5 matrix launcher already strips and
  re-declares it per arm; `docs/design/ws5-five-arms.yaml` loop arms now
  declare `"1"`, `kunglao-warm-no-l1` keeps `"0"`.
- **EMIT words**: no new words — the trace face reuses the registered
  `recall_injected` / `recall_skip` (scripts/event_taxonomy.py:288-289);
  the demand-gate closure is a `recall_skip` row with
  `reason=demand_gate_closed_no_question_keywords`.

## 4. Assembly acceptance

After ALL Phase 1+2 modules land (T4 injection admission, T5 watchdog,
T6 supply gate, T7 transaction), the synthetic campaign replay must
keep the liveness ledger non-degraded:

```bash
uv run python devkit/liveness_gate.py --ledger
```

Expected: exit 0; no fingerprint DEGRADES vs the pre-change baseline.
This PR touches no fingerprint faces — `rl-admission-consumed` (the
dispatch-side admission read face, hooks/dispatch_gate.py:949) reads
dispatch rows, not recall rows, and is untouched; the recall trace
reuses the already-registered `recall_injected`/`recall_skip` words.
On the four-arm campaign (Phase 4), recall is armed per arm exactly via
the ws5 `KUNGLAO_RECALL` declarations — the no-L1 arm must show ZERO
`recall_injected` rows and the warm arm's rows must each carry ≤5
located items.
