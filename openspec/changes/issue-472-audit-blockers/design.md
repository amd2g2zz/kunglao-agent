# design — issue-472-audit-blockers

> REV 2 — incorporates the adversarial design-review verdict (9
> defects: 2 HIGH pre-GREEN blockers, 4 MEDIUM design-text fixes,
> 3 LOW hygiene). Changes vs REV 1: `_safe_int` catches OverflowError
> (D-1); D5 names the source-text pin in test_notes_closure_762.py and
> prescribes the drift-guard transfer (D-2); D4 adds the coercion
> ordering rule + docstring amendments + reasons-before-sweep rule
> (D-3); D5 reconciles the registry header's self-contradiction (D-4);
> D5 uses a SEPARATE try/except for the ExitCode import (D-5); D2
> classifies the missing-file face (D-6); D1 documents the uncaged
> `_run_dispatch_act` test seam (D-7); D6 documents the error-text
> tradeoff + cage boundary (D-8); D2's warn op is the file's dotted
> convention `e2e.resolve_claims` (D-9).

## Context

The #472 audit's through-line is the non-silent evidence rule: every
failure lands in structured evidence at the moment it happens. All six
defects are the same disease at different seams — an exception path
that discards evidence, an `except` that restores state silently, or a
coercion that can raise inside a documented never-raise function. The
fixes are mechanical; the design questions are (a) what the caged
failure records must contain to stay honest, and (b) how far the
exit-1 registry resolution may go without touching emitted codes.

Blast radius (grep-based upstream sweep per symbol — the gitnexus MCP
face is not reachable from this session; index is stale at 39cd16f):

- `run_dispatch_parallel` — one caller (`checkpoints.py:592`,
  checkpoint_c6_loop) + test_e2e_runner.py wave tests. LOW.
- `_resolve_claims` — one caller (`checkpoints.py:391`). LOW.
- `read_retry_counter` — three in-module callers (:408/:434/:467) +
  tests. LOW.
- `kunglao_log.emit` / `e2e.audit.emit` — ubiquitous callers; the
  change only widens inputs that previously crashed. LOW.
- `ExitCode` / `HOOK_EXIT_SEMANTICS` — consumers: tests/
  test_hook_exit_codes.py, a comment in worker_pulse.py, AND the
  source-text pin `tests/test_notes_closure_762.py::
  test_noted_exit_code_is_five_and_documented` (asserts the substring
  `"EXIT_NOTES_DUE = 5"` in the shim's source — see D5). Additive. LOW.
- `run_pipeline` step loop — callers: scripts/e2e/cli.py + tests.
  Behavior changes only where a step raises (previously: unrecorded
  abort). LOW.

## D1 — Wave act cage (HIGH #1)

**Where.** `llm_faces.run_dispatch_parallel` + the prompt-file read in
`AutoLlmFace.run_dispatch`.

**Mechanics.**
- The collection loop maps each future back to its `(req, handle)`; a
  helper `_wave_act(face, req, handle)` wraps `face.run_dispatch` and
  is what gets submitted (and what the inline wave-of-one path calls),
  so the cage lives in ONE place:

```python
def _wave_act(face, req, handle) -> ActRecord:
    try:
        return face.run_dispatch(req, handle)
    except Exception as exc:   # the wave never loses an act (#472)
        audit.emit_dispatch_result(
            req.workspace, req.claim, mode=face.mode, rc=None,
            stderr_full=f"{type(exc).__name__}: {exc}",
            exit_null_reason="wave_act_exception")
        return ActRecord(req.claim, face.mode, "ERROR",
                         {"error": f"{type(exc).__name__}: {exc}",
                          "caged": "wave_act"})
```

- `as_completed` collection then cannot see an Exception from
  run_dispatch; the belt is a per-future try around `future.result()`
  (BaseException classes are deliberately NOT caged — KeyboardInterrupt
  must still propagate).
- The inline path (`len(launched) <= 1`) goes through the same helper:
  a wave of one is still a wave, and the common single-claim tick has
  the identical lose-everything failure today.

**Honesty details.**
- The synthesized record uses the EXISTING outcome vocabulary
  ("ERROR" is already in the ActRecord contract) — no vocabulary drift.
- `emit_dispatch_result` gains one additive kwarg
  `exit_null_reason="orchestrator_face_no_subprocess"` (default =
  today's literal): rc is None for a crashed act (there was no
  subprocess exit to report), and the null must be EXPLAINED — the
  issue-#880-era rule that a null is documented, never silent. The
  cage's reason distinguishes "crashed before any subprocess"
  (`wave_act_exception`) from the orchestrator face's legitimate
  no-subprocess null. Three `emit_dispatch_result` call sites exist
  (llm_faces :120/:199/:300); none passes the kwarg today —
  additive-safe by inspection.
- The prompt-file guard inside `AutoLlmFace.run_dispatch` catches
  `(OSError, UnicodeDecodeError)` on the read_text (the complete raise
  set of `Path.read_text`), emits the RESULT row with
  `exit_null_reason="prompt_file_unreadable"` + full stderr, and
  returns the ERROR ActRecord — the same shape the cage would
  produce, but with the precise cause (a cage hit on the auto face
  after this guard means something OTHER than the prompt read broke).

**Stated exception (review D-7).** `checkpoints._run_dispatch_act`
(:567) calls `ctx.face.run_dispatch` directly, OUTSIDE the wave. It is
the pre-#459 sequential seam with NO production caller (grep: only
`def` in scripts/ + test_e2e_runner.py test calls pin it); the
production dispatch path is `_dispatch_wave` → `run_dispatch_parallel`
(caged). It stays uncaged as a test seam — routing it through
`_wave_act` would import a private helper across modules for a seam
only tests exercise. The spec's "every dispatched act lands"
requirement is scoped to the wave (the production act path).

**Rejected alternatives.**
- Cage only `future.result()` (card-literal, no inline coverage):
  leaves the common single-act tick with the identical HIGH defect.
- Synthesizing a fake rc (e.g. rc=1): fabricates a subprocess exit that
  never existed; rc=None + explained null is the honest shape.
- Re-raising after recording: re-introduces the tick death; the cage's
  contract is "every act lands, the wave completes".

## D2 — _resolve_claims warn (HIGH #2)

**Where.** `checkpoints._resolve_claims` `except Exception` block.

- `kunglao_log.warn("e2e.resolve_claims", ...)` — the dotted
  `e2e.<face>` op convention of the file's only existing warn
  (`e2e.envelope_sampler` at :500); NOT the underscore form.
- checkpoints.py gains `import kunglao_log` (the e2e package already
  runs with scripts/ on sys.path — audit.py imports it the same way).
- Three faces, explicitly classified (review D-6):
  - spec-ABSENT (`not task_spec.is_file()`): silent defaults restore.
    An absent spec has no anchors to read — the documented anchors-
    absent fallback face, not corruption; warning here would re-create
    noise on a legitimate path. Implemented as an `is_file()` pre-check
    before the try (returns early, no warn, no exception involved).
  - spec-UNREADABLE (exists but read/parse raised, or the parsed doc
    is not a mapping) → warn with the face-specific reason: the
    `except Exception` branch carries
    `spec unreadable, defaults restored: {ExcType}: {exc}`; the
    non-dict branch (:100-105) carries
    `spec not a mapping ({type}), defaults restored`.
  - anchors-ABSENT (parses, IS a mapping, but goal_verbatim is empty)
    → silent stays legitimate: the py-derive default fallback is the
    documented #456 behavior for anchor-less units.
- `warn` never raises and never changes the return (None) — zero
  behavioral delta beyond the trace.

## D3 — Retry-counter warn (MEDIUM #3)

- `warn('retry_counter_read', f'{type(exc).__name__}: {exc}')` in the
  `except Exception` of `read_retry_counter`. Rate limiting is
  kunglao_log.warn's own per-(op, reason) process-wide dedupe — the
  established issue-275 batch-3 idiom; no new mechanism. The op name
  matches its write-siblings' convention (`record_retry`,
  `retry_counter_write`).
- Fail-open `{}` return unchanged (a corrupt counter must not break the
  gate; the warn is the trace, not a behavior change).
- The per-entry `int()` skip (:367-371) and non-dict `counters` shape
  (:363-365) stay silent: they degrade individual entries, not the
  whole-counter read; the audit names the parse-failure face only.

## D4 — _safe_int at the emit sites (MEDIUM #4)

```python
def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None
```

- `OverflowError` is load-bearing (review D-1): `int(float('inf'))`
  raises OverflowError — an ArithmeticError, NOT a ValueError subclass
  — so without it `duration_ms=float('inf')` still raises inside the
  never-raise contract. (nan → ValueError, already covered.)
- Defined once in `kunglao_log.py`; `e2e/audit.py` reaches it as
  `kunglao_log._safe_int` (already imports the module).
- Applied to duration_ms / exit / epoch at BOTH event dicts
  (kunglao_log :538-542 and the audit.py twin :180-184).
- **Coercion ordering rule (review D-3, MUST NOT be violated):**
  `_safe_int` applies ONLY at the event-dict coercion sites — i.e.
  AFTER `_resolve_epoch` has run (kunglao_log :526) / after the
  internal `cur_tick` read (audit.py). Coercing BEFORE `_resolve_epoch`
  would convert a garbage explicit epoch to None, which the inheritance
  contract then re-fills with the workspace tick — a fabricated axis —
  and the staleness-prune sweep (:561-562) would delete the
  `value_unparseable` reason, silencing the trace. The test pin
  (`epoch=[1]` → null + reason, NOT the inherited tick) makes the
  ordering violation red.
- Honesty: when a non-None input coerces to None, the field's null is
  explained — `reasons[field] = "value_unparseable"` (the #58 S2b
  rule). In kunglao_log the reason entries are added to `reasons`
  BEFORE the AUTO_NULL_FIELDS sweep at :550, so a coerced duration_ms
  carries `value_unparseable`, not the sweep's `omitted` (a caller
  reason always wins — the sweep's own documented precedence).
- **Docstring amendments (review D-3b), part of the diff:** emit's
  epoch paragraph ("Deliberately there is NO explicit-null face for
  epoch … Only a genuinely unreadable ledger leaves the field null")
  gains the third null face — an explicit garbage epoch now lands null
  documented as `value_unparseable` (the no-fabrication rule overrides
  the no-explicit-null rule); the AUTO_NULL_FIELDS epoch note and
  audit.py's twin schema comment (:34-36) get the same sentence.
- NOT applied to ts/actor/action (the row's identity fields): a
  garbage actor/action is a caller contract violation that audit.py
  already refuses loudly (`unregistered action` warn + return False) —
  that refusal is the designed behavior, not a crash risk.

## D5 — Exit-code registry (MEDIUM #5)

**Semantics check against the registry's own docstring.**
`hook_exit_codes.py` says (Note, :15-17): "Claude Code only reads 0 vs
non-zero for allow/block decisions. The semantic distinction … is for
LOGS and debugging". Consequences: (a) the registry is DOCUMENTATION
with enum teeth, not a wire contract; (b) resolving the exit-1 dual
meaning MUST NOT renumber any emitted code (logs/scanners pin them;
the hooks' docstrings pin them; the tests pin them); (c) per-hook rows
are the only place a code's meaning can be disambiguated — 1 means
crash for state_anchor and deliberate-block for workguard_gate, and
that is fine BECAUSE the row says so.

**Header reconciliation (review D-4).** The module header's first
paragraph (:5) currently claims "Claude Code constrains hooks to
exit(0)=allow, exit(2)=block" — contradicting its own Note (:15-17)
and Claude Code's actual hook contract (non-zero exit = block for
PreToolUse-class hooks; Stop-hook blocking is carried by the stdout
JSON `{"decision": "block", …}`, which both completion_gate and
workguard_gate emit alongside their exit codes — see hooks/
completion_gate.py:8/:249-262/:392, workguard_gate.py:19-21/:92-94).
The amendment rewrites the header line to the Note's contract, states
the stdout-JSON block mechanism for Stop hooks, and keeps the
"documented semantics for logs" purpose — the module stops
contradicting itself, which is also what makes never-renumber safe
under either reading.

**Changes.**
1. Additive `ExitCode` members (values mirror the shim's constants and
   the judge's documented table — no drift, no aliasing):
   `INTENT_UNMATCHED = 4`, `NOTES_DUE = 5`, `NOTES_FAKE = 6`,
   `SUMMARY_FAKE = 7`.
2. Register `"completion_gate"` with its FULL vocabulary — judge:
   0/1/2/3/4 (its docstring's precedence table 3>2>1>4>0); shim-only:
   5/6/7, the second-stop refusal's 1, and the fail-closed integrity
   3s (no-oracle, unparseable oracle, judge crash). Exit 1's row text
   explicitly says "deliberate fail-closed block — NOT a crash".
   Verified complete: no other code is emitted by either face.
3. Workguard's block face gets its documented word: the row already
   keys `GENERAL_ERROR` and documents the deliberate block; the enum
   comment (:26) is amended to acknowledge the documented deliberate
   exit-1 block faces (workguard_gate, completion_gate second-stop)
   and point at the per-hook rows — the "word" no longer contradicts
   the documented face; the per-hook row carries the precise meaning.
   An aliased `DELIBERATE_BLOCK = 1` member was REJECTED (IntEnum
   aliasing — two names, one member, drift invitation).
4. `hooks/completion_gate.py`: `EXIT_NOTES_DUE/NOTES_FAKE/
   SUMMARY_FAKE` derive from the registry — **in a SEPARATE try/except
   placed AFTER the existing _path_hygiene/kunglao_log block** (review
   D-5). Inside the EXISTING block, a registry-import failure would
   drop the hook into the except arm and silently replace the
   canonical dedupe+ledger `warn` with the stderr stub even though
   kunglao_log imports fine. The separate block relies on
   `_esp406()` having already run; per-constant literal fallbacks
   (`EXIT_NOTES_DUE = 5` etc.) preserve the partial-deploy lifeline.
5. **Drift-guard transfer (review D-2).**
   `tests/test_notes_closure_762.py::
   test_noted_exit_code_is_five_and_documented` pins the SUBSTRING
   `"EXIT_NOTES_DUE = 5"` against the shim's source. With the
   derivation above the substring still matches — it lives in the
   fallback arm — so that test stays green UNTOUCHED, but its
   drift-guard role now covers only the fallback. The guard over the
   PRIMARY path is the new value pin in test_hook_exit_codes.py:
   `shim.EXIT_NOTES_DUE == int(ExitCode.NOTES_DUE) == 5` (and 6/7) —
   the registry is the single source of truth the module docstring
   claims, and this pin is what enforces it. The other value pins
   (test_notes_closure_762.py:329/:342, test_notes_fake_834.py:88,
   test_summary_fake_826.py:100) assert `== 5/6/7` and stay green.
6. `tests/test_hook_exit_codes.py` extended: completion_gate +
   workguard_gate in the all-hooks sweep; 4/5/6/7 member values
   pinned; the completion_gate row documents every code the
   shim/judge can emit; the shim-vs-registry value pin.

**Rejected alternatives.**
- Renumber workguard's block to BLOCKED(3) or completion_gate's
  refusal to REJECT(2): changes emitted codes the hooks' own
  docstrings and the #147/#199/#434 tests pin; the registry Note
  explicitly scopes semantics to logs. REJECTED.
- Moving the whole shim onto ExitCode returns: touches 15+ return
  sites for zero documentation gain; constants-at-the-top wiring gives
  the single-source property mechanically. REJECTED (scope).

## D6 — run_pipeline step cage (MEDIUM #6)

- `try: result = fn() except Exception as exc:` →
  `result = _record(ctx, checkpoint, name, model.FAIL, None, None, 0,
  {"failed_step": name, "error": f"{type(exc).__name__}: {exc}"})`.
- `_record` (e2e.runtime.record_result) is the canonical seam: it
  builds the CheckpointResult, writes the per-step evidence file, and
  emits exactly one audit row — the cage adds no second writer.
- The loop's existing FAIL branch then sets
  `EXIT_CHECKPOINT_FAIL`/`"FAIL"` and breaks; `finalize()` runs and the
  report is written. The crash→FAIL conversion needs no new machinery.
- **Where the error text lands (review D-8, stated tradeoff):** the
  `{error, failed_step}` detail reaches the per-step evidence JSON
  (the resume artifact), NOT the audit row — `emit_checkpoint`'s
  detail contract is exactly-those-keys (pinned by
  TestUnifiedAuditTrail); adding `error` there would break the pinned
  contract, so it is NOT done, and nobody should "complete" it later.
  rc=None with no null_reason matches the existing BLOCKED precedent
  (:618/:635/:704/:722 pass rc=None, out=None).
- **Cage boundary (review D-8):** `_record` itself writes files and
  CAN raise (OSError on the evidence dir) — the cage would exit the
  same way it does today. This is the pre-existing shape of every
  `_record` call site in the file; hardening it is out of scope.
- BaseException (KeyboardInterrupt/SystemExit) is not caged: operator
  interrupts must still stop the pipeline immediately.

## TDD plan (RED first, per fix)

1. Wave cage: one face.run_dispatch raises mid-wave → siblings'
   records land, ERROR record synthesized (outcome "ERROR", claim
   preserved), dispatch_result row emitted with the caged null reason,
   run_pipeline-level behavior intact; wave-of-one raising act →
   caged, no propagation; auto-face prompt_file missing → ERROR
   record, "prompt_file_unreadable" reason, no raise.
2. resolve_claims: corrupt YAML spec → warn on stderr (capsys) +
   defaults restored; non-dict spec → warn; anchors-absent spec → no
   warn; MISSING spec file → no warn (silent defaults restore) (D-6).
3. retry counter: garbage `.retry-counter.yaml` → returns {} AND one
   rate-limited warn (dedupe: second read does not re-warn with same
   reason).
4. _safe_int: emit(duration_ms="garbage", exit="x", epoch=[1]) → no
   raise, row written, coerced fields null + value_unparseable
   reasons; `float('inf')` → null (OverflowError caged, D-1);
   `float('nan')` → null; garbage epoch does NOT re-inherit the tick
   (ordering pin, D-3); numeric strings still coerce; audit.py twin
   same.
5. registry: ExitCode 4/5/6/7 pinned; completion_gate + workguard rows
   present with documented faces; shim constants == registry values ==
   literals (drift-guard transfer pin, D-2).
6. pipeline cage: a checkpoint_cN raising → FAIL result recorded,
   report written via report_sink, exit code EXIT_CHECKPOINT_FAIL.

## Risks

- The audit.py `exit_null_reason` kwarg is additive; all existing
  callers keep the default literal (no drift possible).
- The warn calls add stderr output in failure paths — tests that
  assert-clean stderr on those paths would red; the touched suites are
  run and adjusted only where the warn is the DESIGNED new behavior
  (no test in the touched suites asserts clean stderr on these paths —
  verified for test_max_retries_604 by the review).
- Registry additions are additive; `test_hook_exit_codes.py`'s
  existing assertions stay green untouched (extended, not rewritten);
  the test_notes_closure_762 source-substring pin stays green via the
  fallback literal (verified in D5.5).
- The docstring amendments (D-3b, D-4) are comment-only —
  comment_hygiene re-mint pairing applies per repo convention.
