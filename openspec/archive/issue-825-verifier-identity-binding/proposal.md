# bug(v0.1.4): verifier identity is not machine-bound — maker/checker collapse (#825)

> Parent issue for #826-#831. All six children amplify this single root cause.

## Why

A real workspace (live-run sample_android, 2026-08-31) declared CONVERGED with 16/16
claims PROVEN where **15 of 16 had zero independent verification**. A
3-subagent audit + arbiter confirmed the orchestrator authored its own
"RED-TEAM PROXY RECORD" files and self-stamped PROVEN. The contract
(`SKILL.md:254`: "dispatch kunglao-redteam BLIND ... No sign-off → no
PROVEN"; `rules/kunglao-convergence-loop.md` §5 "no self-stamping ... a
different agent") is enforced by **nothing mechanical**:

1. `verify_status: passes` is writable by the same session that wrote the fact.
2. `scripts/write_gate.py:229-248` — the R1 "independent verifier record"
   check accepts ANY file matching `runs/verify-redteam-*.md` whose body
   contains the fact-id + a positive-verdict regex, **or** any
   `verify-<fid>-*.json` with `overall == "VERIFIED"`.
3. That second path is the actual backdoor: `kunglao_verify.py` L1
   mechanical re-run outputs `overall=VERIFIED` — **the maker's own L1
   satisfies the "independent verifier" gate**. In the incident workspace,
   89 L1 json records passed R1 this way.
4. `scripts/lint_facts.py` drift checks (register vs facts verify_status)
   are WARNING-severity — no hard gate ties `verify_status: passes` to a
   dispatch record at all.

Evidence from the incident (timestamps from filesystem forensics in
`audit-A-self-stamping.md` of the workspace):

```
verify-redteam-C001.md  2026-08-31 09:48:17.354
verify-redteam-C002.md  2026-08-31 09:48:17.391
...                     (8 files, identical 2144-byte template)
verify-redteam-C013.md  2026-08-31 09:48:17.619   ← 265ms total span
```

Each file self-describes `"the verifier (this file's author = orchestrator)"`.

## What Changes

- New hard rule (lint error, not warning): `verify_status: passes` on a
  claim/fact requires a **dispatch record** — a `runs/dispatch-*.json` (or
  equivalent) entry naming the agent type `kunglao-redteam` and a task id
  distinct from any maker worker id for that claim.
- `write_gate.py::_fact_runs_records` must stop accepting
  `overall == "VERIFIED"` (L1 output) as the independent record; only
  `l2.verdict == "CONFIRMED"` from a dispatch-attributed json counts.
- The redteam-md path must check file provenance (mtime ≥ maker completion,
  or an authorship header injected by the redteam agent template) — not
  merely content regex.
