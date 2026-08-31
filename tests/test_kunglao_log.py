# -*- coding: utf-8 -*-
"""kunglao_log.py contract tests (#287): structured JSONL event log.

The log is the observability substrate: worker/orchestrator/hook events land
as one JSON object per line under runs/logs/kunglao-<date>.jsonl. Logging
must NEVER break analysis — a write failure degrades to a stderr warning.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from kunglao_log import emit, log_path  # noqa: E402

ALL_FIELDS = {"ts", "actor", "action", "claim", "tool", "artifact",
              "duration_ms", "exit", "detail",
              "arm", "epoch", "version", "hypothesis_ref"}

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _rows(p: Path) -> list[dict]:
    return [json.loads(l) for l in
            p.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


def test_emit_writes_one_valid_json_line_with_all_fields(tmp: Path):
    emit(tmp, actor="orchestrator", action="dispatch", claim="C-1", tool="grep",
         artifact="evidence/e1.json", duration_ms=42, exit=0, detail="ok")
    p = log_path(tmp)
    assert p.exists()
    rows = _rows(p)
    assert len(rows) == 1
    ev = rows[0]
    assert set(ev) == ALL_FIELDS, f"field mismatch: {sorted(ev)}"
    assert ISO_RE.match(ev["ts"]), f"ts not ISO8601: {ev['ts']!r}"
    assert ev["actor"] == "orchestrator"
    assert ev["action"] == "dispatch"
    assert ev["claim"] == "C-1"
    assert ev["tool"] == "grep"
    assert ev["artifact"] == "evidence/e1.json"
    assert ev["duration_ms"] == 42
    assert ev["exit"] == 0
    assert ev["detail"] == "ok"


def test_two_emits_two_lines(tmp: Path):
    emit(tmp, actor="worker", action="tool_call", tool="xxd", duration_ms=7, exit=0)
    emit(tmp, actor="worker", action="artifact_written", artifact="facts/F001.md")
    rows = _rows(log_path(tmp))
    assert len(rows) == 2
    assert rows[0]["action"] == "tool_call"
    assert rows[1]["action"] == "artifact_written"
    # unset optional fields are null, not absent
    assert rows[0]["claim"] is None and rows[0]["artifact"] is None
    assert rows[0]["detail"] is None
    assert rows[1]["duration_ms"] is None
    assert rows[1]["exit"] is None
    assert rows[1]["tool"] is None


def test_log_path_is_runs_logs_dated_jsonl(tmp: Path):
    p = log_path(tmp)
    assert p.parent == tmp / "runs" / "logs"
    assert p.name.startswith("kunglao-")
    assert p.name.endswith(".jsonl")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert p.name == f"kunglao-{today}.jsonl"


def test_write_failure_never_raises_and_warns_stderr(tmp: Path, capsys):
    # runs/ exists as a FILE, so creating runs/logs/ fails — emit must
    # degrade to a stderr warning and NOT raise (logging never breaks analysis).
    (tmp / "runs").write_text("not a directory", encoding="utf-8")
    emit(tmp, actor="orchestrator", action="dispatch", claim="C-1")
    captured = capsys.readouterr()
    assert "kunglao_log" in captured.err, f"expected stderr warning, got: {captured.err!r}"
    # nothing written, but no exception either — emit returned normally


def test_emit_deterministic_for_same_inputs(tmp: Path):
    emit(tmp, actor="w", action="a", claim="C-1", tool="t", artifact="x",
         duration_ms=1, exit=0, detail="d")
    emit(tmp, actor="w", action="a", claim="C-1", tool="t", artifact="x",
         duration_ms=1, exit=0, detail="d")
    rows = _rows(log_path(tmp))
    # identical inputs produce identical payloads (deterministic serialization);
    # ts is second-resolution so two same-second emits may share it
    body = {k: v for k, v in rows[0].items() if k != "ts"}
    body2 = {k: v for k, v in rows[1].items() if k != "ts"}
    assert body == body2
    assert rows[0] == rows[1]  # same inputs + same second = byte-identical lines


# ---------- #459: --tail read-only diagnostic CLI -------------------------

class TestTailCli:
    """kunglao_log --tail <ws> [N] — the minimal answer to issue #459's
    "诊断不可解释" (post-mortems rebuilt from worker-status tails + mtimes
    + vmware.log). One command, the most recent N events, JSON lines."""

    def _emit_n(self, ws: Path, n: int, tag: str) -> None:
        for i in range(n):
            emit(ws, actor="worker", action="tool_call", tool=tag,
                 detail=f"i={i}")

    def _tail(self, ws: Path, *extra: str) -> subprocess.CompletedProcess:
        script = REPO_ROOT / "scripts" / "kunglao_log.py"
        return subprocess.run(
            [sys.executable, str(script), "--tail", str(ws), *extra],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
            errors="replace")

    def test_tail_default_20_and_explicit_n(self, tmp: Path):
        self._emit_n(tmp, 25, "t1")
        r = self._tail(tmp)
        assert r.returncode == 0, f"stderr={r.stderr!r}"
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        assert len(lines) == 20, f"default N must be 20; got {len(lines)}"
        rows = [json.loads(ln) for ln in lines]
        assert rows[-1]["detail"] == "i=24", (
            f"tail must return the MOST RECENT events; last={rows[-1]}")

        r5 = self._tail(tmp, "5")
        assert r5.returncode == 0
        rows5 = [json.loads(ln) for ln in r5.stdout.splitlines() if ln.strip()]
        assert len(rows5) == 5 and rows5[-1]["detail"] == "i=24"
        assert rows5[0]["detail"] == "i=20"

    def test_tail_is_read_only(self, tmp: Path):
        self._emit_n(tmp, 3, "t2")
        logs = tmp / "runs" / "logs"
        before = {p.name: p.read_bytes() for p in logs.glob("*.jsonl")}
        stat_before = {p.name: p.stat().st_mtime_ns
                       for p in logs.glob("*.jsonl")}
        r = self._tail(tmp, "10")
        assert r.returncode == 0
        after = {p.name: p.read_bytes() for p in logs.glob("*.jsonl")}
        stat_after = {p.name: p.stat().st_mtime_ns
                      for p in logs.glob("*.jsonl")}
        assert before == after and stat_before == stat_after, (
            "--tail must not create/modify/truncate anything")

    def test_tail_merges_day_files_chronologically(self, tmp: Path):
        logs = tmp / "runs" / "logs"
        logs.mkdir(parents=True)
        (logs / "kunglao-2020-01-01.jsonl").write_text(
            json.dumps({"ts": "2020-01-01T00:00:00Z", "actor": "w",
                        "action": "dispatch", "claim": None, "tool": None,
                        "artifact": None, "duration_ms": None, "exit": None,
                        "detail": "old"}, sort_keys=True) + "\n",
            encoding="utf-8")
        self._emit_n(tmp, 2, "t3")
        r = self._tail(tmp, "2")
        rows = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
        assert len(rows) == 2
        assert rows[0]["detail"] == "i=0" and rows[1]["detail"] == "i=1", (
            f"most recent across ALL day files, file order; got {rows}")

    def test_tail_empty_workspace_rc0_silent(self, tmp: Path):
        ws = tmp / "nothing"
        ws.mkdir()
        r = self._tail(ws)
        assert r.returncode == 0, (
            f"no events is not an error; stderr={r.stderr!r}")
        assert not r.stdout.strip()

    def test_tail_missing_workspace_and_bad_n_fail_fast(self, tmp: Path):
        r = self._tail(tmp / "nope")
        assert r.returncode == 64, (
            f"missing workspace must fail fast; rc={r.returncode}")
        self._emit_n(tmp, 2, "t4")
        r0 = self._tail(tmp, "0")
        assert r0.returncode == 64, f"N<1 must fail fast; rc={r0.returncode}"
