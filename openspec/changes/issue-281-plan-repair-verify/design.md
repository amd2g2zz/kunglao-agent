# design — issue-281-plan-repair-verify

## Pattern being mirrored

The merged issue-249 remedy-verification design (episode-scoped state,
bounded-window escalation, telemetry rows, "visibility + escalation, not a
new block"). This card is the PLAN-DRIFT analog: the REJECT instructs a
repair; the repair outcome is now verified against the same detector that
issued the instruction.

## Anchors (verified at HEAD fefec1e)

- `scripts/plan_drift_detector.py` — `check()` builds the `drifts` list
  (five #237-era classes + #241 UNVERIFIED_EVIDENCE), prints the REJECT
  report, returns 0/1/2; `check_auto()` (#602) remaps to the dispatch-gate
  contract; `plan_path_candidates` resolution (global_plan.txt /
  global_plan.yaml / plan.md); `_emit_stale_plan_warns` is the in-module
  precedent for a fail-open event face.
- `hooks/worker_budget_sinks.py` `REJECT_FIXES['drift']` — the repair
  guidance ("update global_plan.txt and/or runs/plan-C*.md ...") the issue
  quotes; amended to name the verification.
- `hooks/worker_budget_core.check_plan_drift` — the sinks gate face; runs
  the detector via subprocess; inherits the verification through it (no
  hooks-side change needed for the tick).
- `scripts/convergence_health.py` `stalled_state` / `hooks/lib_kunglao.py`
  `is_stalled_remedy_dispatch` — the #249 pattern: state single-sourced in
  scripts/, the gate face consumes, fail-open/fail-closed split annotated
  at each edge.
- `templates/CLAUDE.md.base.tmpl:118` — the prose carrier contract
  ("amend ... after every convergence verdict") the issue cites; amended
  to point at the mechanical face.
- `scripts/event_taxonomy.py` `EMIT_ACTIONS` — the registration surface.

## Key decisions

1. **The tick lives inside check(), not in the hooks faces.** Every
   detection round advances the window regardless of which face ran the
   detector (operator CLI, --auto dispatch gate, worker_budget gate
   subprocess). #249 kept the state source in scripts/ (convergence_health
   .stalled_state) and the gate face consumed it; here the detector IS the
   state machine, so the hook faces need zero new logic. Trade-off: the
   sinks and dispatch-gate faces may both advance the window within one
   dispatch attempt (two faces, one attempt) — the window is defined in
   DETECTION ROUNDS per the issue, so double-advance is correct-by-
   definition, and the overdue cadence stays one row per window of
   continued drift.
2. **A dedicated state file, not ledger rows.** #249 counted remedy depth
   from convergence-ledger operator rows; the drift window needs
   read-modify-write of a single episode object (fingerprint + rounds),
   which a JSONL ledger serves badly. `runs/plan-repair-state.json`
   follows the `runs/.retry-counter.yaml` precedent for episode-scoped
   gate state. Writes are atomic (tmp + os.replace) so a concurrent face
   reads the old or the new file, never a torn one. Concurrent faces may
   still race the read-modify-write (last-write-wins, a lost increment) —
   accepted: the worst case is a delayed escalation by one window, never
   a premature close (a close requires a genuinely clean round, which the
   detector re-derives from the workspace itself, not from the state).
   ADVERSARIAL-WRITE ACCEPTANCE (review round 1, MEDIUM): runs/ is a
   worker surface — write_guard's contract is deliberately "the FOUR
   contract carriers, and nothing else" with post-image carrier checkers,
   so a runs/ JSON does not fit that shape and was NOT added. A worker
   can therefore reset `rounds` or plant state; the blast radius is
   bounded to the additive observability face (the dispatch verdict never
   depends on the state file — the drift REJECT is re-derived from the
   workspace every round), the file follows the accepted
   `runs/.retry-counter.yaml` forgery-class precedent, and the residue is
   visible (a planted state still cannot manufacture drift-free rounds:
   verified requires the detector's own rc=0). The #249-style
   authenticity upgrade (HMAC / append-only authoritative counter) is
   follow-up material if the operator ever gates on these rows.
3. **The window counter is cumulative and fingerprint-INDEPENDENT.**
   Review round 1 (HIGH) proved the round-1 design's disjoint-fingerprint
   branch defeatable: a workspace alternating two disjoint drift shapes
   reset its window every round (zero overdue) while flooding the log
   with false `plan_repair_verified` rows. Resolved by taking BOTH halves
   of the reviewer's fix as one redesign: (a) `plan_repair_verified`
   fires ONLY on a genuinely clean round (drifts==[] — verified means the
   repair cleaned the plan, not that the drift changed shape; a changed
   fingerprint supersedes the recorded shape in place, silently); and
   (b) the overdue driver is a cumulative drift-round counter that
   advances on EVERY non-clean round regardless of fingerprint, so
   rotation can never reset the window and a perpetually drifting
   workspace escalates on schedule (this also supplies the missing depth
   cap — the #249 MEDIUM-1 lesson class). The fingerprint
   (`TYPE:claim_id` items + classes) remains in the state and event
   detail as telemetry about the CURRENT shape.
4. **Fail-open everywhere, annotated.** Unreadable state file → skip
   verification for the round (stderr note, verdict untouched); any
   unexpected tick error → wrapper catch (silent-except ratchet form);
   state/event writes are fail-open; STALE_PLAN_ON_NEW_EVIDENCE warns are
   structurally excluded (they never enter `drifts`).
5. **Escalation cadence, not once-forever.** `plan_repair_overdue` fires
   at every multiple of the window (`rounds % PLAN_REPAIR_WINDOW_ROUNDS
   == 0`) — review round 1 (LOW): a single emit per episode went
   permanently silent while drift continued. One row per window of
   continued drift is the anti-spam bound; `plan_repair_verified` →
   stdout + event row, once per episode close (only a clean round can
   close it). Exit codes and the REJECT report are byte-identical to the
   pre-card detector on every single-round face.

## Out of scope

- The optional STALLED-class operator-face surfacing
  (convergence_health._human) — the unified log + stderr suffice; a
  follow-up card can wire a read-only line if the operator wants it in the
  health diagnostic.
- Any change to the five drift classes, the exit-code table, or the
  --auto remapping.
