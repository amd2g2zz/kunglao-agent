# Proposal: workspace_export manifest sha256 fidelity — triage ruling for the last red of 8 (#687)

## Scope (reduced card 3)

Issue #687 originally reported 8 test failures in `tests/test_workspace_export_540.py`.
PR #685 (b2b3661, "restore green release-check CI — 10 root-cause classes") already
fixed 7 of them via two production changes in `scripts/kunglao_export.py`:

- `classify()` platform-stability: `rel = path.as_posix()` + scratch check restricted
  to relative paths → fixes the 5 classify-routing reds and the scratch-exclusion red.
- `verify_manifest()` skipping the never-archived `"other"` zone → fixes the 2
  roundtrip-verify reds.

This card triages and resolves the single remaining red:

```
FAILED tests/test_workspace_export_540.py::test_manifest_sha256_is_actual
AssertionError: assert '9aa6411a443b...eb329af6e8982' == '936353965b4b...4c4846b49fbd4'
```

## Triage ruling: test stale (platform-brittle expectation) — NOT a production regression

Byte-level evidence (Windows host, b2b3661):

| quantity | value |
|---|---|
| `sha256(b'{"x": 1}\n')` (LF literal the test hashed) | `936353965b4ba9180e3acb781d81aa634390ac95fd2874a9cbc4c4846b49fbd4` |
| `sha256(b'{"x": 1}\r\n')` (actual disk bytes) | `9aa6411a443b89fd9eec51a038ba7cee16d9a19b55e2ff68c34eb329af6e8982` |
| manifest records | `9aa6411a...` — the ACTUAL disk bytes |

Root cause: the fixture wrote the file with
`(ws / ".mcp.json").write_text('{"x": 1}\n', encoding="utf-8")`. `write_text` opens
with `newline=None`, so on Windows `\n` is translated to `\r\n` — the on-disk bytes are
`{"x": 1}\r\n`. Production `sha256_file()` reads `"rb"` and faithfully hashes those
actual bytes. The test's expectation hardcoded the LF-only assumption (its own comment
`# sha256 of {"x": 1}\n`), so the assertion compares the CRLF hash against the LF hash.

Production is faithful: `test_export_verify_roundtrip_default`,
`test_export_verify_roundtrip_include_scratch`, and `test_verify_detects_tampered_file`
all pass — the manifest hash, the archived bytes, and verify's re-hash are one
consistent chain over actual bytes.

## Solution (test-side only)

1. Fixture pins exact on-disk bytes with `write_bytes` (no newline translation, any
   platform).
2. Expectation is derived from the same single input literal
   (`hashlib.sha256(on_disk_bytes).hexdigest()`) — no second hardcoded hash literal
   (numeric-fidelity: one literal, expectation derived).
3. A CRLF variant is added to lock the contract in the other direction: the manifest
   MUST hash the actual bytes, never newline-normalized text — catching a hypothetical
   future "normalize-then-hash" regression.

No changes to `scripts/kunglao_export.py`.

## Out of scope

- The 7 reds already fixed by #685 (verified green on b2b3661, not re-fixed here).
- Any production change to the export/verify pipeline.

## Acceptance

- [x] Triage conclusion recorded per failure (issue comment carries the full table).
- [x] Stale test updated with derived expectation + ruling rationale in-code.
- [x] Full file green (was 30 passed / 1 failed → all passed after fix).
- [x] `uv run python devkit/quality_gates.py` adds no failures outside the known
      ledger.
