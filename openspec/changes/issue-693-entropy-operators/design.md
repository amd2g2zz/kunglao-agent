# design — issue-693-entropy-operators

## Verified anchors (branch feat/693-entropy-operators off dev 5e1163bc)

| Question | Actual | Drift |
|---|---|---|
| Where the ΔH term died | `scripts/priority_ratio.py` — the score is `(case_face + W_DOWNSTREAM·dterm) · worth`; the ΔH_PQ face removal is pinned by `tests/test_value_rebuild_107.py` + `tests/test_epistemic_pricing_250.py` (ADR-001 removal pins) | none — untouched |
| The entropy machinery that already exists | `scripts/posteriors.py::PQCategorical` — `entropy()` / `update_eliminate` / `update_evidence`; `scripts/entropy_face.py` — frontier PQ entropy + trend, fail-open, consumed by statusline_snapshot + heartbeat_tick (dual-use display) | none — untouched |
| The covering-array machinery | `scripts/replay_equivalence.py::required_combos(variables, strength)` — t-way combos as canonical `((var, canonical_value), …)` tuples; consumed today only by `coverage_errors` (verification side) | none — now shared with the search face |
| Option-death keying | `scripts/rlvr/termination.py` — Beta per `(kind, family)`, cells sorted, verdicts floor sampler weight; heavily pinned by `tests/test_rlvr_termination_461.py` | none — untouched (layer accounting is the NEW face) |
| The hypothesis carrier | `scripts/hypothesis_store.py` — open/refuted/superseded, terminal states never reopen | none — untouched (mint-only) |
| Hash constant tables | absent repo-side (`tools/crypto/algorithms.py` = ciphers/compression/envelope, no hash IVs) | cured by `rlvr.constants_ref` |
| Export-map drift test | no test pins `rlvr.__all__` membership today (the docstring aspiration) | disclosed — additions verified by import smoke |

## Decision 1: entropy stays observable-only; non-degeneracy is the cure, not the term

ADR-001 removed the term because ΔH ≡ 0 on degenerate ledgers. The
governed re-entry path (ADR-001 §2) requires real-ledger evidence that
the term moves TTC/order — evidence that cannot exist while the
distribution is degenerate. So this card supplies the operators that
keep the hypothesis space NON-degenerate (prune impossibilities, refine
mismatches to a layer, enumerate the search matrix), and pins the gate
itself: a test proves a non-degenerate categorical changes the entropy
FACE (h_bits = log2(3)) while ranking two workspaces byte-identically.
No score path, no feed, no λ.

## Decision 2: the refinement decision tree is mechanical, not a model call

`refine_on_mismatch(family_match, kat_pass)` is a 3-branch pure
function over the evidence structure the workspace already produces:
constant-set diff (does any reference table match?) and known-answer
test (does the primitive core verify?). The mapping is the issue's own
diagnosis: no family match -> family layer; family match + KAT fail ->
primitive layer; both pass + digest mismatch -> composition layer (the
`md5(plaintext) != captured` case that used to kill the family). The
returned sub-space NAMES what to re-search and explicitly scopes what NOT to re-litigate
("family constants already match, do NOT re-litigate the family").

## Decision 3: layer attribution rides a map, not a schema change

`layer_death_cells(rows, layer_of)` consumes the obstacle-row shape
(`kind` + `method_family`) read-only and takes the family->layer
attribution as an argument. No obstacle-registry schema change, no
re-record of history: old rows work; the layer attribution is
hypothesis-layer knowledge (which layer a family's search currently
operates at), which belongs to the hypotheses face, not the evidence
registry. Unattributed families land in the explicit `unscoped` bucket
— absence is honest, never silently folded into a named layer.

## Decision 4: covering matrix delegates, never re-implements

`covering_matrix` calls `replay_equivalence.required_combos` (the one
t-way enumeration) and decodes the canonical values back to declared
domain members. Two implementations of t-way enumeration would drift;
one implementation with two consumers (verification `coverage_errors`,
search `covering_matrix`) cannot.

## Decision 5: constant tables are generated-and-cross-checked, not transcribed

Every family table is pinned by a shipped digest roundtrip
(tests/test_constants_ref_693.py): a compact pure-python
re-implementation of each family's compression function READS the
module's tables and must reproduce `hashlib` digests (SM3: the
standard's published "abc" known-answer vector, plus hashlib when the
local OpenSSL provides it) on empty / abc / multi-block / 256-byte
vectors. MD5's T-table is sine-derived and SHA-256's IV/K are
prime-root fractions; SHA-1's IV is the FIVE registers
(0x67452301..0xC3D2E1F0 — a four-word truncation makes a genuine
SHA-1 constant set classify as mutated, so the roundtrip pins the
register count mechanically). SM3's constant set is the 8 IV words +
the two T round constants (0x79CC4519 / 0x7A879D8A) — the complete
digest-compression constant set (CK is SM4's standard, not SM3's).
`classify` picks the max-matched table, so a mutated variant still
IDENTIFIES as its family while `exact=False` — the separation the
acceptance criterion demands.

## Decision 6: invariant contradiction rules are per-key, bound-aware

`output_len` and `input_alignment` are fixed properties — any
difference from the observation contradicts (exact-match rule).
`min_loop_bound` is a one-sided lower bound: a prediction BELOW the
observed smallest loop count contradicts (a core needing fewer
iterations than the trace shows could not have produced it), while
predicting MORE stays inconclusive (longer inputs legitimately
iterate further — conservative pruning never rejects on the safe
side). The rule table lives next to the key vocabulary, so a new
invariant key arrives with an explicit rule instead of a defaulted
comparison.

## Process deviation disclosure

GitNexus MCP was unreachable in the session; impact analysis ran via
the gitnexus CLI (`node .gitnexus/run.cjs impact`) plus a mechanical
importer survey (93 files import rlvr). The only edited existing file
is `scripts/rlvr/__init__.py`: 25 insertions, 0 deletions (three
module imports + `__all__` names + docstring bullets) — additive
export-map growth, risk LOW. All three new modules are leaf-pure (no
workspace IO except the canonical warn sink).
