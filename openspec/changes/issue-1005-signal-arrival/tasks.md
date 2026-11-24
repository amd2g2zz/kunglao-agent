## 1. Baseline

- [x] Record RED: `tests/test_signal_arrival_1005.py` before the module exists — 41 failed (the script is absent), saved under the pipeline's evidence directory.

## 2. The report

- [x] Build `scripts/rlvr/signal_arrival.py`: seven counts, each leaf a number or `no data` with the reason; standard library only; nothing opened for writing.
- [x] Read the three named read faces before any reuse and record that each can write (`consolidated_ledger.read`, `liveness`, `posteriors_case`); reuse none.
- [x] Cover with tests: each count on a workspace built through the public helpers, the empty workspace, the read-only proof (hash and mtime of every file before and after, no new file), a malformed ledger line, the command line.
- [x] Make it green; `ruff check` on the touched Python.

## 3. Registration

- [x] `from . import signal_arrival` in `scripts/rlvr/__init__.py` (required by `tests/test_rlvr_facade_756.py`).
- [x] A row in `scripts/README.md` and a pointer in `scripts/rlvr/README.md`.
- [x] `python scripts/deploy_manifest.py --write`, then `--verify`.
- [x] This OpenSpec change; `openspec validate issue-1005-signal-arrival --strict`.

## 4. The real workspaces, read-only

- [x] Run the report on `/Users/mikenike/re-labs/beike-verification` and `/Users/mikenike/re-labs/ctf-1`, each run bracketed by a sha256 + mtime snapshot of every file.
- [x] Keep both reports under the relay's evidence directory, out of the repository.

## 5. After the first review

- [x] `settlement.attempts` counts the results of `q_cells.observe_settlement` that left a trace: `banked` is what that call books; the credit rows of the other faces are `other_credit_rows`. Label, design, proposal and the script row say what is counted.
- [x] No text calls the blind path's deferred credit file a lasting trace: it is deleted once its credit is banked.
- [x] A dispatch row whose `dispatch_id` is a list or an object is reported, not a crash.
- [x] One assertion theme per test: the agreement test is two, the missing-sources test is two.
- [x] The read-only proof records the mtime of every directory and of the workspace root, in the test and in the external bracket.
- [x] Tests for the empty-list rule, for a source of the wrong kind, and for the reason beside a missing build label.
- [x] Run both real workspaces again under the bracket with the corrected count.
- [x] A JSON line or document nested past what the decoder can read is `unparsable`, not a crash (found while verifying; not among the review's items).

## 6. Left for later legs

- [ ] A second independent review of the staged diff (a different agent): the first failed on the items of section 5.
- [ ] Two commits (tests, then implementation and registration), pull request to `dev` with `Refs #1005`.
- [ ] The paid half: two real sessions at the pinned tip, when the model channel is back.
