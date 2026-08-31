# Design — issue #751 web JS semantic index layer

## D1 — vocabulary: js-domain mirror of the android pair (T1)

Rule B (#729) treats `_CAPABILITY_TAGS` as a closed, review-gated
vocabulary. Adding `js:semantic-query` + `js:call-graph` is the same
deliberate decision shape #728 made for `js:deobfuscate` / `js:unbundle`:
the tag names deliberately MIRROR android:semantic-query /
android:call-graph so a claim like "which function builds the signature
string" routes to the same capability pair on either domain. One operation
per tag; no merged "js:query-all" tag (routing granularity would be lost).

## D2 — ADJUDICATION: specialist trigger contract without an agent file (T4)

`recommend_agent_type` reads the mechanical table exclusively from
`agents/*.md` triggers frontmatter (issue #310 zero-drift design), and the
agent-file layer carries heavy contracts (Gate 6 markers #492,
specialist-contract expansion #494). This wave is parallel to #760, which
OWNS agent files (wave item I4) — so NO agents/*.md ships here.

Resolution: the future trigger block is pinned where it can be regression-
tested today — tests/fixtures/web751/specialists/gitnexus-query.md carries
the exact frontmatter #760 must land inside its agent definition:

- intent must_any covers the semantic/xref/call-graph/调用链/谁调用 family
  including signature-trace phrasings ("trace ... function ...");
- features leg matches web-domain sample features (language JavaScript);
- exclude guards against dynamic-analysis tracing collisions.

The pinned test asserts (a) fixture-table routing of the fixed claim →
gitnexus-query, and (b) TODAY's shipped table does not mis-route that claim
to any existing specialist. When #760 lands its file with this block, the
repo-level router inherits the behavior and test (a)'s fixture becomes the
real table verbatim.

## D3 — registry entry extends in place (T2)

One gitnexus-query provider entry covers both domains rather than adding a
second entry: validate_index enforces UNIQUE provider tokens, so a second
"gitnexus" entry is structurally illegal, and the lazy-index marker
(evidence/gitnexus_index.json + {source_root, indexed_at, tools}) is domain
blind. requires stays `[source_tree, gitnexus_index]`; the input_output /
when_not text records HOW source_tree is satisfied on js targets (a
wakaru/webcrack output directory registered as evidence unpack_out).

wakaru/webcrack entries gain the `unpack_out` hand-off note instead of a new
token: PROVIDER_TOKENS is closed (#692 design D2) and pre-tree recovery has
no additional precondition to name — the note documents the evidence field
the worker registers.

## D4 — quickref step placement (T3)

The index step lands between peeling loop completion and parameter
location inside the layered-peeling section — L93's strip flow ends at
"clean", and the signed-parameter workflow starts at capture; the missing
step was "make the recovered tree queryable before you start reading it".
Methodology posture only (what to ask the graph); invocation details stay
with the demo script + _index-static.md contract entry because the #760
worker owns the execution protocol.

## D5 — T5 demo architecture

Local host facts (2026-08-26): wakaru 1.10.0 runtime REJECTS darwin-x64;
webcrack 2.16.0 works when npm uses an alternate cache dir (default
~/.npm cache has an EACCES permission defect); gitnexus 1.6.9 CLI works.
Therefore tools/static/web_gitnexus_demo.py runs THREE legs with
independent availability probes:

1. wakaru --unpack — skips with reason on this host (platform);
2. webcrack -o — real run here (npm_config_cache fallback), SKIP offline;
3. gitnexus analyze + context/query — real run here.

Fixture: tests/fixtures/web751/bundle.min.js (hand-built webpack-shaped
bundle, verified runnable; exported API names survive minification because
they are property assignments). The bundle executes under node BEFORE the
demo consumes it (regression gate that the sample itself is valid).
webcrack's recovered tree feeds gitnexus; the semantic query answers
"find buildSignature's caller" with sendRequest — asserted by the script
against real output and recorded into its evidence JSON.

Degradation class: legs skip STRUCTURED (json status line), the script
still exits 0 so offline CI stays green; pytest asserts structured-skip +
self-check paths plus the committed golden query answer from the real run
(2026-08-26, see tests/fixtures/web751/evidence-demo.json).

## D6 — non-goals

- No new Python parser of gitnexus output in the repo (the MCP face already
  returns JSON; a wrapper parser would be speculative infrastructure —
  YAGNI until #760 defines the worker contract).
- No mcp_probe manifest change: web labs keeps the direct-npx supply
  philosophy (#728) — gitnexus MCP registration stays android-only HARD.
- No workspace-tool registration of the demo script in _INDEX.yaml (it is
  regression tooling, not a claim-facing capability provider; declared in
  release-manifest.yaml assets instead).
