# Phase 3.5 Contract — kunglao-init (workspace initialization + re-init guard)

`FROZEN @ phase-3.5, change conditions: ① first write a RED test proving the
current state does not satisfy the new contract ② change contract.md +
schemas/ ③ write back into one of the three master docs ④ all within the same
commit`

Basis (layer-1 master spec, excerpts with line numbers, not transcribed):
- `kong-agent-module-design.md` (master): L25-26 store_atomic atomic write / L31 store_claim (claim-register.yaml read/write, human-auditable) / L48 record_event idempotent / L56 Claim schema / L77-79 M0.4 error handling / L224 hooks section idempotent rebuild / L448 kunglao.py the single orchestration entry, special operations via standalone CLIs (kunglao-init/verify/eval...)
- `docs/design/archive/DESIGN.md` §7 (executable work-tree spec; #355: the former `DESIGN.md` moved to docs/design/archive/): L98 every step idempotent (skip if exists and non-empty, no clobber) / L104 0.3 hook install idempotent / L105 0.4 scaffold idempotent / L110 0.9 claim seeding

## 1. Function signatures

`scripts/kunglao-init.py` — **standalone CLI, not a kunglao.py subcommand**
(module-design L448: "single orchestration entry; no subcommand parsing
(special operations via standalone CLIs: kunglao-init/verify/eval...)").

```
python kunglao-init.py <workspace> [--force] [--hooks-json <path>]
```

| Function | Signature | Responsibility (master provenance) |
|---|---|---|
| `main` | `main(argv=None) -> int` | argparse entry, calls run, wrapped in sys.exit |
| `run` | `run(ws: Path, force: bool=False, hooks_json: Path\|None=None) -> int` | state-machine entry: Phase 1 re-init check → resume / --force backup+rebuild / fresh initialization |
| `resume` | `resume(ws: Path, text: str) -> int` | resume mode: recompute state_hash, drift → stderr WARNING (exit 0) |
| `initialize` | `initialize(ws: Path, hooks_json: Path\|None) -> int` | Phase 2 scaffold + seed + idempotent hooks deployment; Phase 3 validation |
| `atomic_write` | `atomic_write(path: Path, text: str) -> None` | temp → rename atomic write (module-design L25-26 store_atomic) |
| `compute_state_hash` | `compute_state_hash(ws: Path, register_text: str\|None=None) -> str` | sha256(claim-register normalized content + facts/_INDEX.md content + facts/ file list concatenated name-sorted) |
| `normalize_marker` / `extract_hash` | `(text: str) -> str / str\|None` | normalize/read the state_hash field of the [initialized] marker (self-consistency hash) |
| `seed_claims` | `seed_claims(sample: str) -> list[dict]` | 3-5 sample-level seeds: C-001 sample overview / C-002 family attribution / C-003 packer (DESIGN L110 0.9) |
| `claim_register_text` | `claim_register_text(sample, sample_sha, state_hash) -> str` | full claim-register.yaml text: [initialized] marker header + claims body (Claim schema: module-design L56) |
| `detect_sample` | `detect_sample(ws: Path) -> tuple[str, str]` | first file in bins/ (name-sorted) → (filename, sha256), missing → ("unknown","") |
| `scaffold` | `scaffold(ws: Path) -> list[Path]` | create facts/ blockers/ runs/ + analysis_state.txt / global_plan.txt / claim_deps.yaml / facts/_INDEX.md / task_spec_snapshot.yaml; skip if exists and non-empty (DESIGN L105, L98) |
| `deploy_hooks` | `deploy_hooks(ws: Path, hooks_json: Path\|None) -> dict` | idempotent hooks deployment (E-init.2, DESIGN L104); target selection in §2 |
| `_patch_settings` | `_patch_settings(path: Path) -> int` | merge the hooks section into settings.json (other keys preserved), return the number of entries added |
| `_ensure` | `_ensure(entries, matcher, hook_file, hook_dir) -> tuple[list, bool]` | same matcher already has a hook command with the same name → skip (idempotent); otherwise append |
| `backup_register` | `backup_register(path: Path) -> Path` | backup before --force rebuild: `claim-register.yaml.bak-<ts>` (E-init.4) |

Error handling (module-design L77-79): read failures do not crash (missing
files take the branch path); settings.json parse failure → explicit
RuntimeError; writes go through atomic_write (L25).

## 2. Output

**State file `claim-register.yaml` (module-design L31: human-auditable)**:
first comment line carries the `[initialized]` marker + `state_hash=<hex>` +
`seeds=N` + `sample=<name>`; the body is the seed claims (id/status/
boundary_type/evidence_tier_attempted/promotion_attempts/depends_on, matching
the L56 Claim schema, with a title line).

**stdout (machine-readable, one line each)**:
- fresh init: `kunglao-init: initialized <ws> (seed_claims=3 sample=<name>)` + `kunglao-init: state_hash=<hex>` + hooks line (below)
- resume mode: `kunglao-init: resume — <ws> already initialized` (exit 0)
- --force: `kunglao-init: --force backup -> <backup-path>`
- hooks: deployed → `kunglao-init: hooks -> <target> (<n> entries, idempotent)`; skipped → `kunglao-init: hooks skipped — <reason>`

**stderr**: drift → `kunglao-init: WARNING state drift detected (recorded
<old>, computed <new>) — external edits present` (contains "drift"/"warn",
the test assertion point); validation failure → `FATAL`.

**exit code**: 0 = success (including resume / continuing after a drift
warning); 2 = Phase 3 validation failure (marker missing or seed < 3).

**Hooks deployment boundary (hard constraint)**: NEVER write the production
`~/.claude/settings.json`. Targets only: ① a copy named by `--hooks-json
<path>` (created if absent); ② `<workspace>/.claude/settings.json` (if it
exists); with neither → skip with a stated reason. Entry format matches
hook_activation.py: `{"type":"command","command":"python
<hooks-dir>/worker_budget.py"}` (POSIX paths,
PreToolUse+PostToolUse matcher=Agent, DESIGN L104).

## 3. State machine

```
run(ws):
  reg = ws/claim-register.yaml
  ├─ reg exists and not --force:
  │    └─ contains [initialized] → resume(ws, text)        # Phase 1 existence check
  │         ├─ extract state_hash → recompute compute_state_hash(ws)
  │         ├─ not equal → stderr WARNING drift (not silent; module-design L224 spirit: detect → warn)
  │         └─ print resume → exit 0 (touch no files, seeds not repeated)
  ├─ --force and reg exists → backup_register() → print backup path
  └─ initialize(ws, hooks_json)                             # Phase 2 fresh initialization
       ├─ scaffold (idempotent: exists and non-empty → skip, DESIGN L98/L105)
       ├─ detect_sample (first file in bins/)
       ├─ draft claim-register (empty hash) → compute_state_hash → write [initialized] marker (self-consistent)
       ├─ deploy_hooks (idempotent, DESIGN L104)
       └─ Phase 3 validation: marker present + seed count ≥ 3 → exit 0 / failure → exit 2
```

Four paths:
1. **First run**: scaffold → write seed register (3 claims) + marker → hooks (deployed if a target exists) → exit 0
2. **Resume**: marker hit → recompute hash and compare → no drift, resume / drift, WARNING then still resume → exit 0, register byte-for-byte unchanged
3. **Drift**: rerun after externally editing the claim-register → normalized hash mismatch → stderr contains "drift"/"warn", exit 0 (no overwrite)
4. **--force**: first `claim-register*.bak*` backup → rebuild register (new state_hash) → hooks idempotent (0 added) → exit 0

## 4. Test points (tests/test_kunglao_init.py)

| Test | Criteria (E-init) | Path covered |
|---|---|---|
| `test_kunglao_init_script_exists` | file exists and is runnable | — |
| `test_second_run_resumes` | first run writes the `[initialized]` marker + seeds; second run resumes with the `id: C-` count unchanged | path 1→2 |
| `test_hooks_idempotent` | rerun does not double-deploy hooks (skip passthrough when nothing to deploy) | path 2 (skip when no default deploy target) |
| `test_state_hash_drift_warns` | after editing the register, rerun output contains "drift"/"warn" | path 3 |
| `test_force_backs_up_first` | --force produces `claim-register*.bak*` before rebuilding | path 4 |

## 5. Completion criteria

- [ ] `python -m pytest -q -p no:cacheprovider` (under kunglao-agent/): all 5 kunglao-init tests pass (including design-permitted skips), zero regression in the pre-existing 138 passing cases
- [ ] the four state-machine paths (first/resume/drift/--force) behave per §3, drift warning contains "drift"/"warn"
- [ ] state_hash formula = sha256(claim-register normalized + facts/_INDEX.md + facts/ file list concatenated name-sorted), self-consistent (recomputing after writing the marker is unchanged)
- [ ] hooks never write `~/.claude/settings.json`; `--hooks-json` copy and workspace `.claude/settings.json` merge idempotently
- [ ] never touched: bins/ binary content (read filenames/hashes only), production settings.json, hooks/ directory
