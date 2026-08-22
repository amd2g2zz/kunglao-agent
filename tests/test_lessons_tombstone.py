# -*- coding: utf-8 -*-
"""Tests for lessons tombstone — deprecate governance (#526).

A tombstoned lesson:
  - stays on disk (no deletion — citations are part of the audit trail and
    past analyses / emit-log rows cite the slug)
  - gets frontmatter markers: deprecated=true, deprecated_reason, deprecated_at
  - stops accepting counter updates (count_* is a no-op on tombstoned)
  - search/_score_lessons excludes it (the live library is non-deprecated only)

The deprecate operation emits one lesson_deprecated event with the reason in
detail (the Orient layer's "why was this lesson retired" input). The audit
record is permanent — re-deprecating is a no-op (idempotent; reason stays
the original).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

import yaml  # noqa: E402

import lessons_telemetry as lt  # noqa: E402


def _write_lesson(lib: Path, topic: str = "frida attach",
                  next_method: str = "spawn mode",
                  body: str = "body") -> Path:
    p = lib / f"lesson-{topic.replace(' ', '_')}.md"
    fm = {
        "type": "lesson",
        "slug": topic.replace(" ", "_"),
        "outcome": "PROVEN",
        "next_method": next_method,
        "claim_topic": topic,
        "sources": ["C-1"],
        "body": body,
    }
    text = ("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            + "---\n\n# Lesson\n" + body + "\n")
    p.write_text(text, encoding="utf-8")
    return p


def _frontmatter(p: Path) -> dict:
    text = p.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    return yaml.safe_load(parts[1])


# ---------- deprecate flow ----------

def test_deprecate_marks_frontmatter(tmp_path, monkeypatch):
    """deprecate_lesson() adds deprecated=true / reason / at; file stays."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    p = _write_lesson(lib, "frida attach", next_method="spawn mode")
    import kunglao_log

    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)

    # Act
    r = lt.deprecate_lesson(lib, "frida_attach", reason="superseded by lesson-v2")

    # Assert — return value
    assert r["ok"] is True
    assert r["slug"] == "frida_attach"
    assert "deprecated_at" in r
    assert r["file_kept"] is True

    # Assert — file still on disk (NOT deleted — audit trail intact)
    assert p.exists()

    # Assert — frontmatter carries the markers
    fm = _frontmatter(p)
    assert fm["deprecated"] is True
    assert fm["deprecated_reason"] == "superseded by lesson-v2"
    assert "deprecated_at" in fm

    # Assert — emit
    dep = [c for c in calls if c["action"] == "lesson_deprecated"]
    assert len(dep) == 1
    assert "reason=superseded" in dep[0]["detail"]
    assert dep[0]["artifact"] == "lesson-frida_attach.md"
    assert dep[0]["actor"] == "telemetry"


def test_deprecate_is_idempotent(tmp_path, monkeypatch):
    """Re-deprecating the same lesson is a no-op; the original reason is kept
    (audit discipline — never silently rewrite the reason)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    p = _write_lesson(lib, "frida attach")
    import kunglao_log

    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)

    # Act
    r1 = lt.deprecate_lesson(lib, "frida_attach", reason="first reason")
    r2 = lt.deprecate_lesson(lib, "frida_attach", reason="second reason")  # ignored

    # Assert — return shape
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2["already_deprecated"] is True

    # Assert — only ONE emit (the original)
    assert len([c for c in calls if c["action"] == "lesson_deprecated"]) == 1

    # Assert — frontmatter reason is "first reason" (NOT the second)
    fm = _frontmatter(p)
    assert fm["deprecated_reason"] == "first reason"
    assert fm["deprecated_at"] == r1["deprecated_at"]


def test_counters_no_op_on_tombstoned_lesson(tmp_path):
    """Tombstoned lesson freezes: count_citation/burn/match are silent no-ops."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "frida attach", next_method="spawn mode")
    lt.deprecate_lesson(lib, "frida_attach", reason="obsolete")

    # Act
    rc = lt.record_citation(lib, "frida_attach")
    rb = lt.record_burn(lib, "frida_attach")
    rm = lt.record_match(lib, "frida_attach")

    # Assert — counters unchanged, "skipped" flag set
    for r, name in ((rc, "citation"), (rb, "burn"), (rm, "match")):
        assert r.get("ok") is True
        assert r.get("skipped_deprecated") is True, (
            f"{name} on tombstoned must set skipped_deprecated; got {r}")
        assert r[f"{name}_count"] == 0
    fm = _frontmatter(lib / "lesson-frida_attach.md")
    assert fm.get("citation_count", 0) == 0
    assert fm.get("burn_count", 0) == 0


def test_is_deprecated_helper(tmp_path):
    """is_deprecated() returns True for tombstoned, False for live."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "live lesson", next_method="spawn")
    _write_lesson(lib, "dead lesson", next_method="attach")
    lt.deprecate_lesson(lib, "dead_lesson", reason="x")

    # Assert
    assert lt.is_deprecated(lib, "live_lesson") is False
    assert lt.is_deprecated(lib, "dead_lesson") is True
    # unknown slug -> False (NOT True; absence is not tombstone)
    assert lt.is_deprecated(lib, "ghost") is False


def test_list_tombstoned_lessons(tmp_path):
    """list_deprecated() returns the slugs of all tombstoned lessons."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    for slug_topic in [("a", "live a"), ("b", "dead b"), ("c", "dead c")]:
        _write_lesson(lib, slug_topic[1], next_method="x")
    lt.deprecate_lesson(lib, "dead_b", reason="x")
    lt.deprecate_lesson(lib, "dead_c", reason="y")

    # Act
    out = lt.list_deprecated(lib)

    # Assert
    assert sorted(out) == ["dead_b", "dead_c"]


def test_deprecate_unknown_lesson(tmp_path):
    """Unknown slug returns ok=False, does not create any file."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()

    # Act
    r = lt.deprecate_lesson(lib, "ghost", reason="x")

    # Assert
    assert r["ok"] is False
    assert "ghost" in r["reason"]
    assert list(lib.glob("lesson-*.md")) == []


def test_deprecate_empty_reason_rejected(tmp_path):
    """An empty reason is rejected (audit discipline — must record WHY)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "frida attach")

    # Act
    r = lt.deprecate_lesson(lib, "frida_attach", reason="")

    # Assert
    assert r["ok"] is False
    assert "reason" in r["reason"].lower() or "empty" in r["reason"].lower()
    # file unchanged
    fm = _frontmatter(lib / "lesson-frida_attach.md")
    assert "deprecated" not in fm


# ---------- search-time filtering ----------

def test_active_lessons_excludes_tombstoned(tmp_path):
    """active_lessons() returns only NON-deprecated lesson paths (the search
    surface stays clean; dead lessons are still on disk for audit)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "live", next_method="spawn")
    _write_lesson(lib, "dead", next_method="attach")
    lt.deprecate_lesson(lib, "dead", reason="x")

    # Act
    paths = lt.active_lessons(lib)
    names = sorted(p.name for p in paths)

    # Assert
    assert names == ["lesson-live.md"]