# web domain index (tool layer)

> Domain: browser/JS reverse-engineering tool face. When a worker is dispatched to web/JSVMP tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml). Methodology depth lives in the knowledge card [references/re-library/jsvmp-triage.md](../references/re-library/jsvmp-triage.md).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `jsvmp-triage` | Three-feature JSVMP/VMP triage CLI (verdict = three-of-two votes) | Read when a deobfuscated web bundle may hide a bytecode VM; not a proof — runtime trace confirmation stays with the operator |

## Three-feature thresholds

| Feature | Signal | Threshold |
|---|---|---|
| F1 | big consumed integer/string array | ≥ 100 literal items (`MIN_ARRAY_ITEMS`) |
| F2 | dispatch switch in an infinite loop | ≥ 8 distinct numeric cases (`MIN_CASE_COUNT`) |
| F3 | semantic-free case bodies | ratio ≥ 0.9, **and** a case table exists (`case_bodies_found`) |

Verdict: `votes = F1+F2+F3`; suspected ⇔ votes ≥ 2; confidence high(3/3) / medium(2/3) / low. F3 anchored on `case_bodies_found` — absence of a case table cannot vote via a hollow 1.0 ratio (#884).

## Contract entries

### jsvmp-triage

- **Purpose**: Mechanically answer whether an ALREADY-DEOBFUSCATED bundle (wakaru/webcrack output) carries a bytecode VM — big consumed array + dispatch-switch loop + stack-op handler bodies — so AST recovery stops and the operator switches to the instruction-trace methodology.
- **Usage**:
  ```bash
  python tools/web/jsvmp_triage.py <file.js> [more.js ...] --json
  ```
- **Inputs**: One or more deobfuscated `.js` file paths; `--json` for the machine verdict.
- **Outputs**: JSON verdict per file: `vmp_suspected` / `votes` / `confidence` (high|medium|low) + per-feature evidence (`f1_bytecode_array`, `f2_dispatch_loop`, `f3_semanticless_handlers.ratio` + `case_bodies_found`), `signals` lines, advisory `note`.
- **exit code**: 0 = triage completed (advisory posture — the verdict lives in the JSON, a miss is still exit 0, mirroring think_seat); 1/2 unused (reserved, not emitted).
- **when_not**: Not a proof of VMP — runtime confirmation requires a single-generation opcode/stack trace (CP3 of the trace methodology); use on already-deobfuscated bundles, not raw minified input. Consistent with _INDEX.yaml when_not.
