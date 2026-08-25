# Design — anomaly detection layer (#663)

## D1. Anomaly score model

A fact's anomaly score is the **maximum** of three sub-scores (each in `[0, 1]`), so any single dimension can flag:

```
score(fact, baseline) = max(
    lexical_rarity_score(fact.conclusion, baseline.term_freq),
    semantic_unusualness_score(fact.claim_id, fact.conclusion, baseline.pair_freq),
    path_unusualness_score(fact.sample_refs, baseline.path_freq),
)
```

Threshold semantics: `score ≥ anomaly_threshold` (default 0.7, operator-tunable via `analysis_state.txt`) → auto-promote to `notes/` with `boundary_type: anomaly`. **Max** is chosen over weighted-sum because a single dimension flagging is more useful for analyst attention than partial-flag averaged away; analyst reviews and either confirms anomaly (note stays) or refutes (note removed).

### D1.1 Lexical rarity

Tokenize `fact.conclusion` (whitespace + simple CJK boundary), look up each token's frequency in `baseline.term_freq` (a `dict[str, int]` built once from the baseline corpus). For each token, `rarity = 1 - (freq / max_freq_in_baseline)`. `lexical_rarity_score = mean(rarity over tokens)`; ties broken by the **rarest** token (`min(freq) / max_freq`) so a single very-rare term dominates.

Empty conclusion → `lexical_rarity_score = 0.0` (can't be anomalous without content).

### D1.2 Semantic unusualness

For each `(claim_id, conclusion)` pair (or `claim_id, conclusion_prefix` for length-tolerant matching), look up frequency in `baseline.pair_freq`. `rarity = 1 - (freq / max_freq)`. Same tie-breaking.

Missing pair (never seen in baseline) → `semantic_unusualness_score = 1.0` (unseen = anomalous; the baseline gap is itself the signal). This makes cold-start with no baseline NOT silent — it's loud (everything scores 1.0) — but the `fail-open` decision lives at the integration layer (D5), not the score layer.

### D1.3 Path unusualness

For each `sample_refs` entry (paths under `bins/` or absolute), look up in `baseline.path_freq`. Same max-rare-token tie-breaking. Empty `sample_refs` → `0.0`.

## D2. Baseline corpus sourcing

Three sources, merged (union of `term_freq`, `pair_freq`, `path_freq`):

1. **RE-library pattern docs** (`references/re-library/*.md`) — pre-built, deterministic. Source: `pathlib.Path(__file__).resolve().parents[2] / "references" / "re-library"`. Read once at scan time, cached for the scan call.
2. **Prior completed samples** (`~/.kunglao/samples/`) — populated when the cross-sample memory feature lands (#358 P4 v0.2 batch). Until then: empty, fail-open.
3. **Operator-provided patterns** — path in `analysis_state.txt` line `baseline_corpus: <path>`. Read at scan time, fail-open if file missing.

`scan_anomalies` accepts an optional `baseline` argument (override for tests + cold-start); otherwise builds from the three sources above.

## D3. Schema bump

`scripts/lint_facts.py` changes:
- `VALID_BOUNDARY_TYPE` add `"anomaly"` (sits next to `"contradiction"`).
- `ACTIVE_SCHEMA_REV = 1` → `ACTIVE_SCHEMA_REV = 2`.
- Rationale for the bump: `VALID_BOUNDARY_TYPE` is the lint contract; adding a value changes what `lint_fact` accepts. Per the docstring ("Bump ONLY on a backward-incompatible frontmatter schema change") — an additive enum value IS technically backward-incompatible for consumers reading `boundary_type` as a closed set, so the bump is correct (consumers that exhaustively matched the prior 9 values must add `"anomaly"`).
- `OPEN_BOUNDARY_TYPES` unchanged (anomaly is in `EMPTY_GATE_TYPES` like `contradiction`).
- `EMPTY_GATE_TYPES` add `"anomaly"` (mirrors `"contradiction"` — an anomaly fact doesn't carry a `promotion_gate`).

## D4. State machine integration (`convergence_check.py`)

Per #443's explicit state machine, additive change only:

```
STAGE_PROBES[State.DRAIN] = (
    ORPHAN_TERMINAL_CLAIM,
    PRIMARY_Q_UNVERIFIED,
    NOTE_LAYER_GAP,
    DISCOVERY_UNCONSUMED,
    GLOBAL_CONTRADICTION,
    ANOMALY_DETECTED,           # ← inserted
    DRAIN_CLEAN,
)

TRANSITIONS[(State.DRAIN, Event.ANOMALY_DETECTED)] = (State.BLOCKED, _act_anomaly)
```

`_act_anomaly(s)` returns the same shape as `_act_contradiction`: `"Cannot CONVERGE: <N> anomaly fact(s) <ids> with scores <scores> — review or refute"`. Verdict `BLOCKED` (not `SATURATED`) because anomalies are reader-action items, not "wait for worker" items — mirrors the contradiction verdict.

`_anomaly_detected(s)` predicate: `bool(s.anomalies)` where `s.anomalies` is a lazy-loaded list (cached like `discovery_reason()` and `contradiction_reason()`) of `{fact_id, claim_id, score, top_dimension}` dicts.

`_DecideInputs` gains one field: `anomalies: list | None = field(default=None, repr=False)` with a `anomaly_reason()` accessor mirroring `contradiction_reason()`.

`_scan_anomalies(workspace)` helper: pure read of `facts/_INDEX.md` + facts/ + baseline, returns the list. Lazy + cached via `_DecideInputs`.

## D5. Fail-open semantics

Three layers, all fail-open (mirror `fact_contradiction_gate` posture):

- **Baseline missing** (`term_freq` empty): `score_fact` returns `0.0` (not anomalous — no baseline means no surprise signal). `scan_anomalies` returns `[]` and emits one `kunglao_log` warning `"anomaly: empty baseline corpus — anomaly detection disabled"`. **DRAIN stays clean** — no anomaly-driven BLOCKED.
- **Baseline file unreadable** (corrupt / permission): same as missing — warn + `[]`.
- **Single fact unreadable** (parse failure): skip that fact, warn, continue with others.

This is **deliberately not fail-closed**. The reason: anomaly detection is a *reader attention* mechanism, not a *correctness* gate. Failing closed would BLOCK every convergence when the baseline corpus is empty (cold-start), which is the worst case for an analyst who needs the rest of the loop to proceed. Correctness remains with contradiction + maker-checker.

## D6. CLI and integration surface

```
python scripts/anomaly_detector.py <ws> [--json] [--threshold 0.7]
```

Exit codes:
- `0` = no anomalies (or empty baseline — informational)
- `1` = anomalies detected (anomaly list printed)
- `2` = usage error

`scan_anomalies` is also called by:
- `scripts/convergence_check.py::decide()` (DRAIN stage, lazy)
- `scripts/progress_report.py` (anomaly count surfaces)
- `tests/test_anomaly_detector.py` (unit + integration)

## D7. Performance

`scan_anomalies` reads `facts/_INDEX.md` once (cached in `_DecideInputs`), reads each fact body (lazy — only when score > 0), reads RE-library pattern docs once (module-level memoization via `_BASELINE_CACHE`). For a workspace with 100 facts and a 50-doc RE-library baseline: cold scan ≈ 50ms; warm (cached) ≈ 5ms. No problem at any realistic scale.

## D8. Maker-checker boundary (decision)

Anomaly is **not** a verdict demotion. A fact with `score > threshold` keeps its existing status (PROVEN / INFERRED / etc.); the anomaly just adds a co-resident note. **Rationale**: the user's "AES example" complaint was that the loop *missed* an observation, not that it *overruled* one. Adding a co-resident note (visible in `progress_report.py`) is the right minimum-viable intervention. If we later need anomaly-driven STAMP downgrade, that's a separate change with its own openspec.

## D9. Out-of-scope decisions (linked)

- **#662 hypothesis seed**: optional integration (feed high-anomaly into hypothesis competitor groups) — separate followup.
- **Cross-sample baseline** (issue deferred per #358): if P4 ships, baseline sources grow; this change's D2 design accommodates.
- **ML-based anomaly detection**: explicitly out-of-scope per issue body. Heuristic only.

## D10. Test strategy

Per the project's RED-first contract:
- RED tests first (all `tests/test_anomaly_detector.py::*` should fail before `anomaly_detector.py` exists)
- GREEN after impl
- Integration with `claim_migrator` (no behavior change — anomaly is observation, not demotion)
- Integration with `convergence_check` DRAIN (state machine adds event, fires only when anomalies present)
- `test_acceptance.py` end-to-end: anomaly in workspace → DRAIN_BLOCKED with reason naming fact
