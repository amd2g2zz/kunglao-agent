# Design — issue-692-constraint-witness

## 1. Where the witness lives

The issue sketches `constraint_witness:` inside an oracle case file. The
repo's oracle case files (`oracle/cases/*.yaml`) are minted per-workspace by
the admission pipeline, but the counterexamples they must witness are
declared once in `<ws>/goal-operationalization.yaml` — the constitution
document. Binding the witnesses there keeps one source of truth:

- the lint (intake) can enforce coverage mechanically against the exact
  `not_done` strings (1:1 key binding, rewording already refused post-dispatch);
- the constitution freeze extends to the witness block with no new
  machinery (it freezes with the lists);
- the ORACLE checkpoint reads the same document it already writes at
  C6-pre.

The block carries its own schema id (`constraint-witness/1`) so a foreign
shape is refused instead of half-read.

```yaml
constraint_witness:
  schema: constraint-witness/1
  witnesses:
    "<exact not_done row>":
      check: "test ! -e browser.dep"   # exit 0 = constraint holds
    "<other exact not_done row>":
      none: "reason no mechanical probe separates this row"
```

## 2. Spec shape rules (lint R6)

- `not_done` empty → R1 already refuses; R6 stays silent (no orphan sweep).
- no block / foreign schema / `witnesses` not a mapping → refused.
- each row: present key, spec is a mapping, exactly one of `check` /
  `none` with a non-empty string, no unknown keys.
- keys not bound to a declared row → refused (witnesses bind 1:1).

Placement: `_witness_errors()` feeds `_content_errors()`, so the refusal
rides the existing exit-1 path of `main()`, `stamp_dispatch()` and
`convergence_check`'s `_goal_op.validate` (every decide re-reads it — an
agent cannot dodge the lint by editing the file after intake; the edit
makes the workspace fail-closed at the next decide).

## 3. Constitution freeze

`stamp_dispatch` copies `witness_map(doc)` (deep) into
`constitution.constraint_witness`. `_constitution_errors` refuses any
post-dispatch change to a frozen row: removal of the whole block, removal
of a row's spec, or a spec change (notably `check:` → `none:`, which would
silently un-witness a row). New rows appended post-dispatch are legal
(their `not_done` append already surfaces as a re-scope record) as long as
they carry their own witnesses.

## 4. Joint verdict at the ORACLE checkpoint

`checkpoint_oracle` already computes the outcome leg
(VERDICT PASS + rc 0 + pair ratio + contamination). It now evaluates the
witness block and ends with:

```
status = constraint_witness.joint(status, witness["status"])
```

`joint` truth table: FAIL if either side is FAIL; outcome PASS + witness
PASS or UNDECLARED → PASS; otherwise the outcome status passes through.
Only the witness leg can add a red, never remove one.

## 5. Fail-open + warn (the settlement posture)

| posture | result | why |
|---|---|---|
| no goal-op file / unreadable | UNDECLARED + warn | pre-contract workspace; intake gate owns refusal |
| no `constraint_witness` block | UNDECLARED + warn | same — convergence decide still blocks dispatch of an invalid document |
| `not_done` empty (draft) | UNDECLARED + warn | R1's refusal is intake-side |
| spec malformed for a row | entry `error` + warn | never a silent pass, never a red for a declaration defect the lint already refuses |
| check spawn error / timeout / rc -1 | entry `error` + warn | an unrunnable probe is not evidence of violation |
| check ran, rc != 0 | **violation → FAIL** | the only witness-side red |

Rationale: red-at-the-oracle must mean "the deliverable violates a
counterexample", not "the harness tripped over itself". The defense
against gaming (deleting the block) is the intake/decide lint, which is
fail-closed, not this read face.

## 6. Check execution contract

`sh -c "<check>"`, `cwd = <ws>`, with `KUNGLAO_WS` / `KUNGLAO_REPO`
exported inside the command string (runner-agnostic — the checkpoint's
injected `ctx.cmd` seam takes no env). Default runner: local
`subprocess.run` with a 60 s hard timeout. rc 0 = holds; any other rc
(0-255) = violation; rc -1 / `timed_out` = errored (fail-open). Witness
checks are therefore plain shell probes over the delivered workspace —
the issue's `forbid_runtime_deps` class becomes e.g.
`! grep -rq playwright artifacts/ tools/` or a dependency-free
re-execution probe.

## 7. Test strategy

`tests/test_constraint_witness_692.py` (targeted, three faces):

1. degraded solution + green outcome → evaluate FAIL → joint FAIL;
2. lint refusal: no block / partial coverage exit non-zero, full coverage
   (check + none) exits zero, stamp refuses the bare document;
3. joint truth table + fail-open UNDECLARED postures (missing file,
   blockless document) with warnings recorded.

Fixture fallout is folded into the existing contract tests
(goal-operationalization fixtures, declared-coverage builder, heartbeat
teardown workspace) — those documents gain witness blocks so their
semantics (valid/converged) are preserved.

## 8. Residuals (disclosed)

- The production reward channel (`oracle_cadence` → posteriors) prices
  case outcomes only; wiring a status-level witness composition there is a
  follow-up card.
- `restatement()` does not yet print witness coverage; the delivery receipt
  restates the `not_done` list as before.
