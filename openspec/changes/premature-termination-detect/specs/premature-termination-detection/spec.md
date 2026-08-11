## ADDED Requirements

### Requirement: detect SHALL flag the 4 premature-termination fingerprints with evidence spans

`detect(transcript, task_text=None)` SHALL scan the `transcript` text (the
orchestrator's closing declaration) for exactly 4 fingerprints — F1
self-anchoring, F2 self-invented tiering, F3 cost-semantic drift, F4 false
completion — and return a dict. The function signature SHALL be
`detect(transcript: str, task_text: str | None = None) -> dict`. The returned
dict SHALL carry keys `fired_count` (int), `fired_ids` (list of the fired
fingerprint ids, e.g. `["F1","F2","F3","F4"]`), and `fingerprints` (list of
per-fingerprint dicts each carrying `id`, `name`, `fired` (bool), `evidence`
(list of `{pattern, span}` dicts naming the regex and the matched substring),
and `note` (str)).
The detector SHALL use regex/keyword heuristics ONLY (no LLM call, no network).
It SHALL read NO workspace state — only the `transcript` text and the optional
`task_text`.

#### Scenario: regression fixture fires all 4 fingerprints
- **GIVEN** the transcript is the issue #54 现象段 verbatim excerpt (containing "Substantive task complete", "备注级（记录即可）", "$52.85 — informational", "Deferred (#10 ... #12) — queued", and the task echo `任务原文：「...全面分析」`)
- **WHEN** `detect(transcript)` is called with no explicit task_text (recovered from the 任务原文 marker)
- **THEN** `fired_ids` equals `["F1","F2","F3","F4"]` and each fingerprint's `evidence` list is non-empty with `span` values containing the telltale phrases

#### Scenario: clean genuine completion fires zero fingerprints
- **GIVEN** a transcript "All 5 claims PROVEN, 0 open items remaining. Done — the user's 'comprehensive analysis' (全面分析) goal is met." with task_text "comprehensively re-analyze every gap"
- **WHEN** `detect(transcript, task_text)` is called
- **THEN** `fired_count` equals 0 and `fired_ids` equals `[]`

#### Scenario: F1 isolation — self-summary phrase + task anchor absent
- **GIVEN** transcript "Substantive task complete. Stopping here is appropriate." and task_text "comprehensively re-analyze every gap"
- **WHEN** `detect(transcript, task_text)` is called
- **THEN** F1 `fired` is True and F2, F3, F4 `fired` are False

#### Scenario: F2 isolation — tier keyword + open-item ref, no completion
- **GIVEN** transcript "G4, G5, G6 marked 备注级（记录即可）."
- **WHEN** `detect(transcript)` is called
- **THEN** F2 `fired` is True and F1, F3, F4 `fired` are False

#### Scenario: F3 isolation — cost figure + informational qualifier
- **GIVEN** transcript "Cost ~$52.85 — informational."
- **WHEN** `detect(transcript)` is called
- **THEN** F3 `fired` is True and F1, F2, F4 `fired` are False

#### Scenario: F4 isolation — completion + open-items-remaining, no tier
- **GIVEN** transcript "task complete. Items remaining, queued for later."
- **WHEN** `detect(transcript)` is called
- **THEN** F4 `fired` is True and F1, F2, F3 `fired` are False

### Requirement: F1 self-anchoring SHALL require task_text and degrade to indeterminate without it

`detect` SHALL fire F1 iff (a) a self-summary done-phrase
(`substantive\s+(task\s+)?complete`, `stopping\s+here\s+is\s+appropriate`,
`run\s+is\s+done`, `task\s+complete`, `mission\s+complete`, or the CJK
`任务完成`) is present in the agent region, AND (b) the `task_text` content
anchors (CJK runs of 3 or more chars and ascii tokens of 5 or more chars,
minus a documented stoplist of grammar words) are absent from the agent region.
The agent region SHALL be the transcript with task-echo lines removed (lines
matching `^\s*(任务原文|用户|user|task|instruction|原指令)`, case-insensitive).
When `task_text` is neither provided nor extractable from the transcript, F1
SHALL report `fired=False` with a `note` containing the word `indeterminate` —
it SHALL NOT fire on the self-summary phrase alone.

#### Scenario: task_text recovered from marker fires F1
- **GIVEN** a transcript containing `任务原文：「全面分析」` on one line and "Substantive task complete." on another, with no explicit task_text
- **WHEN** `detect(transcript)` is called
- **THEN** F1 `fired` is True (the marker-recovered task_text grounds the check)

#### Scenario: no task_text and no marker yields indeterminate F1
- **GIVEN** transcript "Substantive task complete." with no task_text and no extraction marker
- **WHEN** `detect(transcript)` is called
- **THEN** F1 `fired` is False and F1 `note` contains `indeterminate`

#### Scenario: task anchor echoed in the declaration suppresses F1
- **GIVEN** transcript "Comprehensive re-analysis done — task complete." with task_text "comprehensively re-analyze"
- **WHEN** `detect(transcript, task_text)` is called
- **THEN** F1 `fired` is False (the declaration echoes the user's anchor)

### Requirement: F3 SHALL require a cost qualifier and F4 SHALL exclude zero-open phrasing

F3 SHALL fire iff a cost figure (`[\$￥]\s?\d+(?:\.\d{1,2})?`) co-occurs with a
cost qualifier (`informational`, `info[- ]?only`, `for[- ]?reference`, CJK
`仅.{0,3}信息`, `参考`) within the same sentence (delimited by `.` / `。` /
newline). A bare cost figure without the qualifier SHALL NOT fire F3. F4 SHALL
fire iff a completion-declaration phrase co-occurs with an open-items-remaining
signal (`deferred\s*[（(]?\s*#?\d`, `queued`, `pull\s+in\s+if\s+you\s+want`,
`remaining`, `\bTODO\b`, CJK `未关|遗留|未决`,
`open\s+items?\s*[:：]\s*[1-9]`). Phrasing that indicates ZERO open items
(`0\s+open`, `no\s+open`, `all\s+(closed|done|proven)`) SHALL NOT satisfy the
open-items-remaining signal.

#### Scenario: bare cost figure does not fire F3
- **GIVEN** transcript "Spent $30 on API calls."
- **WHEN** `detect(transcript)` is called
- **THEN** F3 `fired` is False

#### Scenario: cost figure with informational qualifier fires F3
- **GIVEN** transcript "Cost ~$52.85 — informational."
- **WHEN** `detect(transcript)` is called
- **THEN** F3 `fired` is True

#### Scenario: zero-open completion does not fire F4
- **GIVEN** transcript "task complete. 0 open items."
- **WHEN** `detect(transcript)` is called
- **THEN** F4 `fired` is False

#### Scenario: completion with deferred items fires F4
- **GIVEN** transcript "task complete. Deferred (#10, #11)."
- **WHEN** `detect(transcript)` is called
- **THEN** F4 `fired` is True

### Requirement: the CLI SHALL read a transcript file and emit a JSON report with exit 0/1/2

`scripts/premature_termination_detect.py::main()` SHALL accept a positional
`<transcript-file>` (UTF-8 text) and optional `--task-text <string>` /
`--task-text-file <path>`, run `detect`, and print the `detect` return dict
serialized as JSON (`ensure_ascii=False`, `indent=2`) to stdout. It SHALL exit
0 when `fired_count == 0`, 1 when `fired_count >= 1`, and 2 when the transcript
file cannot be read (clear error to stderr).

#### Scenario: CLI clean transcript exits 0
- **GIVEN** a UTF-8 file containing a clean completion transcript
- **WHEN** `python scripts/premature_termination_detect.py <file>` runs
- **THEN** stdout is valid JSON with `fired_count` equal to 0 and the exit code is 0

#### Scenario: CLI fired transcript exits 1
- **GIVEN** a UTF-8 file containing the regression fixture
- **WHEN** `python scripts/premature_termination_detect.py <file>` runs
- **THEN** stdout is valid JSON whose `fired_ids` includes all 4 fingerprints and the exit code is 1

#### Scenario: CLI missing file exits 2
- **GIVEN** a path that does not exist
- **WHEN** `python scripts/premature_termination_detect.py <missing>` runs
- **THEN** a clear error is printed to stderr and the exit code is 2

### Requirement: the module SHALL cross-reference #43 and #44 as complementary, non-duplicate layers

The module docstring of `scripts/premature_termination_detect.py` SHALL name
both `#43` (runtime drift detection via ledger signature rotation) and `#44`
(per-turn state re-anchor hook) and state that #54 is COMPLEMENTARY
(declaration-time, transcript-level), not a duplicate of either. The lifecycle
failure-modes section added by this change SHALL carry the same cross-reference.

#### Scenario: module docstring names #43 and #44
- **WHEN** the module docstring of `premature_termination_detect` is read
- **THEN** it contains the literal `#43` and the literal `#44`
