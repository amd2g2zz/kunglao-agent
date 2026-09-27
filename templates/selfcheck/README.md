# templates/selfcheck — per-family candidate self-check probe patterns

The EXP-8 I3 injection source. When a task unit's `family` has a
registered probe shape in `scripts/eval_loop_runner.py`
(`FAMILY_PROBE_SHAPES`: `mod-crypto-native` → crypto,
`arm-native-kdf` → kdf, `req-sign` → sign), the loop runner injects the
matching snippet below into the session's task prompt as the
`SELF_CHECK:` block. The session is expected to run the pattern against
its own candidate BEFORE finalizing.

Evidence (EXP-8 card): mod-crypto-l1 delivered a candidate graded 0/20 —
a wrong deliverable that an in-session probe would have caught.

Rules for these snippets:

- Generic pattern only: they name NO ground truth, no digests, no
  expected outputs. The task material already in the workspace carries
  whatever concrete values the probe needs (published pairs, static
  faces).
- Fail-loud: every snippet ends in a PASS/FAIL declaration — a probe the
  candidate fails means the candidate is not a deliverable yet.
- Zero dependencies: runnable with the task's own toolchain in the
  workspace.

Files:

| file            | shape | applies to (family)   |
|-----------------|-------|-----------------------|
| `probe-crypto.md` | pair-match probe | `mod-crypto-native` |
| `probe-kdf.md`    | static-constant probe | `arm-native-kdf` |
| `probe-sign.md`   | sign-verify probe | `req-sign` |

Unregistered families get no block. Extending the map requires a new
snippet here plus the map entry — both reviewed together.
