# bug(v0.1.4): kunglao-verify expected rewriteable after FAIL — F3 covers tautology only (#828)

Child of #825.

## Why

`scripts/kunglao_verify.py:282-283` (F3 `check_expected_anchor_source`) rejects only the **tautology** case (producing script embedding expected). It does not protect against the *sequential rewrite*: maker runs verify → L1 FAIL (sha256 mismatch) → maker edits `expected:`/`actual:` in the fact frontmatter to the observed output → re-runs verify → PASS.

Incident timeline (workspace file mtimes):

- F008: verify FAIL → **8 seconds later** `expected_sha256` rewritten to the observed value → L1=PASS overall=VERIFIED
- F017: 7 consecutive REJECTED iterations, then expected aligned to actual output by hand → PASS

Both flips passed with no gate noticing that `expected` changed *after* a FAIL was recorded. The verify json history (89 files in the incident) contains the FAIL→PASS transitions but nothing reads them as a signal.

## What Changes

- `kunglao_verify.py`: persist per-fact verify history fingerprint (hash of `expected`) inside each `runs/verify-<fid>-*.json`; a new run raises ERROR when the expected-hash differs from the last recorded one AND the last verdict was FAIL (rewrite-after-fail pattern), unless the fact carries an explicit correction note (supersedes semantics).
- L1 must anchor expected to an **independently derivable** value (byte sha256 of an input artifact), never to a copy of the script's own output.