# -*- coding: utf-8 -*-
"""tests/test_progress_timeline_282.py — issue issue-282 pinned contract.

progress.txt is a COMPLETE case timeline: a rendered view derived from the
kunglao_log event ledger (source of truth) with worker narrative entries
interleaved. Pinned here: zero-gap vs the ledger, tick ordering, byte
idempotency, self-healing, narrative migration/preservation, fail-open,
and the render faces (convergence checkpoint + resume render-then-read).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import progress_timeline as pt  # noqa: E402


# --------------------------------------------------------------- helpers ----

def _ts(i: int) -> str:
    """Controlled event timestamp i minutes past 10:00."""
    return f"2026-09-19T10:{i:02d}:00Z"


def _write_events(ws: Path, events: list[dict]) -> None:
    """Inject machine events with CONTROLLED ts/epoch (emit() stamps real
    wall clock — the fixtures need an exact tick/ts axis)."""
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "kunglao-2026-09-19.jsonl", "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")


def _narrative(ws: Path, entries: list[tuple[str, str]]) -> None:
    """Append (iso_ts, text) entries through the sidecar door."""
    lines = "".join(
        json.dumps({"ts": ts, "text": text}, sort_keys=True,
                   ensure_ascii=False) + "\n" for ts, text in entries)
    p = ws / pt.SIDECAR
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(lines, encoding="utf-8")


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _e_rows(content: str) -> list[str]:
    return [ln for ln in content.splitlines() if ln.startswith("E seq=")]


def _n_rows(content: str) -> list[str]:
    return [ln for ln in content.splitlines() if ln.startswith("N tick=")]


def _pos(lines: list[str], needle: str) -> int:
    return next(i for i, ln in enumerate(lines) if needle in ln)


# ------------------------------------------------- pinned: zero-gap face ----

def test_pinned_zero_gap_events_and_narrative(tmp_path):
    """THE acceptance pin: N machine events + M narrative entries render a
    timeline with every event present, ticks ordered, narrative interleaved
    between its surrounding event timestamps."""
    ws = _ws(tmp_path)
    _write_events(ws, [
        {"ts": _ts(i), "actor": "orchestrator", "action": f"ev{i}",
         "claim": f"C-{i}", "detail": f"event {i}", "epoch": i}
        for i in range(5)
    ])
    _narrative(ws, [(_ts(1), "[2026-09-19 10:01] [W-1] started C-1"),
                    (_ts(3), "[2026-09-19 10:03] [W-1 DONE] strings table")])
    pt.render_and_repair(ws)

    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert pt.timeline_gaps(ws) == [], f"timeline has gaps: {content}"
    e_rows = _e_rows(content)
    assert len(e_rows) == 5
    for i in range(5):
        assert f"action=ev{i}" in content
    ticks = [pt._row_tick(r) for r in e_rows]  # noqa: SLF001 — pinned face
    assert ticks == [0, 1, 2, 3, 4], "ticks must be present and ordered"
    lines = content.splitlines()
    assert _pos(lines, "action=ev1") < _pos(lines, "[W-1] started C-1") \
        < _pos(lines, "action=ev2")
    assert _pos(lines, "action=ev3") \
        < _pos(lines, "[W-1 DONE] strings table") < _pos(lines, "action=ev4")


def test_tick_ordering_across_tick_boundaries(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [
        {"ts": _ts(i), "actor": "orchestrator", "action": f"a{i}",
         "epoch": t}
        for i, t in enumerate((0, 1, 2, 7))
    ])
    pt.render_and_repair(ws)
    rows = _e_rows((ws / pt.PROGRESS_NAME).read_text(encoding="utf-8"))
    assert [pt._row_tick(r) for r in rows] == [0, 1, 2, 7]  # noqa: SLF001


def test_null_epoch_renders_tick_question_mark_not_fabricated(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "noaxis", "epoch": None}])
    pt.render_and_repair(ws)
    rows = _e_rows((ws / pt.PROGRESS_NAME).read_text(encoding="utf-8"))
    assert "tick=?" in rows[0]


def test_multi_day_ledger_merges_chronologically(tmp_path):
    ws = _ws(tmp_path)
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    for day, ts in (("2026-09-18", "2026-09-18T09:00:00Z"),
                    ("2026-09-19", "2026-09-19T09:00:00Z")):
        (logs / f"kunglao-{day}.jsonl").write_text(
            json.dumps({"ts": ts, "actor": "orchestrator",
                        "action": f"d{day}", "epoch": 0}) + "\n",
            encoding="utf-8")
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert content.index("d2026-09-18") < content.index("d2026-09-19")


# ------------------------------------------------ idempotency + healing ----

def test_re_render_is_byte_identical_and_mtime_noop(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    _narrative(ws, [(_ts(1), "worker note")])
    pt.render_and_repair(ws)
    first = (ws / pt.PROGRESS_NAME).read_bytes()
    m1 = (ws / pt.PROGRESS_NAME).stat().st_mtime_ns
    status = pt.render_and_repair(ws)
    assert status["status"] == "rendered" and status["wrote"] is False
    assert (ws / pt.PROGRESS_NAME).read_bytes() == first
    assert (ws / pt.PROGRESS_NAME).stat().st_mtime_ns == m1


def test_deleted_line_is_repaired(tmp_path):
    """Self-healing by construction: delete a machine line AND a narrative
    line; the next render restores the file byte-identically."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(i), "actor": "orchestrator",
                        "action": f"ev{i}", "epoch": i} for i in range(4)])
    _narrative(ws, [(_ts(2), "[W-2] mid note")])
    pt.render_and_repair(ws)
    golden = (ws / pt.PROGRESS_NAME).read_bytes()
    lines = (ws / pt.PROGRESS_NAME).read_text(
        encoding="utf-8").splitlines(keepends=True)
    gutted = "".join(ln for ln in lines
                     if "action=ev2" not in ln and "[W-2] mid note" not in ln)
    (ws / pt.PROGRESS_NAME).write_text(gutted, encoding="utf-8")
    pt.render_and_repair(ws)
    assert (ws / pt.PROGRESS_NAME).read_bytes() == golden


# ------------------------------------------ narrative migration faces ----

def test_worker_appends_migrate_into_the_timeline(tmp_path):
    """No worker-protocol change: a raw append to progress.txt between
    rounds is ingested, appears verbatim as an N row, and survives every
    later re-render without duplication."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(i), "actor": "orchestrator",
                        "action": f"ev{i}", "epoch": i} for i in range(2)])
    pt.render_and_repair(ws)
    with open(ws / pt.PROGRESS_NAME, "a", encoding="utf-8") as f:
        f.write("[2026-09-19 10:05] [W-3 DONE] strings table extracted\n")
    status = pt.render_and_repair(ws)
    assert status["narrative"] == 1
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert "[2026-09-19 10:05] [W-3 DONE] strings table extracted" in content
    status2 = pt.render_and_repair(ws)
    assert status2["narrative"] == 0
    final = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert final.count("[W-3 DONE]") == 1


def test_legacy_progress_txt_migrates_losslessly(tmp_path):
    """Pre-issue-282 free-form content: every non-empty line survives verbatim."""
    ws = _ws(tmp_path)
    legacy = "\n".join([
        "## VERIFIED-FACTS LEDGER",
        "(none yet)",
        "[2026-09-19 09:30] [W-1] scanning headers",
        "stray analysis line without a stamp",
        "",
    ])
    (ws / pt.PROGRESS_NAME).write_text(legacy, encoding="utf-8")
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    for line in ("## VERIFIED-FACTS LEDGER", "(none yet)",
                 "[2026-09-19 09:30] [W-1] scanning headers",
                 "stray analysis line without a stamp"):
        assert line in content
    sidecar = (ws / pt.SIDECAR).read_text(encoding="utf-8")
    assert "scanning headers" in sidecar


def test_narrative_lines_starting_with_n_are_not_swallowed(tmp_path):
    """A worker line starting with 'N ' must classify as narrative, never
    as a rendered row (the rendered prefixes are over-specified)."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    pt.render_and_repair(ws)
    with open(ws / pt.PROGRESS_NAME, "a", encoding="utf-8") as f:
        f.write("N/A verdict lines are narrative too\n")
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert "N/A verdict lines are narrative too" in content


def test_narrative_tick_interpolates_from_surrounding_events(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0},
                       {"ts": _ts(1), "actor": "orchestrator",
                        "action": "ev1", "epoch": 3}])
    _narrative(ws, [(_ts(1), "note between")])
    pt.render_and_repair(ws)
    n_row = _n_rows((ws / pt.PROGRESS_NAME).read_text(encoding="utf-8"))[0]
    assert "tick=3" in n_row  # latest event at or before 10:01


def test_untimed_narrative_sorts_last_and_uses_tick_zero(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    _narrative(ws, [(None, "line with no timestamp")])
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    n_row = _n_rows(content)[0]
    assert "tick=0" in n_row and "ts=-" in n_row
    assert content.rstrip().splitlines()[-1].startswith("N tick=0 ts=-")


# ------------------------------------------------------------ fail-open ----

def test_unreadable_ledger_leaves_file_untouched(tmp_path):
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    pt.render_and_repair(ws)  # a first good render over a real day file
    golden = (ws / pt.PROGRESS_NAME).read_bytes()
    day = ws / "runs" / "logs" / "kunglao-2026-09-19.jsonl"
    day.unlink()
    day.mkdir()  # a directory at the path: stat ok, read fails
    status = pt.render_and_repair(ws)
    assert status["status"] == "skipped" and status["wrote"] is False
    assert "unreadable" in status["reason"]
    assert (ws / pt.PROGRESS_NAME).read_bytes() == golden


def test_missing_ledger_is_a_real_empty_timeline(tmp_path):
    ws = _ws(tmp_path)
    status = pt.render_and_repair(ws)
    assert status["events"] == 0
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert "# events=0 narrative=0" in content


def test_render_note_faces(tmp_path):
    ws = _ws(tmp_path)
    assert "missing" in pt.render_note(ws)
    (ws / pt.PROGRESS_NAME).write_text("legacy content\n", encoding="utf-8")
    # legacy (no marker) wins over stale: the file has not rendered yet
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    assert "legacy" in pt.render_note(ws)
    pt.render_and_repair(ws)
    assert "current" in pt.render_note(ws)


# ------------------------------------------------------------ hook faces ----

def _resumable_ws(tmp_path: Path) -> Path:
    """Minimal crash-shape workspace: register + task_spec + fresh
    heartbeat (the decide/RC contract is test_kunglao_resume's business —
    here it just has to be RC_RESUMABLE so the render face runs)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n  answers_question: q1\n",
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: sample family\n"
        "goal_verbatim: legacy goal\n"
        "success_criterion: legacy criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    now = datetime.now(timezone.utc)
    ts = (now - timedelta(minutes=1)).isoformat()
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": ts, "activity_ts": ts}),
        encoding="utf-8")
    return ws


def test_resume_renders_then_reads_and_stays_scoped(tmp_path):
    """The issue-282 resume amendment: resume repairs ONLY progress.txt when
    stale; the ledger and every other file stay byte/mtime identical; a
    second resume (steady state) touches nothing at all."""
    import kunglao_resume
    ws = _resumable_ws(tmp_path)
    (ws / pt.PROGRESS_NAME).write_text("stale legacy content\n",
                                       encoding="utf-8")
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "converge", "epoch": 0}])

    def tree():
        return {str(p.relative_to(ws)): (p.stat().st_mtime_ns, p.stat().st_size)
                for p in sorted(ws.rglob("*")) if p.is_file()}

    before = tree()
    rc = kunglao_resume.main([str(ws), "--json"])
    assert rc == kunglao_resume.RC_RESUMABLE
    after = tree()
    assert set(after) == set(before) | {str(pt.SIDECAR), str(pt.LOCK_REL)}
    for name, sig in after.items():
        if name != str(pt.PROGRESS_NAME) and name in before:
            assert sig == before[name], f"resume touched {name}"
    assert "E seq=" in (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    steady = tree()
    kunglao_resume.main([str(ws), "--json"])
    assert tree() == steady, "steady-state resume must be a full no-op"


def test_convergence_main_renders_at_checkpoint(tmp_path):
    """Source anchor: convergence_check.main renders right after the
    snapshot append — the tick writer — so the view stays in lockstep."""
    source = (REPO_ROOT / "scripts" / "convergence_check.py").read_text(
        encoding="utf-8")
    append_at = source.index("_append_ledger(workspace, d)")
    render_at = source.index("render_and_repair(workspace)")
    assert append_at < render_at
    assert "fail-open" in source[render_at:render_at + 400].lower()


def test_brief_reports_the_progress_timeline_note(tmp_path):
    import kunglao_resume
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    (ws / pt.PROGRESS_NAME).write_text("stale\n", encoding="utf-8")
    brief = kunglao_resume.build_brief(ws)  # pure read: no repair here
    assert "renders at the next checkpoint" in brief["progress_timeline"]
    assert (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8") == "stale\n"


def test_digest_tail_reads_the_rendered_form(tmp_path):
    """digest_build's mechanical 3-line tail keeps working on the rendered
    file (newest timeline rows are a superset of the old narrative tail)."""
    import digest_build
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(i), "actor": "orchestrator",
                        "action": f"ev{i}", "epoch": i} for i in range(2)])
    _narrative(ws, [(_ts(1), "worker note")])
    pt.render_and_repair(ws)
    progress = digest_build._read_text(ws / pt.PROGRESS_NAME)  # noqa: SLF001
    assert progress and "E seq=" in progress


def test_state_anchor_still_never_reads_progress(tmp_path):
    """issue-530 coexistence: the rendered timeline is a VIEW — the anchor's
    output (built from a real snapshot) carries none of it."""
    import state_anchor
    ws = _ws(tmp_path)
    snap = {"type": "snapshot", "ts": _ts(0), "decision": "DISPATCH",
            "open_ids": ["C-1"], "active_workers": [], "blockers": [],
            "facts_total": 0, "open_count": 1, "partial_count": 0}
    (ws / ".convergence_ledger.jsonl").write_text(
        json.dumps(snap) + "\n", encoding="utf-8")
    _write_events(ws, [{"ts": _ts(i), "actor": "orchestrator",
                        "action": f"ev{i}", "epoch": i} for i in range(2)])
    _narrative(ws, [(_ts(1), "[W-9] secret narrative marker xyzzy")])
    pt.render_and_repair(ws)
    anchor = state_anchor.build_anchor(ws)
    assert anchor, "anchor must build from the snapshot"
    assert "xyzzy" not in anchor
    assert "E seq=" not in anchor


# ------------------------------------------------ review round-2 faces ----

def test_identical_text_retry_entries_both_survive(tmp_path):
    """Review F2: dedup keys on (ts, text) OCCURRENCE COUNTS, not bare
    text — two byte-identical lines (a retry loop re-logging the same DONE
    text) are two entries; both render, and neither grows on re-render."""
    ws = _ws(tmp_path)
    line = "[2026-09-19 10:05] [W-3 DONE] strings table extracted"
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    pt.render_and_repair(ws)
    with open(ws / pt.PROGRESS_NAME, "a", encoding="utf-8") as f:
        f.write(line + "\n" + line + "\n")
    status = pt.render_and_repair(ws)
    assert status["narrative"] == 2
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert content.count(line) == 2
    pt.render_and_repair(ws)
    again = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert again.count(line) == 2  # no growth, no loss


def test_double_ingest_before_rewrite_does_not_duplicate(tmp_path):
    """Review F5 damage shape: two faces snapshot the sidecar before either
    appends — repeated ingest of the same raw lines must stay idempotent,
    so the render never grows duplicate N rows."""
    ws = _ws(tmp_path)
    (ws / pt.PROGRESS_NAME).write_text(
        "[2026-09-19 10:00] [W-1] started\n", encoding="utf-8")
    pt.ingest_progress_appends(ws)
    pt.ingest_progress_appends(ws)  # the second face's snapshot
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert content.count("[W-1] started") == 1


def test_worker_append_between_ingest_and_write_is_not_lost(tmp_path, monkeypatch):
    """Review F1 TOCTOU: an append landing between the ingest read and the
    destructive write must survive — the re-check loop folds it in, so the
    line ends up in the file AND the sidecar."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    pt.render_and_repair(ws)
    golden = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    real_read = pt.read_progress
    calls = {"n": 0}

    def racy_read(w):
        calls["n"] += 1
        text = real_read(w)
        if calls["n"] == 2 and text == golden:
            # the worker's append lands right after the first snapshot read
            with open(Path(w) / pt.PROGRESS_NAME, "a", encoding="utf-8") as f:
                f.write("[2026-09-19 10:06] [W-4] late straggler line\n")
            text = real_read(w)
        return text

    monkeypatch.setattr(pt, "read_progress", racy_read)
    status = pt.render_and_repair(ws)
    assert status["status"] == "rendered" and status["wrote"] is True
    final = real_read(ws)
    assert "[W-4] late straggler line" in final
    assert "[W-4] late straggler line" in \
        (ws / pt.SIDECAR).read_text(encoding="utf-8")


def test_render_lock_is_exclusive_while_held(tmp_path):
    """Review F1/F5 guard: the advisory lock excludes a concurrent face and
    is released after it (flock dies with the process — no stale lock)."""
    import fcntl
    ws = _ws(tmp_path)
    with pt._render_lock(ws):
        other = open(ws / pt.LOCK_REL, "a+")
        try:
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise AssertionError("lock must be exclusive while held")
        except BlockingIOError:
            pass  # expected: a concurrent face cannot enter
        finally:
            other.close()
    # released: a fresh acquisition succeeds
    with pt._render_lock(ws):
        pass


def test_naive_or_garbage_ts_renders_as_documented_null(tmp_path):
    """Review F3: a tz-less/hand-edited ts in the ledger must not crash
    render() with a naive-vs-aware TypeError (which both fail-open callers
    would silently swallow). It is the documented-null face: the row still
    renders, unparseable rows sort last, nothing fabricated."""
    ws = _ws(tmp_path)
    _write_events(ws, [
        {"ts": "2026-09-19T10:00:00Z", "actor": "o", "action": "aware",
         "epoch": 2},
        {"ts": "2026-09-19 10:01:00", "actor": "o", "action": "naive",
         "epoch": 3},
        {"ts": "not-a-timestamp", "actor": "o", "action": "garbage",
         "epoch": 4},
    ])
    status = pt.render_and_repair(ws)
    assert status["status"] == "rendered"
    lines = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8").splitlines()
    assert _pos(lines, "action=aware") < _pos(lines, "action=naive")
    assert lines[-1].startswith("E seq=") and "action=garbage" in lines[-1]


def test_unreadable_ledger_warns_on_stderr(tmp_path, capsys):
    """Review F4: a fail-open skip leaves its one stderr trace (issue-275:
    never silent) — the design matrix's promised warning, now real."""
    ws = _ws(tmp_path)
    day = ws / "runs" / "logs" / "kunglao-2026-09-19.jsonl"
    day.parent.mkdir(parents=True)
    day.mkdir()  # a directory at the path: stat ok, read fails
    status = pt.render_and_repair(ws)
    assert status["status"] == "skipped"
    err = capsys.readouterr().err
    assert "warning" in err and "unreadable" in err


def test_damaged_marker_does_not_pollute_the_sidecar(tmp_path):
    """Review F6: marker recognition is a PREFIX match — an editor that
    normalizes one character (em dash) must not demote the rendered block
    into the sidecar (no ghost narrative, no E-row text stored)."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": 0}])
    pt.render_and_repair(ws)
    content = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    damaged = content.replace(
        "# progress.txt — rendered case timeline (issue-282)",
        "# progress.txt - rendered case timeline (issue-282)", 1)
    assert damaged != content
    (ws / pt.PROGRESS_NAME).write_text(damaged, encoding="utf-8")
    status = pt.render_and_repair(ws)
    sidecar_path = ws / pt.SIDECAR
    sidecar = sidecar_path.read_text(encoding="utf-8") if sidecar_path.exists() else ""
    assert status["narrative"] == 0
    assert "action=ev0" not in sidecar  # no E-row text ingested
    assert "source of truth" not in sidecar  # no header lines ingested
    final = (ws / pt.PROGRESS_NAME).read_text(encoding="utf-8")
    assert pt.RENDER_MARKER in final  # canonical marker restored
    assert "action=ev0" in final  # the timeline itself is intact


def test_capped_row_carries_ellipsis_tail(tmp_path):
    """Review F8: a clipped view row ends with the explicit tail marker —
    a clipped line never looks complete."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "big", "epoch": 0, "detail": "x" * 400}])
    pt.render_and_repair(ws)
    row = next(ln for ln in (ws / pt.PROGRESS_NAME).read_text(
        encoding="utf-8").splitlines() if "action=big" in ln)
    assert len(row) == pt.ROW_CAP and row.endswith("…")


def test_all_question_tick_axis_is_surfaced(tmp_path):
    """Review F9: an all-'?' timeline is complete but un-ticked — the note
    says so instead of a bare current (never fabricated, but visible)."""
    ws = _ws(tmp_path)
    _write_events(ws, [{"ts": _ts(0), "actor": "orchestrator",
                        "action": "ev0", "epoch": None}])
    pt.render_and_repair(ws)
    note = pt.render_note(ws)
    assert "current" in note and "tick axis unavailable" in note


def test_stateless_workspace_stays_stateless(tmp_path):
    """The render face is gated on _has_state: resume on an empty workspace
    must NOT scaffold runs/ or a timeline — NO-STATE guidance stays honest
    (regression: the advisory lock's runs/ mkdir flipped rc 2 -> 1)."""
    import kunglao_resume
    ws = _ws(tmp_path)
    rc = kunglao_resume.main([str(ws), "--json"])
    assert rc == kunglao_resume.RC_NO_STATE
    assert not (ws / pt.PROGRESS_NAME).exists()
    assert not (ws / "runs").exists()
