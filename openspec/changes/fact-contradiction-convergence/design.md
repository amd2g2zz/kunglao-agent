# Design — fact-contradiction-convergence (#47)

## Design Decisions

### D1. CONFLICT is a gate verdict, not a new fact.status

`schema.md`'s `VALID_STATUS` stays untouched (`PROVEN | INFERRED | NEGATIVE | REFUTED | OPEN | DEFERRED | VERIFIED`). The gate returns a **verdict** (`CONFLICT`), and the promotion path maps it to the existing downgrade mechanism: effective status `STAMP` (non-terminal) with reason `needs-resolution: F035 <-> F040`. This mirrors `blind_gate.py` exactly — `check_proven_gate` returns `(allowed, effective_status, reason)` with `STAMP` on failure; the contradiction gate returns `(allowed, reason)` and composes into the same `effective_status` variable. No schema migration, no new terminal state that could wedge convergence.

### D2. Topic = claim_id equality OR sample_refs overlap

Two facts are same-topic iff:
- both rows have non-empty `claim_id` and they are equal, **OR**
- both facts have non-empty `sample_refs` and the sets intersect.

`claim_id` comes from the `_INDEX.md` row (col 3); `sample_refs` comes from fact frontmatter (yaml fenced block or line-level `sample_refs:` key). This mirrors the a2b5e25c pair (F035/F040 shared a routing claim) and the issue's "sample_refs/cites/claim keyword" grouping. `cites` is parsed too and included in the topic fallback when neither claim_id nor sample_refs are present (a fact that cites the same evidence eid as another PROVEN fact is same-topic by evidence scope). Concretely the topic key is a frozenset of normalized tokens: `{claim_id}` if present, else `sample_refs` set, else `cites` set; two facts conflict-check when key intersection is non-empty.

### D3. Conclusion difference = whitespace-normalized inequality

Two conclusions "differ" iff `" ".join(conclusion.split()) != " ".join(other.split())`. Same conclusion on the same topic = converged (not a contradiction) — pass. The gate does NOT judge which conclusion is correct (that is the RCA/backfill process); it only blocks silent coexistence.

### D4. Supersedes link resolution

A pair is resolved iff either side declares a link naming the other:
- `supersedes: F<id>` (this fact supersedes the named fact), or
- `superseded_by: F<id>` (this fact is superseded by the named fact).

Parsing: extract from yaml fenced blocks OR line-level keys in the fact text (`supersedes:` / `superseded_by:`), values may be a single id, comma-separated ids, or a yaml list. Normalize `F<id>` forms (accept `F035`, `F-035`). Link presence on either side of the pair resolves the pair regardless of direction consistency (we do not police link symmetry in the gate; `kunglao_record` migration and human backfill own correctness).

### D5. Wire points (composition, not new flow)

1. **`kunglao_record.py::claim_migrator`** (PROVEN branch, after BLIND gate): call `check_proven_contradiction(claim_id, ws/"facts")`; on conflict, `effective_status = STAMP` and append `[CONFLICT GATE: F035 <-> F040 (needs-resolution)]` to the message. BLIND and CONFLICT failures compose (either downgrades; message carries both reasons).
2. **`hooks/worker_budget.py::compare_register_change_proven_gate`**: for each newly-PROVEN `cid`, run the same check (via `blind_gate.find_fact_file` to locate the fact, then the gate); violations join the `violations` list that blocks the write. This is the orchestrator-direct-write backstop (mirrors the BLIND backstop at L373-418).

Both wire points reuse `scripts/fact_contradiction_gate.py`'s pure functions; no duplicated logic. `scripts` import via the existing `sys.path.insert` pattern (worker_budget already does this for `blind_gate`; `kunglao_record` uses try/except ImportError fail-open, matching its BLIND-gate import).

### D6. CLI (small, verification-first)

`python scripts/fact_contradiction_gate.py <ws>` prints scan_conflicts output (one line per conflict pair) and exits 0 if clean / 1 if any CONFLICT — the mechanical gate for backfill verification (mirrors `--grace-scan` precedent from #49). The core is the pure `scan_conflicts`/`check_proven_contradiction` functions; the CLI is a thin wrapper.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/fact_contradiction_gate.py` | CREATE | pure functions + CLI: `_topic_key`, `scan_conflicts(index_path, facts_dir)`, `check_proven_contradiction(claim_id, facts_dir)` |
| `scripts/kunglao_record.py` | UPDATE | `claim_migrator` PROVEN branch: contradiction check → STAMP downgrade (~10 lines) |
| `hooks/worker_budget.py` | UPDATE | `compare_register_change_proven_gate`: contradiction backstop (~15 lines) |
| `tests/test_fact_contradiction_gate.py` | CREATE | RED1-RED4 + F035/F040 backtest + edges |
| `references/schema.md` | UPDATE | one-line convention: `supersedes:`/`superseded_by:` required for same-topic multi-PROVEN with differing conclusions |

## Out of scope

- Auto-healing: the gate does NOT rewrite facts, pick a winner, or add supersedes links itself (human/backfill process owns that; a2b5e25c backfill happens in the malware-analysis workspace, not this repo).
- `cites`-only grouping depth: cites is a fallback key; evidence-index resolution (eid→file) is `provenance_gate.py`'s job, not this gate's.
- Note-layer contradictions (notes/NNN vs facts): the issue scopes fact-layer only.
