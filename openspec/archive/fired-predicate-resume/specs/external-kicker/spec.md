## ADDED Requirements

### Requirement: The external kicker SHALL build the kick prompt from fired predicates over logged state, never from narrative files

`scripts/external_kicker.py::build_resume_prompt(ws, *, max_chars=4000, max_open_claims=15) -> str` SHALL assemble the RECOVER prompt from mechanical logged state only: the last SNAPSHOT row of `.convergence_ledger.jsonl` (round number = count of SNAPSHOT rows; `ts`, `decision`, `open_ids`, `active_workers`, `blockers`, `facts_total`), the OPEN / PARTIALLY-VERIFIED claims of `claim-register.yaml` (status in PARTIAL_STATUSES or OPEN; IN_PROGRESS excluded), the PARTIAL facts of `facts/_INDEX.md` (2nd `|` field in PARTIAL_STATUSES), and the in-progress `runs/worker-status-*.md` files (last `status:` line == `in-progress`, regardless of mtime). The prompt SHALL contain the round line, the open-claim ids (register order first, then any ledger `open_ids` not already listed, deduped), the active worker ids, ALL blocker ids, the facts total, and the partial fact ids. The function SHALL NOT read `progress.txt` or `analysis_state.txt` in any code path.

#### Scenario: resume prompt carries the ledger last-row open_ids (fired predicate)
- **GIVEN** a workspace whose `.convergence_ledger.jsonl` has several SNAPSHOT rows and whose last SNAPSHOT row has `open_ids: ["C-201", "C-003"]` and a `decision` of `DISPATCH`, and no claim-register.yaml exists
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt contains both `C-201` and `C-003`, the round number equals the SNAPSHOT row count, and the ledger `decision` value appears in the prompt

#### Scenario: resume prompt excludes progress.txt narrative
- **GIVEN** a workspace with a `progress.txt` whose content includes the sentence "我正在分析 C-007"
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt does not contain the sentence "我正在分析 C-007" (nor any other text read from `progress.txt`)

#### Scenario: no open claims yields the CONVERGED directive, not an empty prompt
- **GIVEN** a workspace whose ledger last SNAPSHOT row has `open_ids: []` and whose claim-register.yaml has no OPEN or PARTIALLY-VERIFIED claims
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt is non-empty and contains the exact text `CONVERGED, verify report`

#### Scenario: multiple blockers are all listed
- **GIVEN** a ledger last SNAPSHOT row whose `blockers` list contains `B-01` and `B-02`
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt lists both `B-01` and `B-02`

#### Scenario: partial facts and in-progress workers are surfaced
- **GIVEN** a `facts/_INDEX.md` with a `F042 | PARTIAL | ...` line and a `runs/worker-status-C301.md` whose last `status:` line is `in-progress`
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt contains `F042` and `C301`

### Requirement: The resume prompt SHALL enforce a length cap with priority-ordered truncation of the open-claims list

`build_resume_prompt` SHALL keep the assembled prompt at or below `max_chars` characters and SHALL list at most `max_open_claims` open-claim ids. When the open-claims list exceeds `max_open_claims`, or the assembled prompt exceeds `max_chars`, the SHALL keep the highest-priority claim ids — ordered by `priority.rank_claims` (score descending), with unranked ids appended in register order, falling back to register order when the priority module is unavailable — and SHALL append an explicit truncation marker such as `(+N more truncated by priority)` so the fresh session knows the list is a top-N.

#### Scenario: over-limit claim lists are truncated by priority
- **GIVEN** a workspace with 20 OPEN claims where `C-PRIMARY` answers a primary question and 19 others do not, and `max_open_claims=5`
- **WHEN** `build_resume_prompt(ws, max_open_claims=5)` is called
- **THEN** the returned prompt lists exactly 5 claim ids, includes `C-PRIMARY`, excludes at least one lowest-priority id, and contains the truncation marker

#### Scenario: the hard character cap is never exceeded
- **GIVEN** 20 OPEN claims and `max_chars=500`
- **WHEN** `build_resume_prompt(ws, max_chars=500)` is called
- **THEN** `len(prompt) <= 500` and the truncation marker is present

### Requirement: The resume prompt SHALL tolerate missing or malformed state files

`build_resume_prompt` SHALL return a usable non-empty prompt when the ledger is missing, empty, or contains non-JSON lines (skipping unparseable lines), when `claim-register.yaml` is missing, when the last SNAPSHOT row lacks `blockers` or `facts_total` (blockers fall back to a scan of `blockers/*.md` excluding INVALIDATED; facts_total falls back to counting `facts/F*.md`), and when `facts/_INDEX.md` or worker status files contain non-UTF8 bytes (read with `errors="replace"`). Round number SHALL be 0 when no SNAPSHOT row parses.

#### Scenario: missing ledger still yields a state prompt
- **GIVEN** a workspace with no `.convergence_ledger.jsonl` but a claim-register.yaml with one OPEN claim
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt is non-empty, contains the OPEN claim id, and does not crash

#### Scenario: malformed ledger lines are skipped
- **GIVEN** a `.convergence_ledger.jsonl` whose first line is `not-json{` and whose second line is a valid SNAPSHOT row
- **WHEN** `build_resume_prompt(ws)` is called
- **THEN** the returned prompt reflects the valid SNAPSHOT row and does not crash

### Requirement: The external kicker SHALL deliver the resume prompt on kick

`scripts/external_kicker.py::tick()` SHALL build the kick prompt with `build_resume_prompt(workspace)` (the fired-predicate alternative) instead of `heartbeat_loop_prompt.build_prompt(ws)`, staging it at `runs/.kicker-prompt.txt` and delivering it via stdin to the detached fresh session exactly as before. `heartbeat_loop_prompt.build_prompt` SHALL remain available for its own CLI.

#### Scenario: the kick stages the resume prompt
- **GIVEN** a dead session (heartbeat stale) with no fresh in-progress workers
- **WHEN** `tick(workspace, dry_run=True)` runs
- **THEN** `runs/.kicker-prompt.txt` exists and its content starts with the resume-prompt round line (`你正在收敛循环第`)
