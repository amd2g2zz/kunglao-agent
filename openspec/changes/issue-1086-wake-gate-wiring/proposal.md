# issue 1086 — S18 wake gate wiring (the wrapper the gate declaration names)

## Why

The pre-LLM wake gate is built, implemented and pinned
(`heartbeat_tick.py <ws> --origin cron --wake-gate`; quiet → rc 0 +
`QUIET:`, wake → rc 3 + `WAKE:`, #801 Face 1), and the offline replay proves
the watcher layer costs zero tokens on a quiet day. But nothing consumes the
verdict:

- the gate declaration itself says "a wake verdict exits 3 and **the wrapper
  injects the loop prompt**" — that wrapper did not exist anywhere in the
  repo;
- the operator contract registered the PROMPT as the cron body
  (`skills/kunglao-agent/SKILL.md` → `heartbeat_loop_prompt.py` stdout →
  `CronCreate */5 * * * *`, the same wording in `kunglao_resume.py`'s re-arm
  advice and `heartbeat_loop_prompt.py --verify`'s guidance), so a model turn
  fired every five minutes whether or not there was work, and the verdict only
  ever ran inside a turn whose tokens it existed to save (~750k input tok/h of
  LLM-mediated no-ops, #801's measured waste);
- the tick contract contradicted the reward layer: SKILL.md said "no action in
  a tick = idle fault" and the THINK seat was EMPTY-forbidden unconditionally,
  while the scheduling registry carries `sleep`/`none` as cost-0 actions and
  the reward layer states "deciding NOTHING gains exactly 0".

## What Changes

- New `scripts/heartbeat_wake_gate.py` — the OS-scheduler wrapper the
  declaration names. One pass = run the gate, then honor the verdict:
  QUIET (rc 0) injects nothing (zero prompt bytes, no receipt, exit 0); WAKE
  (rc 3) injects the loop prompt EXACTLY ONCE; rc 2 (the #634 idle circuit
  breaker) stays a mandatory stop; any wrapper/gate fault is LOUD (stderr
  banner + ledger warn + rc 1) and fails toward waking — never a silent QUIET.
  Delivery reuses existing faces only: the payload is the emitter's own body
  (`heartbeat_loop_prompt.build_prompt`, never a re-embedded copy) and the
  out-of-session turn is the external kicker's D4 shape (`build_kick_command`
  + detached `claude -p`, prompt via stdin), skipped when a live session owns
  the wake so a second orchestrator never starts on one workspace.
  `--print-registration` emits the crontab line + schtasks args as strings
  only (the kicker's D5 precedent).
- The contract registers the gate, not the prompt: SKILL.md's activation block
  gains the wrapper registration line (the loop-prompt emitter line stays,
  relabeled as the WAKE payload + the demoted armed watchdog), the loop
  prompt's watchdog tick runs `--origin cron --wake-gate` with a QUIET →
  end-the-turn branch, `--verify`'s fix guidance and `kunglao_resume`'s re-arm
  advice name the wrapper first. The durable /loop cron is never deleted
  (#685 D5) — it is the watchdog, no longer the scheduler.
- Quiet is legal inaction in the tick contract: SKILL.md 1.4 scopes the
  idle-fault rule and the THINK EMPTY-forbidden rule to a WAKEN tick; under a
  QUIET verdict nothing is injected, no model turn happens, and no action is
  owed. The WAKE-branch discipline is unchanged verbatim.
- The `wake_gate` mechanism entry points at the wrapper
  (`entry: scripts/heartbeat_wake_gate.py`) so the registry names what the OS
  scheduler actually runs.
- The remaining prompt-first guidance surfaces are rewritten gate-first too
  (closeout appeal #1 — otherwise the repair envelopes re-teach the bypass on
  every dispatch rejection): `hooks/worker_budget_sinks.py`'s heartbeat
  REJECT_FIX envelope and its not-registered repair message,
  `references/governance/guardrails.md` §6.1,
  `references/contracts/cold-start-contract.md`'s mandatory-steps clause, and
  `scripts/eval_loop_runner.py`'s TICK_GATE refusal remedy. Each keeps the
  CronCreate/#754 durable-watchdog wording (the existing pins bite it) with
  the gate registration leading.

## Impact

- `experiments/scheduler/quiet_day_replay.py` three pins unchanged and green
  (quiet 288 polls/0 wakes, material 5 events/5 wakes, noise 288 rows/0
  wakes) — this slice wires the cron consumer, it does not touch the
  predicate, the watcher or the event stream.
- Affected surfaces: `skills/kunglao-agent/SKILL.md` (activation + tick
  binding), `scripts/heartbeat_loop_prompt.py` (docstring, tick line, verify
  guidance), `scripts/kunglao_resume.py` (re-arm advice),
  `scripts/mechanisms.yaml` (wake_gate entry/description),
  `scripts/README.md` + `tools/_INDEX.ext.yaml` (registration triple),
  `deploy-manifest.yaml` (regenerated last).
- Out of scope: BUS A/B event semantics unification (S19), cheap mechanisms in
  the gate pass (S20), the `intelligent_scheduling` wake-decision wiring in
  the WAKE branch (S21), deleting any cron (#685 D5), and
  `scripts/kunglao-init.py`'s handoff text (it registers the durable
  watchdog itself, so its semantics survive unchanged).
