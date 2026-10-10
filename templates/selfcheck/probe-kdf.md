<!-- probe shape: kdf (static-constant) — injected for family arm-native-kdf -->

STATIC-CONSTANT PROBE (kdf family) — run before finalizing:

1. List every required constant NAME the deliverable contract demands
   (the static face: the checker looks for these names in the candidate
   source).
2. Check your candidate source defines each required constant name —
   derived from the target's algorithm, never a literal copied from
   somewhere else.
3. Sanity-execute the candidate's derivation path once in-process:
   load/initialize it, run its derivation entry on a benign input from
   the task material, and confirm it returns without error and yields a
   well-formed value.
4. PASS requires: all required constant names present AND the derivation
   path executes clean. A missing name or a crashed derivation = the
   candidate is not deliverable — fix before finalizing.

Declare the result before finalizing:
`SELF_CHECK RESULT: static-constant <names-present>/<required> exec=ok|crash — PASS|FAIL`
