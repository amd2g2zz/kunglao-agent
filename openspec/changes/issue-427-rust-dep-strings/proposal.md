# Absorb (independent): rust-dep-strings — Rust crate dependency-string extraction (#427)

## Why

Issue #427 (milestone v0.1.2, 吸收件, 三档判定: **独立**): Rust binaries
embed cargo registry path strings (`.cargo/registry/src/<registry-id>/<crate>-<version>/…`)
that directly name every statically-linked crate dependency — for a Rust
malware sample this is a first-class attribution/dependency surface. The
toolshelf has no equivalent: `go-buildinfo-carve` targets the Go buildinfo
blob (different mechanism, Go-only); nothing covers Rust.

Source asset: `ghidra_scripts/RustDependencyStrings.py`
(Ghidra community script by Matt Ehrnschwender, @category Search). Its data
asset — the `.cargo(/|\)registry(/|\)src(/|\).*?-[a-f0-9]{16}(/|\)(crate-ver)`
regex — is absorbed **with attribution**; everything else (CLI contract,
dual-channel scan, anti-cross-section parsing) is self-built to the
kunglao toolshelf conventions.

## What Changes

- **New tool** `tools/static/rust-dep-strings.py` (kebab-case, homed beside
  `go-buildinfo-carve.py`, same `common.py` plumbing):
  - **Channel `registry`**: cargo registry path/URL patterns —
    `registry[/\](src|cache|index)[/\]<registry-id>[/\]<crate>-<version>`
    (registry id = `<host>-<16hex>`, e.g. `index.crates.io-6f17d22bba15001f`,
    `github.com-1ecc6299db9ec823`), plus bare registry ids and
    `registry+<scheme>://…` source-replacement URLs.
  - **Channel `crate`**: standalone `crate-name-<semver>` strings
    (`name-\d+\.\d+\.\d+` with plausible crate charset).
  - Output: crate name + version + source channel per hit; `--json` single
    object; `--reproduce` field=value; default one line per result; exit
    0 found / 1 negative / 2 error.
  - Implementation drops the original's whole-section `readAllBytes` +
    printable-filter + concat read (it can join non-adjacent sections into
    fake matches): raw-byte marker find + bounded window + post-hit
    backtrack extraction instead.
- **Registration**: `tools/_INDEX.yaml` entry, `tools/_index-static.md`
  contract entry (6 segments) + catalog row, `tools/static/README.md`
  absorption row (16→17 tools), pin updates in
  `tests/test_tool_search.py` (28→29 / cheap 25→26) and
  `tests/test_index_docs_contract.py` (28→29).
- **References**: one-line mention in the Rust-Specific Analysis Tools
  section of `references/re-library/languages-compiled.md` (+ digest re-pin
  in `references/_INDEX.yaml`).
- **Tests**: `tests/test_rust_dep_strings.py` — synthetic fixtures only
  (no real samples): path-separator variants, 16-hex registry ids,
  prerelease version tails, standalone crate strings, channel filter,
  anti-cross-section rejection, plain-binary zero-false-positive, full CLI
  contract (rc / JSON keys / reproduce / negative).

## Impact

| File | Change |
|---|---|
| `tools/static/rust-dep-strings.py` | new (absorption, attributed) |
| `tools/_INDEX.yaml` | +1 entry (29 total) |
| `tools/_index-static.md` | +catalog row, +6-segment contract entry |
| `tools/static/README.md` | absorption row, tool count 16→17 |
| `tests/test_tool_search.py` | count pins 28→29, cheap 25→26 |
| `tests/test_index_docs_contract.py` | registry count 28→29 |
| `tests/test_rust_dep_strings.py` | new contract + behavior tests |
| `references/re-library/languages-compiled.md` | Rust tools section mention |
| `references/_INDEX.yaml` | digest re-pin for the edited reference |

Constraints honored: pure local read-only analysis (no network, no sample
execution); synthetic fixtures only; no real-sample bytes enter the repo.
