<!-- probe shape: sign (sign-verify) — injected for family req-sign -->

SIGN-VERIFY PROBE (sign family) — run before finalizing:

1. Take the published (message, expected signature or expected
   verify-result) material that ships with the workspace.
2. Run YOUR candidate's sign/verify path over the published message.
3. Verify: the produced signature matches the expected signature
   byte-exact, or the verify decision reproduces the expected decision —
   whichever face the task contract specifies.
4. PASS requires every published case to reproduce. A mismatch usually
   means the wrong key-derivation order, padding, or encoding — go back
   and re-derive from the raw target material.

Declare the result before finalizing:
`SELF_CHECK RESULT: sign-verify <matched>/<total> — PASS|FAIL`
