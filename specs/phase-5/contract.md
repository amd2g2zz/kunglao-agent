# Phase 5 Contract — M3 VERIFY / M4 RECORD / M5 MONITOR (Track E)

Source documents (frozen sources, excerpts with line numbers):
- `docs/design/archive/module-design.md` (historical master design doc; #355: the `.research-tree-alignment/` workspace copy is no longer referenced)
  - §M0.2 signatures L40-50; M0.3 Event schema L53-72; M0.4 error handling L75-79; M0.5 test points L81-85
  - all of §M3 L236-306 (M3.1 L238-246; M3.2 L248-268; M3.3 L270-280; M3.4 L282-293; M3.5 L295-299; M3.6 L301-305)
  - all of §M4 L309-362 (M4.1 L311-319; M4.2 L321-333; M4.3 L335-341; M4.4 L343-349; M4.5 L351-355; M4.6 L357-361)
  - all of §M5 L365-432 (M5.1 L367-377; M5.2 L379-394; M5.3 L396-406; M5.4 L408-420; M5.5 L422-426; M5.6 L428-432)
- ready for reuse, unchanged: `scripts/loop_state.py::reconcile` (TEMP mtime → loop-state, L82-94), `scripts/convergence_health.py::assess` (L170-233), `scripts/active_intervention.py::find_help_requests/find_responses`, `scripts/backtrack_gate.py::parse_status/parse_backtrack` (L38-60), `hooks/worker_budget.py` maker-checker criteria (L268/L282-319), `scripts/hook_activation.py` heartbeat registration (`runs/.heartbeat.json` `last_tick_ts`, L195-235)

FROZEN @ phase-5, change conditions: ① first write a RED test proving the
current state does not satisfy the new contract ② change contract.md +
schemas/ ③ write back into one of the three master docs ④ all within the same
commit

---

## 1. Function signatures (frozen, original with line numbers)

### M3 VERIFY (§M3.2 L248-268)

```python
def l1_mechanical(fact: Fact, fixture: Path) -> Verdict:
    """parse_reproduce → run (read-only allowlist) → sha256 compare expected → PASS/FAIL (L251)"""

def l2_redteam(claim_id: str, ws: Path) -> RedteamVerdict:
    """dispatch kunglao-redteam (standalone subagent, BLIND) (L254)
    constraints: never read facts/F<NNN>/notes/worker-status; independent derivation;
          self-assertion before comparison;
          DIFF per disagreement; five angles; plan-to-execute; self-consistency across paths
    → CONFIRMED | REFUTED | UNVERIFIED-WITH-GAP"""

def lane_scheduler(facts: list[Fact], refutability: DepGraph) -> list[list[Fact]]:  # not landed this phase

def anchor_check(verdict: Verdict) -> bool:
    """PASS must carry anchors (raw byte offset + command + expected/actual); no anchor, no promotion (L263)"""

def verify(ws: Path, fact_id: str) -> VerifyOutput:
    """L1 → if PASS and semantics needed → L2 → anchor_check → write runs/verify-<ts>.json (L266)"""
```

### M4 RECORD (§M4.2 L321-333)

```python
def record_event(ws: Path, event: Event) -> int:
    """event_id = sha256(event_type+payload); idempotent (a duplicate returns the existing seq); atomic_append (L325)"""

def read_events(ws: Path, event_type: str | None) -> list[Event]        # L49 (M0.2)

def reconciler(ws: Path, n_rounds: int = 3) -> bool:                    # not landed this phase (E5.2 tested separately)
    """ledger replay into progress.txt/analysis_state.txt append (L328)"""

def summary_aggregator(worker_result: SummaryOfWork) -> dict:           # not landed this phase

def claim_migrator(ws: Path, claim_id: str, new_status: str, actor: str) -> tuple[bool, str]:  # contract blank
    """claim status migration (legality check); a non-orchestrator writing terminal → (False, reason)"""
```

### M5 MONITOR (§M5.2 L379-394)

```python
def heartbeat_check(ws: Path) -> tuple[bool, str]:
    """check tick_ts (< 35min) → alive/STALE; does not check activity_ts (L382)"""

def loop_reconcile(ws: Path) -> LoopState:
    """TEMP mtime → loop-state.json + event diff (L385)"""

def health_check(ws: Path) -> dict:
    """ledger trajectory → HEALTHY/STALLED/SPINNING + flatline/churn metrics (L388)"""

def tick(ws: Path) -> TickOutput:
    """compose: heartbeat→reconcile→help_watch→stuck_watch→health (L391)
    output: one-sentence status + next-step suggestion (LLM reads only)"""
```

### Landing map (contract-blank decisions)

| Design signature | This-phase landing | Note |
|---|---|---|
| file layout | `scripts/kunglao_verify.py` + `scripts/kunglao-verify.py` (thin wrapper); same for `kunglao_record.py`/`kunglao-record.py`; `kunglao-monitor.py` self-contained | the frozen tests use `from kunglao_verify import anchor_check` / `from kunglao_record import ...` direct imports — hyphenated filenames are not importable → logic lives in underscore modules, hyphenated files are CLI entries (same pythonpath resolution) |
| `lane_scheduler` | **not rebuilt** — fact-dependency lane parallelism is an orchestration-layer job; this phase's CLI verifies one fact at a time | M3.1 L243 submodule, not landed without test backing |
| `reconciler` / `summary_aggregator` | **not rebuilt** — E5.2 (Migrate) and digest aggregation left to later phases | M4.2 L328/L331; phase criteria E5.1/E5.3 cover Expand/Contract |
| `claim_migrator` return | `tuple[bool, str]` (ok, reason) — contract blank | landing: register status rewrite + terminal migration recorded as a ledger event |
| `l2_redteam` real dispatch | wrapper interface `l2_redteam(claim_id, ws, dispatcher=None)`; no dispatcher injected → `NOT-RUN` + gap note | real dispatch = orchestrator dispatching the kunglao-redteam subagent with `build_redteam_prompt` (BLIND, no maker context); tests inject a stub |
| `verify` output filename | `runs/verify-<fact_id>-<ts>.json` (ts without colons) | M3.2 L266 "verify-<ts>.json" — fact_id added so same-second multi-fact runs do not overwrite (contract blank) |
| L1 sha256 formula | `actual_sha256 = sha256(stdout.rstrip())`; if expected is 64-hex compare directly, otherwise `sha256(expected.strip())` | contract blank; trailing-newline normalization of reproduce output |
| reproduce parsing | `shlex.split` first token ∈ read-only allowlist → argv as-is (python→sys.executable); otherwise execute the whole string via `python -c` | M3.2 L251 "parse reproduce"; allowlist: python/python3/py/xxd/od/hexdump/cat/strings/file/grep/egrep/fgrep/sed/awk/sha256sum/md5sum/sha1sum/wc/head/tail/sort/uniq; python paths further reject write operations (`open('w')`/`.write(`/`os.remove` etc.), shell paths reject redirection (`>`/`>>`/`| tee`) |
| `needs_semantic` | frontmatter `needs_semantic: true` or `boundary_type: subjective_interpretation` → True, default False | M3.4 L288 "if semantics needed" contract blank |
| claim_id parsing | frontmatter `claim_id` takes priority; missing → `C-UNKNOWN` (allowed by the schema pattern) | contract blank |
| ledger path | `<ws>/ledger.jsonl` | M4.1 L315 "ledger.jsonl idempotent write" |
| `checksum` | `sha256(canonical JSON of the whole record except checksum)` | M0.3 L68 dataclass field, formula a contract blank |
| idempotency key | `event_id = sha256(event_type + canonical(payload))`, canonical = `json.dumps(sort_keys, separators=(",",":"))` | M0.3 L67 original |
| DEFERRED migration event | no dedicated event_type → register update only, no ledger entry | M4.3 L337-340 enum has no claim_deferred (contract blank) |
| `heartbeat_check` path | `runs/.heartbeat.json` `last_tick_ts`, threshold 35min | same source and threshold as worker_budget.check_heartbeat_alive (L505-559) |
| `loop_reconcile` | reuses `loop_state.reconcile`; diff against the previous `runs/loop-state.json` snapshot → `gone_events`; snapshot rewritten every tick | M5.2 L385; M5.5 L427 "no snapshot → treat all as NEW" |
| `stuck_watch` | in_progress and ≥20min without a valid backtrack (`continue/retry_different/escalate/redispatch`) | reuses backtrack_gate.parse_status/parse_backtrack, same default threshold |
| `help_watch` | worker-status files with unanswered help_request (answers matched by claim_id against heartbeat_actions.md) | reuses active_intervention.find_help_requests/find_responses |
| `health_check` | reuses convergence_health.assess; `NO_DATA` → `HEALTHY` (raw kept) | tick schema enum has no NO_DATA (contract-blank mapping) |
| `next` | mechanical chain: STALE heartbeat → re-register; SPINNING/STALLED → health action; help → respond; stuck → backtrack; gone → reconcile; idle → converged-check | M5.4 L418 "mechanically infer the next step" |

---

## 2. Output schema reference

- frozen structure: `schemas/verify-output.json` (M3.3 L272-280 field by field)
  - required 7 fields: `fact_id` / `claim_id` / `l1{verdict, actual_sha256, cmd}` / `l2{verdict, gaps}` / `anchors[{byte_offset, cmd, expected}]` / `overall`
  - `l1.verdict` ∈ PASS|FAIL; `l2.verdict` ∈ CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP|NOT-RUN; `overall` ∈ VERIFIED|REJECTED|PARTIAL
  - additional fields (additionalProperties allowed, not frozen-required): `l1.expected_sha256`, `l1.detail`
- frozen structure: `schemas/tick-output.json` (M5.3 L398-405 field by field)
  - required 9 fields: `ts` / `heartbeat` (alive|STALE) / `active_workers` / `stale_agents` / `gone_events` / `help_requests` / `stuck` / `health` (HEALTHY|STALLED|SPINNING) / `next`
  - additional fields: `heartbeat_detail`, `health_detail`
- frozen structure: `schemas/event.json` (M0.3 L66-72 field by field)
  - required 6 fields: `seq` / `event_id` / `source_module` / `event_type` (enum of 7 values) / `payload` / `checksum`; additional `ts` (added by this implementation, not required by M0.3)

## 3. State machine (original flow)

### M3.4 verify (L285-293)

```
verify(ws, fact_id):
  v1 = l1_mechanical(fact, fixture)
  if v1 == FAIL: return REJECTED            # L2 never entered
  if not needs_semantic(fact): return VERIFIED(v1)
  v2 = l2_redteam(claim_id, ws)             # kunglao-redteam standalone dispatch
  if v2 == CONFIRMED AND anchor_check: return VERIFIED
  if v2 == REFUTED: return REJECTED
  return PARTIAL(UNVERIFIED-WITH-GAP)
```

### M4.4 Expand→Migrate→Contract (L345-349)

```
Expand:   ledger written as a side-channel, old CLIs unchanged (zero behavior change)   ← this phase (E5.1: verify/record side-channel)
Migrate:  reconciler replays the old channel, N=3 rounds checksum zero drift → readers switch to the ledger   ← later phase
Contract: old channel demoted to read-only                           ← this-phase criterion E5.3 (claim_migrator blocks non-orchestrator terminal writes)
```

### M5.4 tick (L411-420)

```
tick(ws):
  hb = heartbeat_check(ws)
  ls = loop_reconcile(ws)                    # update loop-state + events (active/stale/gone)
  hi = help_watch(ws)                        # unanswered help_request
  st = stuck_watch(ws)                       # stuck worker
  hl = health_check(ws)                      # trajectory health
  next = decide_next(hb, ls, hi, st, hl)     # mechanically infer the next step
  return TickOutput
```

## 4. Test points (M3.6 L301-305 / M4.6 L357-361 / M5.6 L428-432 + this-phase RED list)

| Test point | Assertion | File |
|---|---|---|
| discriminative power (L303) | known PROVEN fact → PASS; a fake fact with tampered expected → FAIL; output passes verify-output.json | tests/test_verify_record_monitor.py::test_known_fact_pass_fake_fact_fail |
| anchor_check (L305) | anchor-less PASS → promotion refused (anchor_check → False) | same::test_anchor_check_blocks_no_anchor |
| idempotency (L359) | recording the same event twice → 1 entry, same seq | same::test_ledger_idempotent_same_event_once |
| TickOutput schema | heartbeat/active_workers/health/next fields pass tick-output.json | same::test_monitor_tick_output_schema |
| claim migration (L361) | a non-orchestrator writing terminal → refused | same::test_claim_migrator_blocks_worker_terminal |
| blind verification (L304) | the dispatch prompt carries no maker context (`prompt_is_blind` mechanical assertion, for stub injection in tests) | implemented in kunglao_verify.build_redteam_prompt / prompt_is_blind |
| L1 timeout / missing tool (L297) | timeout/missing → FAIL (never degrades to PASS) | implemented in run_reproduce (script-level, no dedicated test) |

## 5. Completion criteria

1. all new tests green + full regression green (`python -m pytest -q -p no:cacheprovider`): this phase's 5 + the original 143 do not regress (test_kunglao_init 4P+1S included)
2. `schemas/verify-output.json` / `schemas/tick-output.json` validate kunglao-verify / kunglao-monitor output via jsonschema
3. E5.1: verify/record are side-channel new CLIs (zero changes to kunglao.py and other old entries); E5.2 reconciler left for later; E5.3 the old channel's read-only-ness is expressed by the claim_migrator maker-checker gate
4. constraints: do not touch SKILL.md/references/hooks/kunglao.py/convergence_check.py/priority.py/priority_ratio.py/kunglao-decide.py/test_kunglao_init.py/test_contract_docs.py/test_suite_health.py/tools/; no git commit
