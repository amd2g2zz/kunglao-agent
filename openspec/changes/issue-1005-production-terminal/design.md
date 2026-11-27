## Context

The real `hooks/completion_gate.py::process_event` first handles a sanctioned second Stop, then resolves and activates the workspace, loads and judges the oracle, and checks notes and summary. `cg.judge` passing is not equivalent to passing the later checks. Its existing sanction is minted before those checks; a sanctioned second Stop can return before judging them. An exit-zero fail-open path is also not evidence of completion. `rlvr.episode_settle.settle_mission` currently is not called from that Stop path. INV-003 and INV-005 apply to the downstream consumers, not just to the call itself.

The existing settler treats statuses other than OPEN as terminal and can project a claim-register status into a verifier-record mirror. A claim's status alone does not establish mission termination, independent checker identity, success, or attributable failure. A verified failed outcome, a surrendered mission and an interruption are distinct cases; a surrender is not automatically a verified failure, and its documented evidence must determine eligibility.

## Integration contract

**Caller and trigger:** the activated production Stop hook is the caller. Settlement fires only after the oracle and all final checks have actually succeeded, and after independently checking a real terminal outcome and checker record. Workspace absence, disabled hook, oracle I/O fail-open, judge failure, outstanding checks, open or in-progress work, interruption and unverifiable outcomes must never enter the success path. A sanctioned second Stop is a release decision, not proof that final checks passed; it can trigger settlement only if the same settlement eligibility is independently established. A verified failed mission remains eligible as a failure when its actual terminal evidence and attribution establish it; the outcome is never restamped as success.

**Identity and seal:** the idempotency fingerprint binds one mission and its independently verified evidence to its persisted settlement; dispatch, worker, independent checker and settlement retain distinct stable identities. Existing seals are verified through their production owner; missing or corrupt evidence is reported without exposing or replacing keys. A mirror derived from the claim register is not independent verification.

**Transaction and failure recovery:** serialize concurrent terminal settlement per workspace. Persist the settlement intent and its retry reason before admitting completion; make writes replay-safe, preserve already verified ledger facts and only mark complete after ledger, episode and derived-view consistency are checked. A durable recovery consumer must replay unfinished work after a crash; if durable intent cannot be recorded, report the failure rather than claim completion. An episode, a span, or a fail-open read by itself cannot prove that all settlement writes succeeded. The proposal must be checked against actual writer behavior and cannot assert atomicity that those writers do not provide.

**Independent checker and consumers:** checker identity is separate from the maker; real checker artifacts and their binding are required, rather than generated status mirrors. The episode pool and `pool_indexer` consume the episode; settlement/credit consumers and `q_cells` read their own persisted data. `runs/face-spans.jsonl` requires a named reader, stable parent/child identities and sanitized metadata; it is not a ledger. Where no consumer or source can be established, report the value or connection as unknown.

## Evaluation and open decision

The dev-only paired comparison uses synthetic state and cost, identical visible information and checker semantics for each arm, reproducible seeds, and explicit fault schedules. Record both successful and failed traces, count unfinished attempts in denominators, and never interpret synthetic cost as measured time or tokens. Unsupported numerical or task-memory ablations are marked not runnable rather than simulated as if connected. Any missing production connection is reported.

S5 remains a **proposed view-only decision**, pending owner approval: declaration metadata must not alter posterior inputs, and `declared_propensity` denotes historical smoothed frequency, not behavior probability. This change does not close that owner-dependent acceptance.

The existing boundary is narrower than a global view-only claim. Dispatch appends declaration rows to `runs/experience.jsonl`; `disposition_producer` reads them across processes and propagates route and historical frequency to persisted disposition and `disposition-signal/1` telemetry rows marked `strategy_learning`. `disposition_measure` reads the disposition file or its mirror. In the checked code, the Q-cell posterior fold reads `q-cell-obs` rows and does not ingest disposition signals directly. A cross-process synthetic regression compares equal Q-cell inputs with and without a declaration; it is not evidence about external consumers. Compatibility work must preserve existing records, identify any signal consumers, and obtain an owner decision before changing learning inputs. Existing propensity wording needs correction without reinterpreting historical records as measured policy probabilities.

## Implemented production slice and remaining acceptance

`hooks/completion_gate.py:process_event` calls
`rlvr.production_terminal.settle_stop` only after the real oracle, notes and
summary checks pass. An exception swallowed by a discriminator's legacy
fail-open path suppresses settlement. The sanctioned second-Stop release does
not call settlement. The new owner requires a supported terminal status,
a real canonical checker record, its byte-matching `verdict_anchor`, and a
checker identity distinct from the maker. Maker identity comes from explicit
claim metadata or the existing latest maker verify-note; absent identity is
ineligible. It never invokes the settler's mirror-writing path without that
independent evidence.

The firing fingerprint is `runs/production-terminal.json` (`production-terminal/1`)
with the mission anchor, evidence digest and `pending`, `retry`, or `completed`
state. A per-workspace flock serializes Stops. An fsynced atomic intent precedes
all settlement writes. The next eligible **real Stop** consumes unfinished
intent, rechecks the same evidence, calls the existing mission settler and
`settle_round_credit.run`, and reads back pending rollouts, the episode and its
derived views before certifying completion. It preserves append-only facts.
This is replayable coordination, not a transaction across legacy writers.
Round credit can legitimately add the existing scalar tier amendment after the
initial rollout settlement; that amendment is not a duplicate reward.

The operator consumer is
`PYTHONPATH=scripts python -m rlvr.production_terminal <workspace>`: it reads
the checkpoint, episode count, pending rollouts and `runs/face-spans.jsonl`
separately. Current actual spans cover settlement and mission terminal, with
stable parent/child IDs, start/end event, timestamp, orchestrator role, operation
name and unknown usage. **Dispatch, worker and checker stage spans are still
unimplemented.** No terminal span is accepted as ledger proof. Terminal traces
are best-effort and never contain sample bytes, credentials or key material.

`tests/test_production_learning_1005.py` runs synthetic artifact bytes through
actual dispatch, two real SubagentStop calls (park then consume the mocked
independent ruling), and subprocess Stop. It checks non-empty question,
absolute rules path, artifact hashes, armed seal, dispatch attribution,
non-uniform posterior, duplicate completion, and fixed-seed subsequent sampler
choices. This proves component wiring in a synthetic workspace only. Real
Claude session liveness, real sample outcomes, and expert capability remain
unverified. `devkit/experiments/v016_within_task.py`, the five paired environments
and 200+200-seed evaluation remain TODO; no simulated metrics are reported.

## P1 certification fixes after independent review

The final terminal owner strictly checks the existing notes queue's readable
YAML and mapping/list/entry shapes before invoking settlement. Missing queue is
legacy absence; a present unreadable or malformed queue is unknown obligation
state and produces `retry`, even when the legacy `notes_due()` returned `[]`.

Before any reward owner runs, and again before completion, participating
round-credit and Q-cell credit rows are checked by `learning_seal.verify_row`.
Rows already carrying seals remain subject to verification if the key later
disappears or becomes corrupt. Armed channels also reject missing seals.
Certification never re-signs invalid facts, overwrites key material, or repairs
corrupted reward values. Raw JSONL readability is required; tolerated telemetry
reads cannot silently drop a malformed participating fact for certification.

For every applicable committed dispatch, terminal certification reads its
existing settled round-credit row and `q_cells.banked_mass`. Missing/unreadable
credit remains `retry` even when `settle_round_credit.run` returned no top-level
error after swallowing a Q-cell write failure. The real Stop checks this return
state and blocks; the next eligible Stop reruns the existing recovery owner.
This adds a read-after-write postcondition only: reward arithmetic, calibration,
credit amendments, and the separate #1042 amendment transaction remain unchanged.
Known incomplete postconditions return `status: retry` with a diagnostic reason;
unexpected exceptions retain the existing raise-and-block behavior.
