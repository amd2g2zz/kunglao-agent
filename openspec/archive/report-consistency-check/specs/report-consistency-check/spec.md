## ADDED Requirements

### Requirement: check SHALL flag cross-chapter symbol-polarity contradictions with evidence spans

`check(report_text)` SHALL parse the report markdown into chapters (each `## N.N` or
`### N.N.N` header starts a chapter with id `§<number>`; pre-header text is `§preamble`),
classify each tracked-symbol occurrence's polarity per chapter (NEGATIVE when a routing
negator matches within a ±12-char window, POSITIVE otherwise), and return a CC1
inconsistency for every symbol that appears POSITIVE in one chapter and NEGATIVE in
another. The function signature SHALL be `check(report_text: str) -> dict`. Each
inconsistency SHALL carry `id="CC1"`, `name`, `referent` (the symbol token), and
`chapters` (a list of `{chapter, polarity, span}` dicts naming the chapter id and the
matched substring). The detector SHALL use regex/keyword heuristics ONLY (no LLM call, no
network, no binary read).

#### Scenario: regression group A — HandleCommand polarity flip is flagged
- **GIVEN** a report where §3.3 contains "不经过通用的 HandleCommand 处理地址" and §3.4 contains a code listing titled `HandleCommand.func12`
- **WHEN** `check(report_text)` is called
- **THEN** a CC1 inconsistency with `referent` containing `HandleCommand` is in the result, its `chapters` list contains one NEGATIVE entry citing §3.3 and one POSITIVE entry citing §3.4

#### Scenario: consistent symbol usage is not flagged
- **GIVEN** a report where the symbol `HandleCommand` appears positively in §3.3, §3.4, and §4.1 (always the handler, never negated)
- **WHEN** `check(report_text)` is called
- **THEN** no CC1 inconsistency references `HandleCommand`

### Requirement: check SHALL flag mutually-exclusive-mechanism contradictions (CC3) and mechanism-topic polarity flips

`check` SHALL flag a CC3 inconsistency when (a) two members of a configured exclusive-
mechanism pair (e.g. {named-pipe, shared-memory}) are BOTH classified POSITIVE anywhere in
the report (exclusive transports cannot both be the channel), or (b) a mechanism topic
(e.g. `注册表`/`registry`, `Run`/`Startup`) appears POSITIVE in one chapter and NEGATIVE
in another. Each CC3 inconsistency SHALL carry `id="CC3"`, `name`, `referent`, and
`chapters` evidence.

#### Scenario: regression group B — named pipe vs shared memory both asserted
- **GIVEN** a report where §5.4 contains "通过命名管道或共享内存通道" and §6.1.3 contains a code listing with `wire_WriteMsg` / shared-memory context
- **WHEN** `check(report_text)` is called
- **THEN** a CC3 inconsistency with `referent` naming the exclusive pair (named-pipe and shared-memory) is in the result

#### Scenario: regression group C — registry persistence denied and asserted
- **GIVEN** a report where §1.1 contains "运行全程不依赖系统注册表实现持久化" and §2.3 contains a Run-key table
- **WHEN** `check(report_text)` is called
- **THEN** a CC3 (or CC1) inconsistency with `referent` containing `注册表` or `Run` is in the result, with one NEGATIVE entry citing §1.1 and one POSITIVE entry citing §2.3

#### Scenario: negated exclusive mechanism is not flagged
- **GIVEN** a report where §5.4 contains "使用共享内存（不经过命名管道）"
- **WHEN** `check(report_text)` is called
- **THEN** no CC3 exclusive-mechanism inconsistency is in the result (named-pipe is NEGATIVE)

### Requirement: check SHALL flag potential negative-finding scope amplification (CC2) as a warning, separately from hard inconsistencies

`check` SHALL flag a CC2 amplification when the report contains a config-storage-caliber
NEGATIVE assertion (keywords `环境变量|env|配置存储|不落盘`) in one chapter AND a
persistence-mechanism-caliber NEGATIVE assertion (keywords `持久化|注册表|registry|Run
键|Startup|不依赖`) in a DIFFERENT chapter. CC2 evidence SHALL enter the result under a
separate `amplifications` list with `severity="potential"` and SHALL NOT be counted under
`inconsistency_count` (it is a warning the reviewer triages, not a hard error — the
mechanical check cannot judge whether the caliber was preserved or amplified).

#### Scenario: regression amplification — config-storage negative becomes persistence negative
- **GIVEN** a report where one chapter contains "OVERLORD_* 环境变量不落盘" (config-storage NEG) and §1.1 contains "持久化不依赖注册表" (persistence-mechanism NEG)
- **WHEN** `check(report_text)` is called
- **THEN** a CC2 amplification is in `amplifications` naming the two calibers (config-storage, persistence-mechanism), and `inconsistency_count` does not count it

#### Scenario: same-caliber negative is not flagged as amplification
- **GIVEN** a report where two chapters both contain persistence-mechanism negatives (no config-storage caliber present)
- **WHEN** `check(report_text)` is called
- **THEN** no CC2 amplification is in the result

### Requirement: a CONFLICT marker SHALL acknowledge a contradiction instead of counting it as a fresh inconsistency

`check` SHALL recognize an explicit `CONFLICT` marker (an HTML comment `<!-- CONFLICT: ...`
or a `CONFLICT:` label) in a chapter as the author's acknowledgment of a tension. A CC1 or
CC3 contradiction whose evidence chapter carries a CONFLICT marker SHALL be reported under
a separate `acknowledged` list with `acknowledged=true` and SHALL NOT be counted under
`inconsistency_count`. This realizes the issue's "contradictory conclusions must converge
OR carry an explicit CONFLICT marker" rule.

#### Scenario: CONFLICT-marked HandleCommand tension is acknowledged not counted
- **GIVEN** a report where §3.3 says "不经过 HandleCommand" and §3.4 says `HandleCommand.func12` AND §3.4 carries a `<!-- CONFLICT: routing ambiguity -->` marker
- **WHEN** `check(report_text)` is called
- **THEN** the CC1 entry for HandleCommand has `acknowledged=true` and is NOT counted in `inconsistency_count`

### Requirement: the CLI SHALL read a report file and emit a JSON report with exit 0/1/2

`scripts/report_consistency_check.py::main()` SHALL accept a positional `<report-file>`
(UTF-8 markdown), run `check`, and print the result dict serialized as JSON
(`ensure_ascii=False`, `indent=2`) to stdout. It SHALL exit 0 when
`inconsistency_count == 0 AND amplification_count == 0` (an acknowledged tension —
`acknowledged_count > 0` — is the author's accepted resolution per the issue's "converge
OR carry CONFLICT marker" rule and SHALL NOT by itself trigger a non-zero exit), 1 when
`inconsistency_count > 0 OR amplification_count > 0`, and 2 when the report file cannot be
read (clear error to stderr).

#### Scenario: CLI clean report exits 0
- **GIVEN** a UTF-8 file containing a clean consistent report
- **WHEN** `python scripts/report_consistency_check.py <file>` runs
- **THEN** stdout is valid JSON with `inconsistency_count` equal to 0 and the exit code is 0

#### Scenario: CLI inconsistent report exits 1
- **GIVEN** a UTF-8 file containing the regression fixture (3 contradiction groups)
- **WHEN** `python scripts/report_consistency_check.py <file>` runs
- **THEN** stdout is valid JSON with `inconsistency_count` >= 1 and the exit code is 1

#### Scenario: CLI missing file exits 2
- **GIVEN** a path that does not exist
- **WHEN** `python scripts/report_consistency_check.py <missing>` runs
- **THEN** a clear error is printed to stderr and the exit code is 2

### Requirement: the module SHALL cross-reference #50 and numeric-fidelity as complementary, non-overlapping layers

The module docstring of `scripts/report_consistency_check.py` SHALL name `#50`
(report↔binary byte-exact checker) and reference the numeric-fidelity caliber rule, and
state that #57 is the report-INTERNAL cross-chapter sibling (complementary, not
overlapping). The module docstring SHALL additionally carry a brief call contract for the
report pipeline (follow-up, out of scope): run after per-chapter review on the assembled
markdown, BLOCK on CC1/CC3 `severity="error"` (not acknowledged), WARN on CC2
`severity="potential"`. The cross-reference and call contract live in the module docstring
(no separate references doc) to avoid edit conflicts with the existing failure-modes-*
files owned by other changes.

#### Scenario: module docstring names #50 and numeric-fidelity
- **WHEN** the module docstring of `report_consistency_check` is read
- **THEN** it contains the literal `#50` and the literal `numeric-fidelity`
