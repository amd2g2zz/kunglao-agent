# Design — assembly history (#700)

## D1: archive rotation lives inside write_init_report

The rotation happens immediately before the fresh atomic_write, inside
`write_init_report` — not at call sites — so every writer path (six init
phases, any future caller) inherits it. The helper is named
`archive_previous_init_report(target)` and returns the archive path (or
None when nothing rotated); it never raises (history rotation must not
break init — same fail-open class as the report write itself).

Naming: `.init-report.1.json`, `.init-report.2.json`, … newest = highest
n. On rotation the current `.init-report.json` moves to n = max+1 (1
when no archives exist). Pruning deletes archives beyond the KEEP limit,
oldest first; individual unlink failures are swallowed (best effort).

## D2: KEEP is env-tunable, invalid falls back

`KUNGLAO_INIT_REPORT_KEEP` (int ≥ 1, default 5). Parse failures,
zero/negative → default, silently — a mistyped env var must not break
init. Fail-open matches the surrounding write surface.

## D3: three events, existing channel, no new schema

`kunglao_log.emit(ws, actor="toolchain_install", action=…, tool=<item
name>, detail=…)` — the existing kwarg surface already has tool and
detail slots; nothing in the event schema changes. Three actions
registered in EMIT_ACTIONS (alphabetical, anchor test requires
sorted+unique):

- `install_attempt` — detail `via <plan.kind>` (install / elevation /
  set-env / manual / mcp_url modes visible from the plan without a
  second resolve_install call)
- `install_declined` — no-consent headless degrade AND the IDA mcp_url
  branch (both are "no real user choice" declines per #451 wording
  discipline; detail states which)
- `install_failed` — detail = first line of err-or-out, capped at 120
  chars (head-of-error per issue acceptance; full stderr stays in the
  operator guidance already printed)

## D4: fail-open at the call site, not just inside emit

emit() never raises by contract, but the call sites wrap in
`try/except Exception: pass` anyway — the guarded-helper pattern
established by hypothesis_seeder (#669). The install loop must never
abort because observability broke.

## D5: success is the absence of a terminal event

attempt → (failed | declined | silence). Silence + re-probe PASS is
success. Adding an install_ok face was rejected: the re-probe already
reports outcome, and a fourth word buys no query the timeline cannot
already answer (YAGNI; also keeps EMIT_ACTIONS growth at +3).

## D6: what this deliberately does NOT do

- No `assembly-failures.jsonl` (superseded — the #534 report IS the
  per-cycle record; rotation makes it durable across cycles).
- No resume-brief parser changes: the rotation stderr line is the
  pointer; digest/resume consumption of archives is a follow-up if a
  consumer asks (issue acceptance listed "resume brief 显示装配失败史"
  as the proposer's narrowed form — the archive files + one-line pointer
  satisfy "可读"; a dedicated brief section can ride #718's vocabulary
  work if still wanted).

## Risks

- glob-based n detection could collide with a user-created
  `.init-report.abc.json` — the regex accepts digits only; non-numeric
  siblings are ignored, never deleted.
- Windows rename-over-existing: we always move to a fresh n (max+1), so
  `replace()` never targets an existing file (except the pathological
  manually-placed collision — swallowed by the never-raises guard).
