# design — issue-460-feature-mining (Part A)

## Verified anchors (2026-09-30, branch feat/feature-mining-460a off origin/dev bc8aaad3)

| Question | Actual | Drift |
|---|---|---|
| What a run dir carries | `<root>/runs/e2e/<run_id>/run-state.json` {run_id, family, lane, type, unit, task_dir, ws, steps, started_ts, [method_family: ""]} + `report.json` (schema e2e-run-report/1: final_status, exit_code, oracle; C6 detail.acts[] in pre-audit-stream runs) + checkpoint C*.json (C6-loop.json carries the same acts[]) + `dispatch-prompt-C*.md` (exemplar with full artifacts: e2e-run-v016/runs/e2e/e2e-20260929-221504) | none |
| What a workspace carries | `task_spec.yaml` (lane, promise.prescan.{apkid,die}.state, difficulty block schema difficulty-calibration/1: tier/score/dominant_factor/factors/families/coverage), `claim-register.yaml` (claims: id/status/source/answers_question), `evidence/{die,apkid,difficulty}.json` (die/apkid usually absent — `state: not_probed`), `runs/logs/e2e-audit.jsonl` (17-field stream; dispatch_attempt/dispatch_result rows carry claim top-level, detail as a JSON-ENCODED STRING), `runs/rollout-ledger.jsonl` (settlement rows, rollout_id `task/<claim>`; present in 1 of 8 live workspaces — the fold settles scaffold claims C-001..C-003) | none |
| Audit-stream coverage | only 2 of 8 live workspaces (e2e-ws-20260929-221504, e2e-ws-20260930-060104) carry runs/logs/e2e-audit.jsonl; the other 6 runs' per-act data exists only in report.json/C6-loop.json detail.acts[] ({claim, mode, outcome: "DISPATCHED", detail:{cmd, rc, ...}}) | disclosed below (Decision 3) |
| rc=None dispatch results | `scripts/e2e/audit.py::emit_dispatch_result(rc: int | None)` — a result row can exist with rc null (orchestrator/dry face, null_reasons exit=orchestrator_face_no_subprocess) | mapped below (Decision 3) |
| Method attribution material | live e2e dispatch envelopes declare NO method_family (kunglao_dispatch = {version, claim, tier, tools, agent}); the dual-face declaration contract exists in `method_families.declared_value(envelope_meta, prompt_text)` (v1 envelope field first, v0 `method-family:` prose marker second); the per-claim prompt file `dispatch-prompt-{claim}.md` is REWRITTEN on every dispatch of that claim (checkpoints.py:463); claim registers carry `source` (static_re / synthesis / …) — hence `method_family_or_claim_source`; #432 tokens are kebab-case (static-decompile, crypto-core-identification, …) | none |
| act_result material | dispatch_result rows carry rc + timed_out INSIDE the JSON-encoded detail string (top-level exit is null on dispatch rows); rc=0 landed, timed_out/rc=-1 timeout, other rc blocked, rc-null-in-present-row unknown | none |
| Settlement material | `rlvr.ledger.settled(ws)` folds the append-only ledger (last non-null settlement per rollout_id) and never raises on a missing ledger → reuse, not re-implement | none |
| Difficulty/probe composition owner | `difficulty_calibration.features_from_evidence` is the canonical die/apkid → factor/coverage composition (pure function) + `_die_usable`/`_apkid_usable` presence rules; the MOUNTED difficulty block (task_spec/evidence/difficulty.json) is the persisted calibration; `runs/` is gitignored (line 37) so the live output can never be committed accidentally | none |
| Determinism precedent | ledger/q-cell writers: `json.dumps(row, ensure_ascii=False) + "\n"` for rows; `sort_keys=True` only inside digests | none |

## Decision 1: run-state.json is the run anchor; everything joins from it

A run IS a directory under `<root>/runs/e2e/` carrying a parseable
`run-state.json`. Row identity: run_id = run-state's `run_id` field
(authority over the directory name), family = run-state's `family`
(the corpus TIER directory — release/chain/…; the task.yaml semantic
family is derivable from task_id and is not a separate row field),
task_id = run-state's `unit`. All other sources join through the
recorded pointers: `ws` (workspace), `task_dir` (corpus task).
Resolution rule for both pointers: an absolute path is used verbatim
(live shape); a RELATIVE path resolves against the mining root
(fixture shape — keeps the pinned fixtures machine-independent). A
run whose run-state.json is missing, unparseable, OR undecodable
(invalid UTF-8 — the #438 lesson: decode errors are data problems,
counted with unparseable) is SKIPPED with a stderr warn; a run whose
pointers dangle degrades field-by-field (the difficulty gap-rule
idiom: absence is never scored, it is recorded as nulls/empty and the
row still ships — an unrun task is exactly the cold-start case Part B
must see).

## Decision 2: the row is instance-keyed, not progress-keyed

`signature_hash` = sha256 over the canonical JSON of the `features`
object (sort_keys=True, separators=(",",":"), ensure_ascii=False,
UTF-8), first 12 hex chars — mirroring the state_signature digest
idiom but a DIFFERENT namespace: this is the INSTANCE signature (what
the target IS), not the pre-dispatch progress state (where the run
stands). The features object contains only instance-level,
discretized inputs, each field pinned exactly (the hash is computed
over these bytes, so an unpinned field set would make the hash
implementation-defined):

- `lane`: run-state `lane`, fallback task_spec `lane`, else null.
- `project_type`: run-state `type`, else null.
- `target_kind`: `{"language": <task.yaml workspace_scaffold.language
  or null>, "entry_suffix": <lowercased Path(entry).suffix WITH the
  dot, e.g. ".apk"; null when entry absent>}`.
- `packer_flags`: `{"packing","obfuscation","anti_analysis",
  "surface_reduction"}` booleans = the difficulty block's
  `families.<name>.active`; `detected_packers` = sorted unique union
  of die `derived.detected_packer` (when truthy) and apkid
  `summary.packer`; `detected_obfuscators` = sorted unique apkid
  `summary.obfuscator`. Case preserved, sort is codepoint order.
  Absent evidence degrades to all-false booleans + empty lists (never
  null — the absence-never-scored idiom).
- `difficulty_factors`: the MOUNTED calibration block verbatim-shaped
  — precedence: task_spec `difficulty:` block; fallback
  `evidence/difficulty.json`; both absent/unusable → null.
  Recomputation from raw die/apkid via calibrate() is FORBIDDEN (the
  mounted block is the persisted calibration; re-deriving could
  disagree with what the run actually saw). Emitted shape:
  `{"tier","score","dominant_factor","factors":{name→score},
  "families":{name→active},"coverage":{"die","apkid"}}` — timestamps
  (generated_at) and free-text notes EXCLUDED (instance signature
  must not vary with mount time).
- `probe_outputs`: always-present sub-objects, inner fields null on
  degrade:
  `{"die": {"prescan_state": <task_spec promise.prescan.die.state or
  null>, "usable": <difficulty_calibration._die_usable(doc)>,
  "detected_packer": <die derived.detected_packer or null>,
  "entropy_max": <max section entropy float or null>},
  "apkid": {"prescan_state": …, "usable": <_apkid_usable(doc)>,
  "packers": <summary.packer list or []>, "obfuscators":
  <summary.obfuscator list or []>}}`.

No budget, no run timestamps, no claim state: two runs of the same
task with the same evidence hash equal; the outcomes list carries
everything run-specific. Part B joins on this hash.

## Decision 3: outcomes are per-act, joined from the audit stream

One outcome entry per dispatch attempt, in stream order, each
carrying `claim` and `run_id` (traceability keys beyond the card's
four outcome fields), `method_family_or_claim_source`,
`act_result`, `settled`, `credit`:

- **Pairing (FIFO per claim)**: each attempt pairs with the earliest
  LATER result row carrying the same claim (the live stream
  interleaves attempts and results across claims; FIFO is the only
  pairing that is order-stable and crash-tolerant). An attempt with
  no later result row → act_result `unknown`.
- **act_result** ∈ {landed, timeout, blocked, unknown}: rc and
  timed_out are read from the result row's `detail` (a JSON-encoded
  STRING — json.loads'd; the top-level `exit` field is null on
  dispatch rows and is NOT read). rc 0 and not timed_out → landed;
  timed_out true or rc -1 → timeout; any other non-zero rc →
  blocked; rc null in a PRESENT result row → unknown (the
  orchestrator/dry face — a no-subprocess row is not a blocked act).
- **Attribution**: the dispatch prompt file
  `<run_dir>/dispatch-prompt-{claim}.md` is read (runner convention,
  checkpoints.py:463); its first-line `kunglao_dispatch` JSON is the
  envelope meta and the file text is the prompt text, fed to
  `method_families.declared_value` (v1 envelope `method_family`
  field first, v0 `method-family:` prose marker second — the #105
  dual-face contract, REUSED not re-implemented). Undeclared → the
  claim register's `source` for that claim → else null (never
  fabricated). The prompt file is per-claim and rewritten on every
  dispatch: once the #462/#432 sampler varies family per attempt,
  every attempt of that claim inherits the LAST envelope — a stated
  approximation, disclosed here (the q_cells._current_sig honesty
  precedent: approximated attribution beats fabricated attribution).
- **settled/credit**: ledger fold of rollout_id `task/<claim>` via
  `rlvr.ledger.settled(ws)`: a settlement row → settled true, credit
  = its reward; none → settled false, credit null.
- **Coverage boundary (disclosed)**: outcomes are mined ONLY from
  the workspace audit stream. Runs predating the unified audit
  stream (6 of the 8 live workspaces) mine with `outcomes: []` —
  their per-act data survives only in report.json / C6-loop.json
  `detail.acts[]` ({claim, mode, outcome: "DISPATCHED", …}), and a
  checkpoint-acts fallback is a declared follow-up card (owner scope
  call), not Part A. The report.json final_status/oracle is likewise
  NOT an outcome field: outcomes are per-act training tuples.

## Decision 4: determinism is a byte contract

Rows sorted by (family, task_id, run_id, root) — the root in the key
makes the output byte-identical regardless of CLI argument order and
disambiguates the same run_id appearing in two different roots (both
rows ship: distinct truth, distinct provenance); roots passed
duplicate are deduplicated by resolved path before scanning.
Outcomes in audit stream order; every row serialized
`json.dumps(row, ensure_ascii=False, sort_keys=True)` + "\n" (sorted
keys chosen over the ledger's insertion-order idiom because this
file is a hashed, diffed artifact — key-order drift would fake
content drift); floats pass through unchanged from their parsed JSON
values (no arithmetic on read), so the same input bytes always
serialize identically. The miner writes only the --out path (default
`runs/feature-table.jsonl` under CWD) and never mutates any input
root. A one-line JSON summary {roots, runs, rows, skipped} goes to
stdout.

## Decision 5: fixtures are the pinned regression truth, sanitized

`tests/fixtures/feature-mining-460/` carries a fixture ROOT tree
synthesizing 3 historical runs shaped byte-contract-accurately to
the live artifacts (exemplar: e2e-20260929-221504, which carries the
full artifact set), with run-state pointers rewritten relative
(Decision 1) and no absolute machine paths, no secrets, no live
prompt bodies. The three runs: (a) a landed + timeout mix where one
DISPATCHED claim carries a ledger settlement (settled true, credit
0.0 — the truthful join shape; live ledgers settle scaffold claims,
so the fixture synthesizes the dispatched-claim settlement the join
must handle), (b) a timeout-loop run with die/apkid evidence present
(exercises the probe_outputs/usable path and the hash-differs
scenario), (c) a degraded run with a dangling ws pointer (null
features degrade, empty outcomes). One dispatch prompt in (a)
declares a REGISTERED #432 token (static-decompile) to exercise the
envelope-wins-over-register-source path. The golden
`feature-table.jsonl` mined from the fixture root is committed beside
it and its sha256 is pinned by the determinism test — any extraction
drift goes RED. The LIVE mining (kunglao-wt roots) is a runtime
operation against process data and is never committed.

## Design review (independent, pre-implementation)

Adversarial architect review (45 tool uses against the repo, the
contracts, and the live /tmp/e2e + kunglao-wt data) returned FAIL
with 3 HIGH, 7 MEDIUM, 7 LOW defects; the architecture itself was
confirmed sound (capability boundary, hash namespacing, settled()
reuse, determinism, live-data safety all verified against actual
code and data). All defects folded BEFORE any test or code:

- H1 rc-null dispatch results → act_result unknown (Decision 3).
- H2 attempt/result pairing pinned FIFO-per-claim (Decision 3).
- H3 audit-stream coverage cliff disclosed + checkpoint-acts
  fallback declared as follow-up (Decision 3, anchors table).
- M1 declared_value reuse + per-claim last-write-wins approximation
  disclosed (Decision 3).
- M2 difficulty_factors precedence pinned to the mounted block,
  recomputation forbidden (Decision 2).
- M3 probe_outputs sub-object shape enumerated, degrade = inner
  nulls (Decision 2, spec schema requirement).
- M4 packer_flags merge rule (sorted unique union) + all-false/empty
  degrade pinned (Decision 2).
- M5 sort key extended with root, duplicate roots deduped, duplicate
  run_id across roots both ship (Decision 4).
- M6 scenario token corrected to a registered #432 token
  (static-decompile; spec Requirement 3).
- M7 decode errors counted as unparseable — the #438 lesson
  inherited (Decision 1, spec tolerance requirement).
- L1 tasks.md 1.2 was unchecked until this fold landed (now [x]).
- L2 row-shape wording names both claim and run_id traceability keys.
- L3 anchors exemplar corrected to e2e-20260929-221504.
- L4 rc/timed_out field authority pinned to the detail JSON string.
- L5 run_id authority (run-state field) and lane precedence pinned.
- L6 the settled fixture case is a settled DISPATCHED claim.
- L7 entry_suffix normalization pinned (lowercased, dot kept).

## Code-review folds (independent pre-merge review, post-implementation)

The staged-diff code review returned FAIL with 1 HIGH / 2 MEDIUM /
2 LOW; all folded (tests added for each):

- HIGH — kunglao_log.warn's ledger face resolves a workspace by cwd
  walk-up (any dir carrying runs/) and APPENDS into it: with CWD
  inside a mining root, a tolerance warn would WRITE into the input —
  a read-only contract break. The miner's warns are now a local
  stderr-only `_warn` (documented why NOT kunglao_log); the
  never-written test now exercises the warn path with CWD inside the
  root.
- MEDIUM — the settlement join is kind-scoped (`settled(ws,
  kind="task")`): a self_distill/hybrid_distill rollout anchored at
  the same string is not the claim's task settlement (test pinned).
- MEDIUM — malformed FIELD VALUES (mixed-type apkid packer lists,
  non-numeric entropy, scalar families entries) crashed the table:
  every probe/difficulty field read is now isinstance-guarded, packer
  lists coerce-before-sort, non-finite entropies drop to null (tests
  pinned).
- LOW — a parseable run-state whose row fails feature-table/1 (absent
  family/unit, non-string type) is now skipped via validate_row inside
  mine_run — the miner never ships a row its own validator rejects
  (spec tolerance requirement gained the sentence; test pinned). A
  difficulty block missing tier/score/dominant_factor degrades to
  null instead of fabricating "None" strings.
- LOW — path-hostile claim ids (separators, null bytes) never reach
  the filesystem: the envelope lookup rejects them up front and the
  outcome ships with register/null attribution (test pinned).
- Test gaps the review named are closed: absolute-pointer verbatim
  resolution; warn-path + inputs-never-written combined.
