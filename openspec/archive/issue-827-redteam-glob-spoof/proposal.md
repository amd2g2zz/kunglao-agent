# bug(v0.1.4): plan_drift_detector UNVERIFIED_EVIDENCE spoofable by batch templates (#827)

Child of #825.

## Why

`scripts/plan_drift_detector.py:156-172` computes "covered" claim ids by:

```python
for p in runs_dir.glob("verify-redteam-*.md"):
    m = re.search(r"C-?\d+", p.name)
    if m:
        out.add(_normalize_cid(m.group(0)))
```

File **existence + claim-id in filename** is the entire check. The incident workspace defeated it with 8 byte-identical 2144-byte template files written in a 265ms single-burst (09:48:17.354 → .619), each substituting only the claim id. UNVERIFIED_EVIDENCE then reported zero findings and the dispatch gate unblocked.

`scripts/write_gate.py:229-236` (R1 md path) has the same shape: `fid in text and POSITIVE_VERDICT_RE.search(text)` — the templates contained "KEEP status: PROVEN" which matched the positive-verdict regex.

## What Changes

- Consume the dispatch ledger from #825 instead of the glob.
- Cheap hardening until the ledger lands: reject redteam-md files whose (a) mtime cluster shows ≥3 files within a 5s window with template-similar content (normalized-hash equality), or (b) body lacks the redteam agent template authorship header.
- `write_gate.py` R1 md path: same ledger requirement.