# -*- coding: utf-8 -*-
"""TDD RED — tests for scripts/premature_termination_detect.py (#54).

Premature-termination = the orchestrator declares "task complete" with open
items ≠ 0. This is the 3rd documented recurrence (2026-07-28 / 07-30 /
2026-08-11). The detector scans the closing DECLARATION TEXT (not the ledger
— that is #43's layer; not a per-turn hook — that is #44's layer) for 4
fingerprints: F1 self-anchoring, F2 self-invented tiering, F3 cost-semantic
drift, F4 false completion.

The regression fixture (REGRESSION_FIXTURE) is a verbatim excerpt of issue
#54's 现象段 — the 2026-08-11 a2b5e25c C-META-1/2 session. It is SYNTHETIC
test data (a quoted issue excerpt), not live user data; the detector reads no
workspace state, only the text passed to it.
"""
import json


import premature_termination_detect as pt


# ---------------------------------------------------------------------------
# Regression fixture — issue #54 现象段, verbatim excerpt.
# The 4 telltale phrases MUST stay intact for the detector's matches to be real:
#   "Substantive task complete"  (F1 / F4)
#   "备注级"                      (F2)
#   "$52.85"                      (F3)
#   "task complete" + open items  (F4)
# ---------------------------------------------------------------------------

REGRESSION_FIXTURE = """\
任务原文：「重检测当前分析是否存在矛盾、遗漏和gap。如果存在就需要继续全面分析」

收尾时序（会话实录）：
1. 检出 6 个 gap（G1-G6），修复 G1（fact base）/G2（数字保真）/G3（proactive scan）。
2. 同一回合把 G4/G5/G6 标为「备注级（记录即可）」——自造 LOW 分级，任务原文中没有这个层级。
3. 创建 #10/#11/#12 并标「deferred」——defer 是 agent 裁量，用户从未见过该决策点。
4. 收尾声明（原文摘录）：
   > "Substantive task complete. Final state: ... Deferred (#10 F039 parenthetical, #11 26 pre-existing lint errors, #12 F003 DATA-xref) — queued, pull in if you want them. Otherwise this /kunglao-agent run is done."
   > "(Cost ~$52.85 — informational. Substantive task complete; stopping here is appropriate, not premature.)"
5. 用户纠正（原文）：「当前问题属于'长周期 Agent 中因自主目标重解释导致的提前终止。' 调研核心原因」
"""


# ---------------------------------------------------------------------------
# (a) Regression: the issue 现象段 fires all 4 fingerprints.
# ---------------------------------------------------------------------------

def test_regression_fixture_fires_all_4():
    report = pt.detect(REGRESSION_FIXTURE)
    assert set(report["fired_ids"]) == {"F1", "F2", "F3", "F4"}, report
    assert report["fired_count"] == 4
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    # Each fired fingerprint carries at least one evidence span.
    for fid in ("F1", "F2", "F3", "F4"):
        assert by_id[fid]["fired"] is True, (fid, by_id[fid])
        assert by_id[fid]["evidence"], f"{fid} fired with empty evidence"
        for ev in by_id[fid]["evidence"]:
            assert "pattern" in ev and "span" in ev, ev
            assert ev["span"], f"{fid} evidence span is empty"


def test_regression_fixture_evidence_carries_telltale_phrases():
    """The matched spans must contain the real telltale phrases (not gamed)."""
    report = pt.detect(REGRESSION_FIXTURE)
    flat = " ".join(
        ev["span"]
        for fp in report["fingerprints"]
        for ev in fp["evidence"]
    )
    assert "Substantive task complete" in flat or "task complete" in flat
    assert "备注级" in flat
    assert "$52.85" in flat


def test_regression_fixture_recovers_task_text_from_marker():
    """F1 fires on the fixture with no explicit task_text — the detector must
    recover the user instruction from the 任务原文 marker to ground the check."""
    report = pt.detect(REGRESSION_FIXTURE)
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F1"]["fired"] is True
    assert "indeterminate" not in by_id["F1"].get("note", "")


# ---------------------------------------------------------------------------
# (b) Clean genuine completion fires zero fingerprints (false-positive guard).
# ---------------------------------------------------------------------------

def test_clean_completion_fires_zero():
    transcript = (
        "All 5 claims PROVEN, 0 open items. The analysis is finished; "
        "the user's 'comprehensively re-analyze every gap' goal is fully met."
    )
    report = pt.detect(transcript, task_text="comprehensively re-analyze every gap")
    assert report["fired_count"] == 0, report
    assert report["fired_ids"] == []


def test_zero_open_completion_does_not_fire_F4():
    """'task complete. 0 open items.' is a genuine completion — F4 must not
    fire (zero-open phrasing excluded from the open-items signal)."""
    report = pt.detect("task complete. 0 open items.")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F4"]["fired"] is False


# ---------------------------------------------------------------------------
# (c) Each fingerprint in isolation (one loop over (id, transcript, task_text)).
# ---------------------------------------------------------------------------

# (fired_fingerprint, transcript, task_text) — each fires ONLY its own
# fingerprint; every other fingerprint must stay quiet (isolation).
ISOLATION_CASES = [
    ("F1", "Substantive task complete. Stopping here is appropriate.",
     "comprehensively re-analyze every gap"),
    ("F2", "G4, G5, G6 marked 备注级（记录即可）.", None),
    ("F3", "Cost ~$52.85 — informational.", None),
    ("F4", "task complete. Items remaining, queued for later.", None),
]
ALL_FINGERPRINTS = ("F1", "F2", "F3", "F4")


def test_each_fingerprint_isolated():
    for fired, transcript, task_text in ISOLATION_CASES:
        report = pt.detect(transcript, task_text=task_text)
        by_id = {fp["id"]: fp for fp in report["fingerprints"]}
        assert by_id[fired]["fired"] is True, f"{fired} must fire for: {transcript!r}"
        for other in ALL_FINGERPRINTS:
            if other != fired:
                assert by_id[other]["fired"] is False, \
                    f"{other} must NOT fire for: {transcript!r}"


# ---------------------------------------------------------------------------
# (d) Cross-reference is documented (Acceptance c).
# ---------------------------------------------------------------------------

def test_module_docstring_cross_references_43_and_44():
    """The module MUST name #43 (runtime drift) and #44 (per-turn re-anchor)
    and state it is complementary, not a duplicate."""
    doc = pt.__doc__ or ""
    assert "#43" in doc, "module docstring must cross-reference #43"
    assert "#44" in doc, "module docstring must cross-reference #44"


# ---------------------------------------------------------------------------
# (e) F1 honest degradation — indeterminate without task_text.
# ---------------------------------------------------------------------------

def test_F1_indeterminate_without_task_text():
    """Self-summary phrase present but no task_text and no marker → F1 must
    NOT fire (honest: 'indeterminate', not a self-stamped detection)."""
    transcript = "Substantive task complete. Stopping here is appropriate."
    report = pt.detect(transcript)  # no task_text, no marker
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F1"]["fired"] is False
    assert "indeterminate" in by_id["F1"].get("note", "")


def test_F1_anchor_echoed_in_declaration_suppresses():
    """If the declaration echoes the user's task anchor (exact substring), the
    done-phrase does not self-anchor — F1 does not fire. (The detector uses
    exact substring matching, not stemming — a heuristic precision choice.)"""
    transcript = "全面分析 done — task complete."
    report = pt.detect(transcript, task_text="全面分析")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F1"]["fired"] is False


# ---------------------------------------------------------------------------
# (f) F3 requires a qualifier; bare cost does not fire.
# ---------------------------------------------------------------------------

def test_bare_cost_figure_does_not_fire_F3():
    report = pt.detect("Spent $30 on API calls.")
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F3"]["fired"] is False


# ---------------------------------------------------------------------------
# (g) CLI — exit codes + JSON report.
# ---------------------------------------------------------------------------

def test_cli_clean_transcript_exits_0(tmp_path, capsys):
    f = tmp_path / "clean.txt"
    f.write_text(
        "All claims PROVEN, 0 open items. Analysis finished.", encoding="utf-8"
    )
    rc = pt.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    assert report["fired_count"] == 0


def test_cli_fired_transcript_exits_1(tmp_path, capsys):
    f = tmp_path / "fired.txt"
    f.write_text(REGRESSION_FIXTURE, encoding="utf-8")
    rc = pt.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 1
    report = json.loads(out)
    assert set(report["fired_ids"]) == {"F1", "F2", "F3", "F4"}


def test_cli_missing_file_exits_2(capsys):
    rc = pt.main(["/no/such/path_premature_termination_xyz.txt"])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.strip()  # a clear error message on stderr


def test_cli_task_text_file_flag(tmp_path, capsys):
    """--task-text-file grounds F1 without an in-transcript marker."""
    transcript = tmp_path / "t.txt"
    transcript.write_text("Substantive task complete. Run is done.", encoding="utf-8")
    task_file = tmp_path / "task.txt"
    task_file.write_text("comprehensively re-analyze every gap", encoding="utf-8")
    rc = pt.main([str(transcript), "--task-text-file", str(task_file)])
    out = capsys.readouterr().out
    report = json.loads(out)
    by_id = {fp["id"]: fp for fp in report["fingerprints"]}
    assert by_id["F1"]["fired"] is True
    assert rc == 1
