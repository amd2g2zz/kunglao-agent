## Why
The heartbeat loop is still a fixed cron. `cadence_advisor` / `slot_monitor` / `heartbeat` are hand-written constants; no alternative is ever chosen, no propensity is logged, and no wake decision can be evaluated off-policy (one session: 156 scheduled fires, 94% of gaps in [4,6] minutes). The design note already says the right thing — "the cron heartbeat demotes to a true watchdog" — and the implementation inverts it: the watchdog is the driver, self-maintenance costs more than the dispatches it exists to serve.

## What Changes
The wake decision becomes an ACTION exactly like a dispatch:

- the scheduling five (`sleep` / `wake_on` / `probe` / `close_loop` / `none`) register at the orchestration level in the action vocabulary (`scripts/action_space.py`, tagged `scheduling`; `none` is the null action, cost 0, value 0);
- `scripts/intelligent_scheduling.py` selects with a Gumbel top-k WITHOUT replacement (exact Plackett-Luce propensities), width k = min(free_slots, f(entropy));
- every decision is recorded (`runs/.scheduling-decision.json`) and logged (one `kind=scheduling` row on the signal stream) with `{action, propensity, source, k, null_propensity, budgets}`; `source` follows the dispatch trichotomy sampled | declared | none;
- every decision carries the null action's own propensity at the same point — the do-nothing baseline any timer action is measured against;
- the three budgets (tokens / tool_calls / verify_calls) ride every decision, so "how often" has a price;
- the fixed cron path is DEMOTED to an armed watchdog (event-first, polling as fallback), never deleted — default-safe.

Non-goals: no trigger rules (a threshold branch is exactly the hand-written constant this card removes); no tick-loop rewiring (the decision module is the recorded seat, the orchestrator applies); the learned prior itself is the next slice — day-one priors are flat, and the signal stream this card writes is what updates them.
