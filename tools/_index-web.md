# web domain index (tool layer)

> Domain: browser/JS reverse-engineering tool face. When a worker is dispatched to web/JSVMP tasks, read this file first, then load on demand. Contract field meanings are in [README.md](README.md); the machine contract is [_INDEX.yaml](_INDEX.yaml). Methodology depth lives in the knowledge card [references/re-library/web/vm/jsvmp-triage.md](../references/re-library/web/vm/jsvmp-triage.md).

## Tool catalog

| Tool | Purpose (one-liner) | When to read / when not |
|---|---|---|
| `jsvmp_triage` | Three-feature JSVMP/VMP triage CLI (verdict = three-of-two votes) | Read when a deobfuscated web bundle may hide a bytecode VM; not a proof — runtime trace confirmation stays with the operator |
| `js_obfuscation_detect` | Obfuscation-technique inventory + routing to the registered next tool | Read FIRST on a raw minified bundle to route (packer → unbundle → deobfuscate → VMP triage); advisory only — no transforms, no family proof |

## Three-feature thresholds

| Feature | Signal | Threshold |
|---|---|---|
| F1 | big consumed integer/string array | ≥ 100 literal items (`MIN_ARRAY_ITEMS`) |
| F2 | dispatch switch in an infinite loop | ≥ 8 distinct numeric cases (`MIN_CASE_COUNT`) |
| F3 | semantic-free case bodies | ratio ≥ 0.9, **and** a case table exists (`case_bodies_found`) |

Verdict: `votes = F1+F2+F3`; suspected ⇔ votes ≥ 2; confidence high(3/3) / medium(2/3) / low. F3 anchored on `case_bodies_found` — absence of a case table cannot vote via a hollow 1.0 ratio (#884).

## Contract entries

### jsvmp_triage

- **Purpose**: Mechanically answer whether an ALREADY-DEOBFUSCATED bundle (wakaru/webcrack output) carries a bytecode VM — big consumed array + dispatch-switch loop + stack-op handler bodies — so AST recovery stops and the operator switches to the instruction-trace methodology.
- **Usage**:
  ```bash
  python tools/web/jsvmp_triage.py <file.js> [more.js ...] --json
  ```
- **Inputs**: One or more deobfuscated `.js` file paths; `--json` for the machine verdict.
- **Outputs**: JSON verdict per file: `vmp_suspected` / `votes` / `confidence` (high|medium|low) + per-feature evidence (`f1_bytecode_array`, `f2_dispatch_loop`, `f3_semanticless_handlers.ratio` + `case_bodies_found`), `signals` lines, advisory `note`.
- **exit code**: 0 = triage completed (advisory posture — the verdict lives in the JSON, a miss is still exit 0, mirroring think_seat); 1/2 unused (reserved, not emitted).
- **when_not**: Not a proof of VMP — runtime confirmation requires a single-generation opcode/stack trace (CP3 of the trace methodology); use on already-deobfuscated bundles, not raw minified input. Consistent with _INDEX.yaml when_not.

### js_obfuscation_detect

- **Purpose**: Inventory which obfuscation techniques a JS bundle carries (packer bootstrap, string-array + rotation, control-flow flattening, opaque predicates, dead-code injection, bundler markers, aaencode face-text, hex-renamed identifiers) with per-technique count evidence, then recommend the registered next tool.
- **Usage**:
  ```bash
  python tools/web/js_obfuscation_detect.py bundle.min.js
  ```
- **Inputs**: One or more raw or deobfuscated `.js` file paths (batch-capable).
- **Outputs**: JSON report per file: `techniques` [{name, confidence, evidence}] + `recommendation` {route, next_tool, why} (routes: unpack-first → webcrack-deobfuscate; unbundle; webcrack-deobfuscate; vmp-triage → jsvmp_triage; sandbox-decode → js_env_diagnose; direct-read).
- **exit code**: 0 = every file analyzed / 2 = any missing, empty, or undecodable path (fail loud — errors on stderr; reports still print for good files).
- **when_not**: Advisory routing only — performs no transforms and proves no family; run the routed registered tool for the real work (consistent with _INDEX.yaml when_not).
