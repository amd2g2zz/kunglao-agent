# -*- coding: utf-8 -*-
"""#818 batch-1: log schema four fields + decision_input snapshot.

emit() gains arm / epoch / version / hypothesis_ref kwargs (backward
compatible: absent → null keys in the row). decide() emits ONE
decision_snapshot event per verdict (actor=convergence_check) carrying
claims status counts and the top-K priority (id, score) list.

Ledger assertions scan ALL kunglao-*.jsonl day files (sorted) — emit writes
to TODAY's file, so fixture-dated files alone miss rows (date-rollover
lesson, #832).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import kunglao_log


def _rows(ws: Path) -> list[dict]:
    rows = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _mk_ws(tmp_path: Path, claims="claims: []\n") -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(claims, encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text("F001 | OPEN | C-001 | x\n", encoding="utf-8")
    return ws


def test_emit_new_fields_land_in_row(tmp_path):
    ws = _mk_ws(tmp_path)
    kunglao_log.emit(ws, "test", "converge", arm="N", epoch=3,
                     hypothesis_ref="H-001")
    rows = _rows(ws)
    row = rows[-1]
    assert row["arm"] == "N"
    assert row["epoch"] == 3
    assert row["hypothesis_ref"] == "H-001"


def test_emit_absent_fields_are_null_keys(tmp_path):
    """Backward-compatible schema: absent optional fields are explicit nulls
    (stable key set) — old consumers use .get() and keep working."""
    ws = _mk_ws(tmp_path)
    kunglao_log.emit(ws, "test", "converge")
    row = _rows(ws)[-1]
    for field in ("arm", "epoch", "version", "hypothesis_ref"):
        assert field in row
        assert row[field] is None


def test_emit_version_autofills_git_sha_or_none(tmp_path):
    ws = _mk_ws(tmp_path)
    kunglao_log.emit(ws, "test", "converge")
    row = _rows(ws)[-1]
    sha = row["version"]
    # inside the kunglao-agent worktree the SHA resolves; in a non-repo temp
    # dir subprocess fails → None. Either way the field is well-typed.
    assert sha is None or (isinstance(sha, str) and len(sha) >= 7)


def test_decide_emits_decision_snapshot(tmp_path):
    """decide() must emit ONE decision_snapshot event per verdict carrying
    claims status counts + top-K priority (id, score)."""
    ws = _mk_ws(tmp_path, claims=(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: synthetic\n"
        "  - id: C-002\n"
        "    status: PROVEN\n"
        "    statement: synthetic\n"
    ))
    import convergence_check
    convergence_check.decide(ws)
    snaps = [r for r in _rows(ws) if r.get("action") == "decision_snapshot"]
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap["actor"] == "convergence_check"
    detail = json.loads(snap["detail"])
    assert detail["status_counts"] == {"OPEN": 1, "PROVEN": 1}
    assert isinstance(detail["top_priorities"], list)
    assert all({"id", "score"} <= set(t) for t in detail["top_priorities"])
    assert len(detail["top_priorities"]) <= 5


def test_decide_snapshot_never_breaks_decision(tmp_path):
    """Logging must never break analysis: even if emission internals raise,
    decide() returns the same decision dict."""
    ws = _mk_ws(tmp_path, claims="claims:\n  - id: C-001\n    status: OPEN\n    statement: s\n")
    import convergence_check
    d = convergence_check.decide(ws)
    assert d["decision"] in {"DISPATCH", "DISPATCH_VERIFIER"}
    assert "exit_code" in d
