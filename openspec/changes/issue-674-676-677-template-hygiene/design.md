# design — issue-674-676-677-template-hygiene

## D1 — the deploy manifest is a RECEIPT, not a third version file

`template_version`'s "no third version file" rule bans hand-maintained
version assets (they drift from the receipt-checked pair). The deployed
copy's sibling `deployed-manifest.json` is not that: `source_version` is
minted BY the deploy machinery from the receipt-checked source
(`deploy_manifest._source_version()` calls this very function), so
reading it back is a receipt lookup — nothing hand-maintained, no drift
surface. Resolution chain: `pyproject.toml` → `.claude-plugin/plugin.json`
→ `deployed-manifest.json:source_version` → raise. Precedence guarantees
the skill tree never notices the new arm (the repo root has no
`deployed-manifest.json`); an unreadable/versionless carrier warns once
(fail-open) and falls through to the unchanged guard.

## D2 — the terminal-claim seam has ONE owner: the detector

Two candidate fixes were on the table (the issue lists them as
complementary, pick one):

- (a) renderer: render terminal claims in a trailing settled section;
- (b) detector: exempt TERMINAL statuses from `ORPHAN_CLAIM`.

(b) is taken:

1. The rendered face's contract is "open thread = latest next per claim
   line" — a settled claim has no open thread, and a settled section
   would change what every consumer of `global_plan.txt` reads as the
   plan (resume, plan stages, reviser, budget sinks).
2. `ORPHAN_CLAIM` exists to catch "mid-iteration discovery not logged";
   a terminal claim is by definition not mid-iteration frontier — the
   exemption cannot hide live work, and the reality-check class
   (`UNVERIFIED_EVIDENCE`) still audits PROVEN claims independently.
3. Blast radius: no existing test pins `ORPHAN_CLAIM` for a terminal
   claim (every fixture uses OPEN), so the exemption breaks nothing
   while the renderer change would alter every rendered plan.

(a) remains recorded as the complementary option if the owner later
wants the face to be a complete claim map; it is deliberately NOT taken
in this change.

## D3 — header preservation is capture-and-reprepend, not a re-stamp

`ws_yaml` keeps its single-writer purity: capture the maximal run of
leading `#` lines before `safe_load`, re-prepend it verbatim after
`safe_dump` (the round-trip refusal stays body-only, byte-identical to
before). The stamp VALUE recovery chain from the previous fix is kept
for headers that lack the stamp (file → same-dir `CLAUDE.md` for the
register → active skill version). Calling `stamp_workspace` post-write
was rejected: it would re-stamp every carrier from a register write
(side-effect fan-out) and would still not preserve `[initialized]`.

## D4 — touched-file complexity ratchet cleared in the same change

`ws_yaml.main` already failed `C901` (16 > 12) before this change — a
pre-existing red on the exact validation command. The repo ratchet
("grandfathered … cleared as files are touched") plus the mandate to
leave the validation green forced a behavior-preserving split: the
mutate phase moves into `_mutate` / `_apply_append` (return-code
contract: `None` = mutated-and-write, `0` = done without write, other
int = exit code; `KeyError` still maps to exit 5 in `main`). The 51-test
register-writer suite plus the new regression tests pin parity.

## D5 — three deltas, one validate

Three spec deltas register under the change;
`openspec validate issue-674-676-677-template-hygiene` must exit 0
(the three-registrations discipline). Tests cite issues by design (test
trees are exempt from the production-code narration bans); production
comments stay narration-free per the formal-code owner ruling.
