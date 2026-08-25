# Design: #687 last-red triage — manifest sha256 fidelity

## D1 — Evidence chain (reproduce commands, Windows host, b2b3661)

```
$ uv run python -m pytest tests/test_workspace_export_540.py -q
1 failed, 30 passed
FAILED ...::test_manifest_sha256_is_actual
  assert '9aa6411a443b...e8982' == '936353965b4b...fbd4'   # left=manifest, right=test literal

$ uv run python -c "import hashlib; \
  print(hashlib.sha256(b'{\"x\": 1}\n').hexdigest()); \
  print(hashlib.sha256(b'{\"x\": 1}\r\n').hexdigest())"
936353965b4ba9180e3acb781d81aa634390ac95fd2874a9cbc4c4846b49fbd4   # LF  == test literal
9aa6411a443b89fd9eec51a038ba7cee16d9a19b55e2ff68c34eb329af6e8982   # CRLF == manifest value
```

Conclusion: manifest sha256 == sha256(actual on-disk bytes). Production faithful.

## D2 — Why the disk bytes are CRLF on Windows

`Path.write_text(data, encoding="utf-8")` opens with the default `newline=None`;
on write, `\n` is translated to `os.linesep` (`\r\n` on Windows). The fixture itself
materialized CRLF; the expectation literal assumed LF. The same test passes on Linux
CI, which is why #540's original 31-test lock stayed green there and only surfaced on
a Windows host run.

## D3 — Why this is NOT a production regression

- `sha256_file()` opens the file `"rb"` and streams chunks — no text decoding, no
  normalization path exists in the module.
- End-to-end consistency proof: `export_workspace` archives disk bytes via `tar.add`;
  `verify_manifest` re-hashes archived bytes and compares against the manifest hash;
  the roundtrip tests and the tamper-detection test are green. If production hashed
  anything other than actual bytes, roundtrip/tamper would fail — they don't.
- Contract direction: manifest sha256 exists for round-trip integrity of the archive,
  so it MUST be the hash of the bytes that get archived (actual disk bytes) — exactly
  what production does.

## D4 — Fix decision

| option | verdict |
|---|---|
| change `sha256_file` to normalize newlines before hashing | REJECTED — would break roundtrip verify (archived bytes are not normalized) and betray the integrity contract |
| change expectation to `hashlib.sha256(file.read_bytes())` | REJECTED as sole fix — becomes near-tautological (same read path both sides) and pins nothing |
| **pin fixture bytes with `write_bytes`, derive expectation from that one literal** | ADOPTED — platform-independent materialization; expectation derived from input (numeric-fidelity: no second hash literal) |
| add CRLF param variant expecting sha256(CRLF bytes) | ADOPTED — locks "hash actual bytes, never normalized text" against a future normalize-then-hash regression |

## D5 — RED/GREEN bookkeeping under a test-stale ruling

The task card's default RED step ("write a new derived test, watch it fail first")
assumes production is wrong. D1-D3 show production is faithful, so no derived
assertion can be red against it. RED evidence for this card is therefore the
b2b3661 failing run itself (D1, captured verbatim); GREEN is the re-derived test
passing on all platforms plus the new CRLF contract lock. Recorded here so the
missing "new red" is a documented consequence of the ruling, not an omission.

## D6 — Reconciliation of "8 reds" vs the 9 test IDs in the issue body

The issue body lists 9 failing test IDs under an "8 failures" heading. On b2b3661
all 9 pass except sha256. Pre-#685 enumeration is captured in the issue comment
(worktree at b2b3661^) to name exactly which were red and which root cause fixed
each — no guessing.
