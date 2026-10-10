# Design — issue-487-query-formulation

Interpretation (2 sentences, stated up front): the flow gap is between the trigger scan
and the distill dispatch — the query the retrieval face uses is the raw trigger fragment.
We insert ONE mechanical, budget-free stage (formulate → per-facet retrieve → coverage
matrix) that runs before the dispatch prompt is minted in both hosts (e2e tick step +
production closure stamp), leaving the act, budget, report, oracle, and landing faces
untouched.

Design review (disclosed self-review, the #478 quota-wall precedent): the three
adjudication points the dispatcher named — the problem-representation schema, the
per-facet retrieval loop, the coverage matrix + disambiguation — are each decided below
with the alternatives considered. Alternatives rejected: (a) LLM-side formulation (the
worker narrating its own problem) — rejected because the raw material is already
structured state in the workspace and narration is exactly what #461's
attribution-in-state ruling displaces; (b) extending `online_distill.py` in place —
rejected: the engine is at 888 lines (over the 800 file cap) and formulation is a
distinct organ with its own test surface; (c) embedding retrieval in the dispatched
agent only — rejected: the coverage matrix must exist BEFORE the act to steer it and to
serve as the false-trigger guard.

## 1. Problem-representation schema (`query-formulation/1`)

```
{
  "schema": "query-formulation/1",
  "trigger": {"kind": ..., "token": ..., "sample_hint": ...},
  "facets": [Facet, ...],              # 3..5, order fixed
  "sources_read": ["evidence/die.json", "evidence/apkid.json",
                   "runs/obstacles", "runs/worker-status-*.md"]
}

Facet = {
  "kind": "format_family" | "technique" | "tool" | "error_signature",
  "face": str | None,                  # disambiguator for repeated kinds
  "terms": [str, ...],                 # 1..6 normalized lowercase
  "query": "android native elf",       # " ".join(terms)
  "provenance": [{"source": "evidence/apkid.json#summary.packer",
                  "value": "aplib"}, ...]
}
```

Four kinds (the issue's four term classes, closed enum). Facet count is
evidence-bounded, floor 3, cap 5:

1. `format_family` — always present. Terms from die `derived.language`,
   die `derived.detected_packer` / `detects`, apkid `summary.packer` /
   `summary.obfuscator`, the sample-hint suffix (closed map: `.apk`→android,
   `.so`→native library, `.dex`→dex, `.jar`→java, `.zip`→archive),
   fallback `binary` (the
   anchored sample is a byte container — always true, never fabricated). A
   `format-unknown` trigger adds the closed fallback terms (unknown format /
   file identification / entropy).
2. `technique` — always present. Terms from apkid `summary.anti_analysis`
   rules (tokenized on `_`), obstacle `kind` (closed map:
   encryption_layer→encryption, detection_trigger→anti analysis,
   tool_limit→tooling, missing_env_entry→environment), obstacle
   `method_family`, fallback: the trigger token's own components.
3. `tool` — always present. The trigger token verbatim (normalized,
   `:`→space) + its components + `method_family` terms.
4. `error_signature` — only when material exists, in two faces: face
   `obstacle` (cause one-liners → technical tokens; stopwords dropped by a
   closed list) and face `probe` (die `call_errors` keys). Two faces may
   both appear → the count reaches 5.

Every term records the (source, value) it came from — provenance is what the
reformulation pass re-words from, and what makes the representation auditable
("a term with no provenance is fabrication" is a structural test).

Normalization: lowercase, `[_:/]`→space, whitespace collapse; terms 1–40
chars; ≤6 per facet (order of first appearance).

## 2. Per-facet retrieval loop (mechanical, local)

`retrieve_facets(corpus_root, formulation)` — corpus default
`references/re-library/` resolved relative to the module's install parent
(works in-repo AND deployed under `.claude/`); explicit override for
fixtures/tests.

- Cards: `*.md` / `*.yaml` under the corpus root (rglob, sorted; read
  tolerant; 512 KB per-file defensive cap). Card text + term are normalized
  identically (lowercase, `[_:/-]`→space) so `anti analysis` matches
  `anti-analysis` and `sha 256` matches `sha-256`.
- Match: term present on word boundaries in the normalized card text
  (lookarounds `(?<![a-z0-9])term(?![a-z0-9])`).
- Per facet, independently: card score = number of DISTINCT facet terms
  matched; a card covers the facet at the half-ceiling rule — score ≥
  ceil(n/2) of its n terms, minimum 1 (a single-term facet asks for its
  one term, a two-term facet for one, a five-term facet for three — the
  rule scales with facet size instead of a flat 2). Hits = top 5 by
  (score desc, path asc), recorded corpus-relative.
- No cross-facet merging: facet independence is the point (coverage is
  measured per facet, not per act).

## 3. Coverage matrix + empty-facet disambiguation (`distill-coverage/1`)

```
{
  "schema": "distill-coverage/1",
  "corpus": "references/re-library",
  "facets": [
    {"kind": ..., "face": ..., "query": ..., "hits": [{"path": ...,
      "matched": [...], "score": n}], "verdict": "hit"
     | "reformulated-hit" (+"reformulated_query")
     | "corpus-lack", "reformulated": bool}
  ],
  "summary": {"facets": n, "hits": n, "reformulated_hits": n,
              "corpus_lack": n}
}
```

Empty facet → disambiguate corpus-lack vs bad-query with EXACTLY ONE
reformulation: the facet is re-worded from its PROVENANCE terms (raw
provenance values tokenized, deduped against the original terms, capped 6).
Re-retrieve; hit → `reformulated-hit`; still empty (or the reformulated set
is empty/identical — no material to reword) → `corpus-lack`. Corpus-lack is
the REAL shelf-miss verdict: the distill act proceeds exactly as today (web
face), so a corpus-lack can never block or budget anything — it is the
false-trigger guard the issue asks for (a facet that hits locally means the
"miss" was partly a recall failure, and the hit cards ride the prompt).

## 4. Host wiring (both retrieval faces)

- e2e tick step (`scripts/e2e/checkpoints.py::_maybe_distill`): after
  `reserve_act` succeeds and before the prompt is minted, load
  `query_formulation` via `_load_repo_module` (the twin-resolution guard)
  and run `formulate_and_retrieve(ws, trigger, repo)`. The dispatch prompt
  gains a `Problem formulation (#487)` section: facets (the retrieval
  queries), hit cards (validated starting points), corpus-lack facets (the
  web-face priorities). The `distill_result` audit row's detail carries the
  coverage matrix (new `coverage=` kwarg on `emit_distill_result`, omitted
  when None); the tick `detail["distill"]` entry carries formulation +
  coverage. Failure of formulation is one rate-limited warn + the act
  proceeds unformulated (fail-open rider, the scan-failure precedent).
- production closure (`hooks/round_closure.py`):
  `online_distill.formulate_for_trigger(ws, trigger)` (engine-side delegate,
  lazy sibling import, fail-open → None) feeds
  `online_distill.stamp_trigger(ws, triggers, formulation=...)`, which now
  stamps `formulation` + `coverage` into `runs/distill-trigger.json` — the
  object the orchestrator's dispatch protocol reads (SKILL.md's shelf-miss
  dispatch protocol paragraph gains one sentence: the dispatch prompt
  carries the stamped formulation + coverage; corpus-lack facets are the
  web-face priorities).
- `online_distill.py --scan` formulates for the first trigger and stamps it
  (CLI/host parity, the #458 rule).

## 5. Fixture — good formulation beats fragment queries

`tests/fixtures/query-formulation-487/corpus/` — 6 synthetic cards
(frontmattered, deliberately NOT under `references/re-library/`: no
mapping/_INDEX/pin churn; the fixture is test-local). A staged workspace
(rich environment: apkid packer + anti-analysis findings, die call_errors,
obstacle rows, `shelf-miss: android:sign-recovery sample=bins/libsign.so`)
formulates 4–5 facets whose per-facet retrieval over the fixture corpus
hits the right cards, while the fragment baseline (the raw token terms)
misses. Pinned in `tests/test_query_formulation_487.py`:
`formulated_hit_facets > fragment_hit_facets` with exact counts.

## 6. Non-goals / invariants kept

- No budget interaction (formulation debits nothing; hop/act caps untouched).
- No vocabulary growth: `distill_attempt` / `distill_result` /
  `candidate_landed` carry the coverage in `detail`.
- No spine/landing change (#478 T-pass consumes candidates exactly as
  before; the coverage matrix rides the audit row as E-gate evidence).
- No LLM, no network, deterministic serialization (sort_keys), repo-local
  siblings + stdlib only — the engine discipline verbatim.
- Trigger scan semantics untouched (#458's two-and-only-two rule).
