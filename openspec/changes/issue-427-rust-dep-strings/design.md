# Design — rust-dep-strings (#427)

## D1. Location & style mirror

`tools/static/rust-dep-strings.py`, kebab-case like its siblings
(`go-buildinfo-carve.py`), importing the category's single shared module
`common.py` (`add_common_flags` / `read_bytes` / `report` / `negative` /
`sha256`) — the #277 CLI contract and #340 one-shared-module rule both stay
intact. UTF-8 stdout guard block copied verbatim from
`go-buildinfo-carve.py` (mechanically pinned by
`tests/test_utf8_stdout_convention.py`).

The issue text mentions the repo path as `tools/static/rust-dep-strings.py`;
the dispatch prompt's `scripts/re/rust_dep_strings.py` spelling conflates the
per-engagement *workspace* RE-tool namespace (`scripts/re/**` — see
devkit/subagent_review.py legal citation classes) with the repo toolshelf.
The repo-side authority (issue + tools/README structure rule #2: every
registered tool's .py lives in `tools/<category>/`) wins.

## D2. Dual-channel model (dispatch requirement)

Per-hit `channel` field, selectable via `--channels registry,crate`:

- **`registry`** — high-confidence, cargo-structural evidence:
  1. `registry[/\](src|cache|index)[/\]<registry-id>[/\][<crate>-<version>…]`
     paths. Registry id = `<host>-<16hex>`; canonical ids:
     `index.crates.io-6f17d22bba15001f` (sparse crates.io),
     `github.com-1ecc6299db9ec823` (git crates.io-index). `src` kind yields
     crate+version; `cache` kind yields `<crate>-<version>.crate`.
  2. Bare registry ids appearing without a crate tail (still Rust evidence;
     listed under `registry_ids`, no crate row).
  3. `registry+<scheme>://…` SourceId URLs (cargo source replacement).
- **`crate`** — standalone `crate-name-<semver>` byte strings with a
  plausible crate charset (`[a-z][a-z0-9_-]{0,63}`), version
  `\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?` (prerelease/build tails kept).
  Offsets already inside a registry-path hit are excluded (a crate row
  merges both channels instead).

Crates are deduped by `(name, version)`; merged rows carry
`channels: [...]`, up to 32 `offsets` (`offsets_capped: true` beyond).

## D3. Anti-cross-section parsing (issue 实现要点)

The absorbed Ghidra script concatenates every RW section's printable bytes
into one string then regexes it — two far-apart sections can be joined into
a match that exists in neither (跨段误报). Replacement, mirroring
`go-buildinfo-carve`'s marker+window style:

1. `data.find(b"registry")` marker walk (raw bytes — any regex match over
   the buffer is byte-contiguous by construction, no concat step exists);
2. within a ≤16-byte window after each marker, require `[/\](src|cache|index)[/\]`;
3. read the registry id as a bounded token (≤80 bytes, charset-checked);
4. **backtrack-extract** the crate-version component with an anchored
   regex over a bounded tail window (≤120 bytes) — a tail without a
   valid `<name>-<semver>` start is rejected (no partial crate), which is
   the pinned rejection behavior tested at RED.

## D4. Output / exit contract (#277)

- default text: one line per crate —
  `off=0x.. crate=<name> version=<ver> channels=<a,b> registry=<id|->`
- `--json`: single object `{tool, input_sha256, channels, total, crates[],
  registry_ids[], registry_sources[]}`
- `--reproduce`: `tool / input_sha256 / total / first_crate /
  first_version / first_channel` field=value lines (kunglao L1 gate format)
- exit `0` ≥1 crate or registry hit, `1` negative (scanned, nothing found;
  `negative()` → status=NEGATIVE), `2` error (bad args / unreadable input,
  structured JSON on stderr with guidance).

## D5. Registration surfaces (issue 变更范围)

1. `tools/_INDEX.yaml`: `rust-dep-strings` / static / `static:rust-dep-strings`
   / T1 / cheap / input_output / description (15-40 chars) / when_not.
2. `tools/_index-static.md`: catalog row + 6-segment `### rust-dep-strings`
   entry (Purpose/Usage/Inputs/Outputs/exit code/when_not, fixed order).
3. `tools/static/README.md`: absorption-history row + count 16→17.
4. Pins: `tests/test_tool_search.py` (T1 28→29, cost-max-cheap 25→26,
   docstring counts), `tests/test_index_docs_contract.py` (28→29).
5. `references/re-library/languages-compiled.md` Rust-Specific Analysis
   Tools mention + `references/_INDEX.yaml` sha256 re-pin (guarded by
   `tests/test_replay_gate.py::test_references_index_pins_all_reference_files`).
6. `tools/validate_index.py` must pass (29 tools).

## Attribution (issue 署名 requirement)

Docstring names the source script path and author (Matt Ehrnschwender);
the registry-path regex carries a provenance comment marking it as the
absorbed data asset (adapted from single-path to marker+window form).
Sample-specific values from the source are not carried over.

## Risks

| R | Risk | Mitigation |
|---|---|---|
| R1 | channel `crate` false positives on non-Rust binaries (`foo-1.2.3` strings are legal in any binary) | channel labeled per hit; registry channel is the authoritative source; negative fixture pins zero hits on a plain binary; `--channels registry` escape hatch |
| R2 | registry-path regex misses exotic registries (self-hosted, cloudsmith) | id charset is generic `<host>-<16hex>`, not an allowlist; unknown hosts still match |
| R3 | prerelease tails (`0.9.0-alpha.1`) mis-split | version regex keeps `[-+…]` tails; RED fixture pins `rand_core-0.9.0-alpha.1` |
| R4 | digest drift in references/_INDEX.yaml | re-pin computed and committed in the same change; replay-gate run at GREEN |
