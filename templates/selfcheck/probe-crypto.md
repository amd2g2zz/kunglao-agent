<!-- probe shape: crypto (pair-match) — injected for family mod-crypto-native -->

PAIR-MATCH PROBE (crypto family) — run before finalizing:

1. Collect the published input pairs from the task material (payload →
   expected output rows that ship with the workspace).
2. Drive YOUR candidate module with each published payload exactly as
   the task contract specifies (same lane/parameter handling).
3. Compare candidate output vs expected output on every published pair —
   full-string or byte-exact, never "looks right".
4. PASS requires EVERY pair to reproduce. One mismatch = the candidate
   is wrong (typically a planted non-standard constant or a
   stock-algorithm default leaking through) — go back and re-derive.

Declare the result before finalizing:
`SELF_CHECK RESULT: pair-match <matched>/<total> — PASS|FAIL`
