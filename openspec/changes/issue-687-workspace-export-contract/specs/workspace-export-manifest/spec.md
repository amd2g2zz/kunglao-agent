## ADDED Requirements

### Requirement: manifest sha256 SHALL be the hash of the file's actual on-disk bytes

`scripts/kunglao_export.py::build_manifest` SHALL record, for every tracked file, a
`sha256` computed over the file's exact on-disk bytes (binary read, no text decoding,
no newline normalization). This is the integrity contract that `verify_manifest`
relies on: it re-hashes the archived bytes — which are the same on-disk bytes — and
compares against the manifest value.

Test-side corollary (the #687 ruling): a test that locks this contract SHALL
materialize the fixture with `write_bytes` (exact bytes, platform-independent) and
SHALL derive the expected digest from those same input bytes. Writing the fixture
with `write_text` (whose `newline=None` default translates `\n` to `os.linesep` on
Windows) while expecting the LF digest is a platform-brittle expectation, not a
production defect.

#### Scenario: LF bytes on disk

- **WHEN** a carrier file's on-disk bytes are exactly `b'{"x": 1}\n'`
- **THEN** its manifest entry's `sha256` equals `sha256(b'{"x": 1}\n')`

#### Scenario: CRLF bytes on disk

- **WHEN** a carrier file's on-disk bytes are exactly `b'{"x": 1}\r\n'` (e.g. a
  Windows-authored file)
- **THEN** its manifest entry's `sha256` equals `sha256(b'{"x": 1}\r\n')` — the
  actual bytes, NOT the LF-normalized digest. A normalize-then-hash implementation
  fails this scenario.
