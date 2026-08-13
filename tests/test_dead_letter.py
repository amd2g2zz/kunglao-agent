# -*- coding: utf-8 -*-
"""Tests for dead_letter.py — DEAD status + dead-letter quarantine (#36).

TDD RED phase: these tests define the contract BEFORE implementation.
RED runs:
  - test_dead_excluded_from_open:        fails until DEAD is in TERMINAL
  - test_mark_dead_*:                    fail until dead_letter.py exists
  - test_scan_*:                         same
  - test_detect_dirty_statuses:          same
Run: python scripts/test_dead_letter.py
or:  pytest scripts/test_dead_letter.py
"""
import sys
from pathlib import Path

# sibling import (scripts/ on sys.path for both direct-run and pytest)
sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402
import dead_letter as dl  # noqa: E402
import convergence_check as cc  # noqa: E402


# ---------- helpers ----------

def _mk_reg(ws: Path, claims: list) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")
    ) or {}


# ---------- RED tests ----------

def test_dead_excluded_from_open(tmp_path):
    """DEAD status is excluded from dispatchable (via TERMINAL, zero code change)."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "DEAD", "promotion_attempts": 3}])
    reg = _load_reg(tmp_path)
    assert cc._open_claims(reg) == []


def test_mark_dead_writes_artifact(tmp_path):
    """Exhausted OPEN claim -> DEAD + blockers/dead-letter-<claim>.md."""
    _mk_reg(tmp_path, [{"id": "C-2", "status": "OPEN", "promotion_attempts": 3}])
    r = dl.mark_dead(tmp_path, "C-2", reason="3 attempts exhausted")
    assert r["status"] == "DEAD"
    assert r["marked"] is True
    artifact = tmp_path / "blockers" / "dead-letter-C-2.md"
    assert artifact.exists(), "dead-letter artifact must be created"
    assert "DEAD" in artifact.read_text(encoding="utf-8")
    # register now carries DEAD + dead_at + dead_reason
    claim = next(c for c in _load_reg(tmp_path)["claims"] if c["id"] == "C-2")
    assert claim["status"] == "DEAD"
    assert claim.get("dead_at")
    assert claim.get("dead_reason") == "3 attempts exhausted"


def test_mark_dead_rejects_unknown(tmp_path):
    """Unknown claim id -> marked False, no write, register unchanged."""
    _mk_reg(tmp_path, [{"id": "C-2", "status": "OPEN", "promotion_attempts": 3}])
    before = _load_reg(tmp_path)
    r = dl.mark_dead(tmp_path, "C-404", reason="missing")
    assert r["marked"] is False
    assert "reason" in r
    assert _load_reg(tmp_path) == before
    assert not (tmp_path / "blockers").exists() or not any(
        (tmp_path / "blockers").glob("dead-letter-*")
    )


def test_scan_finds_exhausted_open(tmp_path):
    """promotion_attempts>=3 + non-terminal -> reported; already-DEAD -> not."""
    _mk_reg(tmp_path, [
        {"id": "C-3", "status": "OPEN", "promotion_attempts": 3},
        {"id": "C-9", "status": "DEAD", "promotion_attempts": 5},
        {"id": "C-7", "status": "OPEN", "promotion_attempts": 1},
    ])
    assert dl.scan(tmp_path) == ["C-3"]


def test_detect_dirty_statuses(tmp_path):
    """PASS- dirty literal flagged; clean register yields none."""
    _mk_reg(tmp_path, [
        {"id": "C-4", "status": "PASS-"},
        {"id": "C-5", "status": "OPEN"},
        {"id": "C-6", "status": "PROVEN"},
    ])
    assert dl.detect_dirty_statuses(tmp_path) == ["C-4"]


# ---------- direct-run harness (pytest collects these too) ----------

if __name__ == "__main__":
    import tempfile

    passed = 0
    failed = 0

    def run(name, fn):
        global passed, failed
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"PASS  {name}")
                passed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL  {name}: {exc!r}")
                failed += 1

    # tests that take tmp_path
    for n, f in [
        ("test_dead_excluded_from_open", test_dead_excluded_from_open),
        ("test_mark_dead_writes_artifact", test_mark_dead_writes_artifact),
        ("test_mark_dead_rejects_unknown", test_mark_dead_rejects_unknown),
        ("test_scan_finds_exhausted_open", test_scan_finds_exhausted_open),
        ("test_detect_dirty_statuses", test_detect_dirty_statuses),
    ]:
        run(n, f)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
