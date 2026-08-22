# -*- coding: utf-8 -*-
"""Tests for lessons telemetry — CBM quartet + utility score emit (#526).

Per-lesson CBM (Citation / Burn / Match) tracking + utility_score emission:

  - citation_count: bumped when the lesson is surfaced as a candidate (search
                    hit) — i.e. how often retrieval says "this is relevant".
  - burn_count:     bumped when the lesson is actually CONSUMED — i.e. its
                    next_method was adopted as the new method. A search hit
                    that nobody acts on is noise (citation alone = 0 utility).
  - match_count:    bumped when retrieval returned the lesson with score > 0
                    (same shape as citation but counted separately so we can
                    tell "appeared in result set" from "passed the threshold").
  - utility_score:  derived; utility = burn_count / (citation_count + 1) so a
                    lesson with 0 utility (cited but never used) is reflected.

The four counters live in the lesson's frontmatter (one source per file —
no separate registry). count_* calls are atomic-ish (read-modify-write with
file lock semantics in mind) and idempotent on tombstoned lessons (deprecate
freezes the counters; further count_* is a no-op).

The emit-log face (kunglao_log.emit) carries utility_score in detail so
--tail can graph the per-lesson utility without re-reading the library.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

import yaml  # noqa: E402

import lessons_telemetry as lt  # noqa: E402


# ---------- helpers ----------

def _write_lesson(lib: Path, slug: str, topic: str = "frida attach",
                  next_method: str = "spawn mode",
                  body: str = "frida attach body") -> Path:
    """Seed one lesson file with the standard #41 frontmatter shape."""
    p = lib / f"lesson-{slug}.md"
    fm = {
        "type": "lesson",
        "slug": slug,
        "outcome": "PROVEN",
        "next_method": next_method,
        "claim_topic": topic,
        "sources": ["C-1"],
    }
    text = ("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            + "---\n\n# Lesson\n" + body + "\n")
    p.write_text(text, encoding="utf-8")
    return p


def _frontmatter(p: Path) -> dict:
    text = p.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    return yaml.safe_load(parts[1])


# ---------- CBM quartet ----------

def test_citation_increments_and_emits_utility(tmp_path):
    """count_citation() bumps citation_count in frontmatter + emits one event
    with the current utility_score."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "abc123", next_method="spawn mode")

    # Act — capture emit calls
    import kunglao_log
    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    real_emit = kunglao_log.emit
    kunglao_log.emit = _fake
    try:
        r1 = lt.record_citation(lib, "abc123")
        r2 = lt.record_citation(lib, "abc123")
    finally:
        kunglao_log.emit = real_emit

    # Assert — counters
    assert r1["citation_count"] == 1 and r1["burn_count"] == 0
    assert r2["citation_count"] == 2 and r2["burn_count"] == 0
    fm = _frontmatter(lib / "lesson-abc123.md")
    assert fm["citation_count"] == 2

    # Assert — emit calls: 2 citations, each carries utility_score
    cit = [c for c in calls if c["action"] == "lesson_citation"]
    assert len(cit) == 2
    for c in cit:
        assert "utility=" in c["detail"], f"detail must carry utility_score; got {c}"
        assert c["artifact"] == "lesson-abc123.md"


def test_burn_bumps_burn_count_and_recomputes_utility(tmp_path):
    """count_burn() bumps burn_count; utility_score = burn / (citation + 1)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "burn01")
    # seed 3 citations
    for _ in range(3):
        lt.record_citation(lib, "burn01")
    # 2 burns
    r1 = lt.record_burn(lib, "burn01")
    r2 = lt.record_burn(lib, "burn01")

    # Assert — utility formula
    # burn_count=2, citation_count=3 -> utility = 2 / (3 + 1) = 0.5
    assert r1["burn_count"] == 1 and r1["utility_score"] == 1 / (3 + 1)
    assert r2["burn_count"] == 2 and r2["utility_score"] == 2 / (3 + 1)
    fm = _frontmatter(lib / "lesson-burn01.md")
    assert fm["burn_count"] == 2
    assert abs(fm["utility_score"] - 0.5) < 1e-9


def test_match_count_distinct_from_citation(tmp_path):
    """match_count is a separate counter (search hit with score > 0)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "match01")

    # Act
    r = lt.record_match(lib, "match01")

    # Assert — match bumps match_count, leaves citation_count at 0
    assert r["match_count"] == 1
    assert r["citation_count"] == 0
    fm = _frontmatter(lib / "lesson-match01.md")
    assert fm["match_count"] == 1
    assert fm["citation_count"] == 0  # never bumped -> materialised at 0


def test_citation_zero_utility_explicit(tmp_path):
    """A lesson with only citations (no burns) has utility_score = 0."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "cit0")

    # Act — 5 citations, zero burns
    for _ in range(5):
        lt.record_citation(lib, "cit0")

    # Assert
    fm = _frontmatter(lib / "lesson-cit0.md")
    assert fm["citation_count"] == 5
    assert fm["burn_count"] == 0
    assert fm["utility_score"] == 0.0


def test_compute_utility_formula_pure():
    """compute_utility is pure (no I/O), the formula in the docstring."""
    assert lt.compute_utility(0, 0) == 0.0
    assert lt.compute_utility(1, 1) == 0.5
    assert lt.compute_utility(3, 2) == 0.5
    assert lt.compute_utility(10, 9) == 9 / 11
    # citation+1 in the denominator guarantees a 0/0 stays 0 (no ZeroDiv)
    assert lt.compute_utility(0, 0) == 0.0


def test_unknown_lesson_returns_zero_safely(tmp_path):
    """Unknown slug returns an "ok=False" payload; does NOT create a file."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()

    # Act
    r = lt.record_citation(lib, "ghost")

    # Assert
    assert r["ok"] is False
    assert "ghost" in r["reason"]
    assert list(lib.glob("lesson-*.md")) == []


def test_missing_library_no_crash(tmp_path):
    """Library dir doesn't exist -> graceful fail, no write, no crash."""
    # Act
    r = lt.record_citation(tmp_path / "nolib", "abc")

    # Assert
    assert r["ok"] is False
    assert not (tmp_path / "nolib").exists()


def test_corrupt_frontmatter_no_crash(tmp_path):
    """A lesson file with broken YAML frontmatter degrades to ok=False."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    p = lib / "lesson-bad.md"
    p.write_text("---\ntype: lesson\nbroken: [unclosed\n---\n\nbody\n",
                 encoding="utf-8")

    # Act + Assert
    assert lt.record_citation(lib, "bad")["ok"] is False


# ---------- emit-log face ----------

def test_emit_action_words_are_registered():
    """#459 CI anchor: every action word we emit must be in EMIT_ACTIONS."""
    import event_taxonomy as et
    # the words this file emits — pinned here so a refactor cannot silently
    # extend the vocabulary without registering
    for w in ("lesson_citation", "lesson_burn", "lesson_match",
              "lesson_deprecated"):
        assert w in et.EMIT_ACTIONS, (
            f"action {w!r} must be registered in event_taxonomy.EMIT_ACTIONS "
            f"(extend scripts/event_taxonomy.py); got {sorted(et.EMIT_ACTIONS)}")


def test_emit_carries_utility_score_in_detail(tmp_path, monkeypatch):
    """Every counter event carries utility=<current> in detail (--tail-able)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "abc")
    import kunglao_log
    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    lt.record_citation(lib, "abc")    # utility = 0
    lt.record_burn(lib, "abc")        # utility = 1 / (1+1) = 0.5
    lt.record_citation(lib, "abc")    # utility = 1 / (2+1) = 0.333...

    # Assert
    assert len(calls) == 3
    details = [c.get("detail", "") for c in calls]
    assert "utility=0.000" in details[0]
    assert "utility=0.500" in details[1]
    assert "utility=0.333" in details[2]
    for c in calls:
        assert c["actor"] == "telemetry"
        assert c["artifact"] == "lesson-abc.md"


def test_emit_failure_does_not_corrupt_counters(tmp_path, monkeypatch):
    """A crashed emit must NOT corrupt the file (read first, write only after)."""
    # Arrange
    lib = tmp_path / "lib"
    lib.mkdir()
    _write_lesson(lib, "abc")
    import kunglao_log

    def _boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(kunglao_log, "emit", _boom)

    # Act — citation still succeeds (counters are on-disk source of truth)
    r = lt.record_citation(lib, "abc")

    # Assert
    assert r["ok"] is True
    fm = _frontmatter(lib / "lesson-abc.md")
    assert fm["citation_count"] == 1