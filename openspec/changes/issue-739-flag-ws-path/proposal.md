# issue-739-flag-ws-path — flags are not workspace paths

## Why

`ws_layout.resolve_strict` honored an explicit arg unconditionally
(`Path(arg).resolve()`), so `heartbeat_touch --help` silently created a
literal `--help/` workspace in RC1 (re-labs/ctf-1, 03:45:17 — runs/,
.heartbeat.json and a log tree under a flag-named directory). The
#228 "never guess" discipline only guarded the no-arg path.

## What Changes

1. `resolve_strict` refuses dash-leading args LOUDLY (stderr guidance +
   exit 2 — the same discipline as the nothing-found face).
2. `resolve_quiet` treats a dash-leading arg as absent (its contract is
   silence) and degrades to the no-arg probe.
3. Real path args win exactly as before — the arg-wins contract is
   untouched.

## Out of scope

- A real argparse `--help` for individual scripts (the guard gives the
  loud refusal; per-script usage text is cosmetic follow-up).
