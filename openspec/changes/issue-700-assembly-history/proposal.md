# Assembly history: init-report archive rotation + per-item install events (#700)

## Why

Issue #700 field report (2026-08-25 lab): after a failed analysis-box
build, hours later "why is frida missing" was unanswerable — no record of
the failed install survived. The proposer's own re-review narrowed the
claim: #534's degrade_report already writes install-failed/declined
reasons into runs/.init-report.json phases *within one init cycle*, so
the original "zero difference afterwards" thesis is falsified. Two real
gaps survive (arbitration 2026-08-26, dev cb65c84 verified):

1. **Init-report overwrite loses history** — scripts/kunglao-init.py:250
   docstring self-declares "Idempotent: overwrites any prior report".
   The second init destroys the first's assembly-failure history — and
   the multi-round debugging case (install half-fails → re-run) is
   exactly when that history matters most.
2. **kunglao_log has no per-item install events** — the whole of
   kunglao-init.py carries only 4 emit calls (dispatch ×2,
   write_blocked ×2); toolchain_install.py carries 1 (unrelated). The
   runs/logs timeline cannot answer "which tool was attempted when".

Out of scope (arbitration): the issue's original
`runs/assembly-failures.jsonl` proposal — superseded by archive rotation
reusing the existing #534 report, plus events reusing the existing
kunglao_log channel. No new event schema (detail field only).

## What Changes

- `write_init_report` archives any prior report to
  `.init-report.{n}.json` (n increasing, newest = highest n; keeps the
  most recent `KUNGLAO_INIT_REPORT_KEEP`, default 5, older deleted;
  invalid env value falls back to default). One stderr line announces
  the rotation.
- `ask_then_install` emits three per-item events (registered in
  event_taxonomy.EMIT_ACTIONS, guarded fail-open):
  - `install_attempt {tool, via=plan.kind}` — after consent, before the
    plan runs
  - `install_failed {tool, detail=head of error}` — consented install
    that ran and failed
  - `install_declined {tool, reason}` — no-consent headless degrade AND
    the IDA mcp_url non-auto-installable degrade

Success remains observable as attempt-with-no-terminal-event (the
re-probe path is unchanged).
