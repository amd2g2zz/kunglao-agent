# design — issue-460-intake-battery

## Verified anchors (2026-10-02, branch feat/intake-battery-460 off origin/dev 79521d9a)

| Question | Actual | Drift |
|---|---|---|
| Where intake hangs the promise | `scripts/kunglao-init.py::run` — `if not skip_toolchain:` block at the #813 promise (`intake_promise.build(report, task_spec, ws)` → `apply`); WARN-tier: promise failure = ERROR line + `kunglao_log.emit(env_incident)`, never an init failure; `target_name` (the aligned `bins/` file), `lane`, `report`, `task_spec` all in scope | none |
| The probe contracts | die: `tools/static/die_probe.py` CLI (`--binary` + `--die/$KUNGLAO_DIE/PATH` resolution, `--out FILE`, `--timeout N` per call, three-state exit 0/1/2; `--out` payload written whenever args validate, `call_errors` carried inside; exit 2 = diec missing, NO file). apkid: `scripts/apkid_scanner.py::run(ws, apk)` library face — never raises, ALWAYS writes `evidence/apkid.json` (status ok/unavailable/error; `_apkid_usable` = status ok), `_run_scan` bounded 120 s | none |
| What mining consumes | `feature_mining._probe_outputs(spec, ev_dir)` reads `evidence/die.json` (`_die_usable` → usable/detected_packer/entropy_max) + `evidence/apkid.json` (`_apkid_usable` → usable/packers/obfuscators) + `promise.prescan.{die,apkid}.state`; `probe_outputs` schema is exactly {die, apkid} (pinned by `validate_row`) | none |
| The capability-fact chain (Part B) | `intake_promise._prescan`: toolchain item (PASS→available/WARN→degraded/FAIL→missing) > host presence > **probe-evidence presence** > missing; `_probe_evidence_present` currently counts ANY parseable JSON as present; spec text says "probe-evidence presence" (the "parseable" wording is design prose, not spec) | parseable over-counts (fold F1) |
| Shelf offer for a 3rd entropy/stat probe | `tools/_INDEX.yaml` cost_tier=probe: yara-gen, die-probe, opaque-pred, measure-cold-start, sanitize-text — no standalone entropy/stat binary probe; entropy/stat faces are die-probe's own `-e` call (per-section + total entropy), overlay-scan/pe-analyze/strings-classify (all cost_tier=cheap, none feeds `probe_outputs`) | none |
| Live-run reality | the feature-mining fixture's `e2e-ws-b` (a js-bundle target) historically carries BOTH die.json and apkid.json — live runs already point both identification probes at whatever the target is; the probes self-classify (die negative-finding, apkid non-APK error) | none |
| Impact (gitnexus CLI, index @39cd16f — stale vs branch) | `_prescan` upstream = CRITICAL (127 symbols, transitive through the init flow into compose/verifier processes); the actual edit target `_probe_evidence_present` has exactly ONE direct caller (`_prescan`) and the change refines only the chain's LAST fallback branch | disclosed: CRITICAL by closure, 1-caller refinement |

## Decision 1: the battery is die-probe + apkid-prescan (2 probes); the entropy slot is served by die-probe's own entropy call

Owner ruling allows 2-3 probes with an entropy/stat slot "if a shelf
tool offers it". The shelf offers NO standalone entropy/stat probe of
its own contract (the cost_tier=probe set is yara-gen / die-probe /
opaque-pred / measure-cold-start / sanitize-text). Entropy IS a
first-class battery output already: die-probe's dedicated `-e` call
emits per-section + total entropy, which mining lifts into
`probe_outputs.die.entropy_max`. Adding a third tool (e.g.
strings-classify, cost_tier=cheap) would produce evidence with NO
mined consumer — `feature-table/1`'s `probe_outputs` is exactly
{die, apkid} (schema-pinned), so a third file would violate this
card's own minability requirement and grow unmined surface. Fold: the
battery is 2 probes; entropy rides die-probe.

## Decision 2: WHEN — inside init's `not skip_toolchain` block, immediately BEFORE the #813 promise block

"Before the first claim dispatch" is satisfied anywhere in init; the
precise slot is chosen for coherence: probe FIRST, then record. With
the battery before `intake_promise.build`, the promise's
evidence-presence fallback and `_obfuscation_prior` (which reads
`evidence/apkid.json` summary.obfuscator — the #692 WP6 deobf-prior
key) see fresh t=0 artifacts, so run #1 already carries a populated
obfuscation prior instead of an empty one. The reverse order would
leave the promise blind to the artifacts the same init pass just
produced. Both orders are capability-accurate in every realistic
type/tool combination (the toolchain item dominates the chain), but
probe-then-record is the honest t=0 snapshot.

## Decision 3: failure semantics — each probe degrades independently; the battery never blocks init

- die: tool missing (CLI exit 2) → NO evidence/die.json + an absent
  row (reason: exit + stderr guidance). Probe ran with a negative
  finding (exit 1) → evidence WRITTEN (payload with `call_errors`)
  + a ran/negative row; `_die_usable`-based mining records
  unusable — the probe's own three-state contract IS the semantics.
- apkid: `apkid_scanner.run` never raises and always writes
  (unavailable = tool missing, error = non-APK/invocation failure);
  the battery row mirrors the status; unusable statuses count as
  absent for facts and mining (Decision 5).
- The battery function itself catches everything per probe and never
  raises; the init wiring additionally wraps the call in the promise
  block's pattern (WARN-tier ERROR + `env_incident`) so even an
  unexpected defect cannot refuse an init. Instruments degrade, they
  don't gate.

## Decision 4: outputs land exactly where the probe contracts expect

`evidence/die.json` via the die CLI's own `--out` (one writer: the
probe); `evidence/apkid.json` via `apkid_scanner.run` (its contract);
plus the battery ledger `evidence/intake-battery.json`
(schema `intake-battery/1`: `sample`, `lane`, one row per probe with
`ran`, `outcome` ∈ produced/absent, `evidence` path-or-null,
`reason`). The ledger is the instrument's audit face — what ran, what
it produced, why anything is absent (the #813 "never skip silently"
discipline applied to the battery).

Faces: die via CLI subprocess (its module import inserts
`tools/static` into `sys.path` — the #863 shadow risk; a subprocess
isolation avoids the side effect and exercises the real CLI contract);
apkid via the library face (`run()` is the documented never-raise
entry). Both probes run over the ALIGNED `bins/` sample whenever one
exists; no sample (non-malware lane) → explicit absent rows
(lane-aware no-op, the `_prescan_obligation` idiom). Applicability
lives in the probes' own contracts, not in battery-side rules — live
runs already point both probes at any target kind and the probes
self-classify.

## Decision 5 (fold F1): capability facts derived from probe evidence require USABLE evidence

Part B's `_probe_evidence_present` counts any parseable JSON as a
capability fact. Once the battery writes fail-open artifacts
(apkid `status: unavailable` when the tool is missing), a promise
built after it would record the capability as AVAILABLE on
unusable evidence — exactly the lie this card's failure semantics
forbid ("probe failure → the capability fact records absent"). Fold:
the fallback requires usable evidence (die: `_die_usable`; apkid:
`status == "ok"`, both reused from `difficulty_calibration` — the
single usability source Part A already trusts). The Part B SPEC text
("probe-evidence presence") is satisfied and refined; the design
PROSE said "parseable" and is superseded here, disclosed. One Part B
test fixture gains `status: ok` (its simulated artifact was always
meant to be a produced one); a new pin covers the unavailable case.

## Decision 6: unconditional — no flag, no dispatch behavior

The battery is not behind `KUNGLAO_PREDICT_BEFORE_TRY`: the flag
gates prior-informed SELECTION (a behavior); the battery is evidence
PRODUCTION (an instrument). Flag-gating it would starve the very A/B
re-evaluation the activation waits on (no battery-fed rows while
off). The battery orders nothing, gates nothing, consumes no acts;
the first-claim dispatch flow is untouched.

## Decision 7: bounded cost

die: battery passes `--timeout 30` (per call; the CLI default 120×5
is an agent-run budget, not an intake budget) + a subprocess backstop
of `5×30+30` s. apkid: the library face's existing 120 s bound. Both
constants are named module constants (no env knobs — ADR-001: no
runtime-tunable constants without replay evidence; operators re-run
the CLI face with `--timeout` for one-off adjustments).

## Design review (in-session adversarial pass, pre-implementation)

**Process disclosure**: no subagent-dispatch tool exists in this
session (tool surface: Bash/Read/Grep/Glob/Write/Edit only; the
gitnexus/MCP servers report connection failures). The review ran as a
dedicated in-session adversarial pass against the exact contracts
named above — the same deviation the merged Part B change disclosed
and the review gate accepted. The pre-merge review (tasks 5) repeats
the disclosure.

Verdict: FAIL → folded (all folds applied above BEFORE any test or
code):

- **F1 (MEDIUM)** — battery-written fail-open artifacts would flip
  the promise's evidence-presence fallback to "available" on
  unusable evidence, violating the card's own failure semantics in
  BOTH battery orderings (t=0 and re-init). Fold: Decision 5
  (usable-evidence requirement, usability rules reused from
  difficulty_calibration).
- **F2 (MEDIUM)** — a third entropy/stat probe would emit unmined
  evidence (probe_outputs is schema-pinned to {die, apkid}), growing
  surface with no consumer while the minability requirement demands
  the opposite. Fold: Decision 1 (2 probes; entropy rides die's
  `-e` call).
- **F3 (LOW)** — battery-side applicability rules (suffix sniffing)
  would re-derive what the probe contracts already encode
  (three-state exits, non-APK error) and would have mis-skipped die
  on apk targets that live runs demonstrably probe. Fold: Decision 4
  (applicability lives in the probes).
- **F4 (LOW)** — importing `die_probe` as a library face inserts
  `tools/static` into `sys.path` (the #863 "common" shadow risk).
  Fold: CLI subprocess face for die.
- **L-notes (recorded, no fold)** — the toolchain apkid
  recommendation prose ("agent to run on first claim") becomes
  redundant on battery-fed workspaces but stays: it is a
  recommendation face, not a rule, and rewriting it is out of this
  card's minimal scope. Re-init re-runs the battery (idempotent
  overwrite of evidence) — consistent with the promise/calibration
  blocks, disclosed.
