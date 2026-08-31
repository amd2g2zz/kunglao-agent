## ADDED Requirements

### Requirement: write_guard payload read SHALL decode bytes through a charset chain and never raise

`hooks/write_guard.py::_read_payload` MUST read stdin as bytes (`sys.stdin.buffer.read()`, falling back to the text layer only when no buffer exists) and decode through the chain `utf-8` (strict) → `locale.getpreferredencoding(False)` (strict) → `utf-8` with `errors="replace"`. The function MUST NOT let a decoding failure surface as an empty payload on a carrier-writing tool call: with non-empty stdin bytes, the decode result — exact or replacement-degraded — MUST be handed to the JSON parser, and only a JSON parse failure (or empty stdin) degrades to `{}`.

#### Scenario: locale-encoded non-ASCII payload (the #686 failing shape)

- **WHEN** the parent encodes the payload JSON with the host locale (`cp936`) and the payload contains a non-ASCII character (e.g. U+2014 em-dash, GBK `0xA1 0xAA`), while the child runs with `PYTHONIOENCODING=utf-8`
- **THEN** the strict UTF-8 decode fails, the locale decode succeeds, the payload parses intact, and the write is adjudicated normally (must-block shapes return `rc=2`; clean shapes return `rc=0`) — the hook no longer returns `rc=0` with empty stderr on a must-block payload.

#### Scenario: genuine Claude Code payload

- **WHEN** stdin bytes are valid UTF-8 JSON
- **THEN** the first chain step decodes them and behavior is byte-identical to pre-#686.

#### Scenario: neither charset fits

- **WHEN** the bytes decode under neither UTF-8 nor the host locale
- **THEN** the replacement decode runs; if the JSON structure survives, the write is adjudicated on its structural fields; if not, `_read_payload` returns `{}` and the documented allow-on-unparseable contract applies.

#### Scenario: non-dict JSON

- **WHEN** stdin parses to a list or scalar
- **THEN** `_read_payload` returns `{}` (allow as "not a file-writing tool call") instead of crashing `main()` with `AttributeError`.

### Requirement: `KUNGLAO_WG_DEBUG=1` SHALL expose the decision trace

With the environment variable `KUNGLAO_WG_DEBUG=1` set, `hooks/write_guard.py` MUST write `wg-debug:`-prefixed lines to stderr at each `main()` decision point (payload decoded + charset used, resolved workspace, carrier, post-image reconstruction, per-leg adjudication counts, final decision) so that an enforcement failure can be localized without out-of-tree drivers. With the variable unset, stderr output MUST be byte-identical to the pre-#686 contract (block reasons only).

### Requirement: the 7 must-block payload shapes SHALL be pinned by a permanent subprocess suite

`tests/test_write_guard_686.py` MUST exercise, through the subprocess-stdin harness (real `python hooks/write_guard.py` child, `PYTHONIOENCODING=utf-8`), one parameterized case per issue-listed failure — R1 verifier==producer PROVEN, W-2 invented status, unresolvable-workspace carrier fail-closed, block-lands-in-kunglao_log, chainless same-claim correction, supersedes-with-inherited-passes, supersedes-at-nonexistent-note — asserting `rc=2` each, plus allow guards (schema-clean em-dash fact write and a non-carrier write, both `rc=0`) so a degenerate always-block fix cannot pass. The must-block payloads MUST retain their non-ASCII characters: they are the trigger class of the #686 regression.

#### Scenario: regression re-introduced

- **WHEN** `_read_payload` again converts a decoding failure into an empty payload
- **THEN** at least the 7 must-block cases fail with `rc=0`, keeping the enforcement layer from silently dying again.
