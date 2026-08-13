"""Smoke test for the full cognitive memory pipeline (F1-F4).

Validates:
  F2 (recall) - top-K scoring, skip rules (low confidence, superseded, archived, stale-no-citations)
  F4 (forget)  - decay, supersede, prune all behave atomically + archive to .archived/
  F1 (capture) - classify_event fires on each event source; writes staging entry
  F3 (auto-distill) - staging crossing threshold triggers distill.py

Run: python <skill_root>/memory/scripts/test_cognitive_memory.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall as rc
import forget as fg
import memory_capture as mc
import distill as dt


def _make_longterm_entry(
    longterm_dir: Path,
    name: str,
    *,
    confidence: float = 0.8,
    citations: int = 3,
    age_days: int = 0,
    cross_project: bool = True,
    tags=None,
    superseded_by=None,
) -> Path:
    longterm_dir.mkdir(parents=True, exist_ok=True)
    p = longterm_dir / f"{name}.md"
    mod_dt = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
    fm = {
        "name": name,
        "description": f"Test rule {name}",
        "metadata": {
            "node_type": "memory",
            "type": "rule",
            "originSessionId": "test",
            "modified": mod_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cross_project": cross_project,
            "confidence": confidence,
            "citations": citations,
            "tags": tags or [],
        },
    }
    if superseded_by:
        fm["metadata"]["superseded_by"] = superseded_by
    body = "\n## Rule\nSynthetic.\n\n## Examples\n- example\n"
    yaml_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    p.write_text(f"---\n{yaml_text}---{body}", encoding="utf-8")
    return p


def _swap_longterm(longterm_dir: Path):
    true = rc.LONGTERM_DIR, fg.LONGTERM_DIR
    rc.LONGTERM_DIR = longterm_dir
    fg.LONGTERM_DIR = longterm_dir
    def restore():
        rc.LONGTERM_DIR, fg.LONGTERM_DIR = true
    return restore


def test_recall_top_k_basic():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        for i, conf in enumerate([0.9, 0.7, 0.5, 0.4, 0.85, 0.3]):
            _make_longterm_entry(lt, f"r{i}", confidence=conf)
        restore = _swap_longterm(lt)
        try:
            top3 = rc.recall(top_k=3, ctx={})
            assert len(top3) == 3, f"expected 3, got {len(top3)}"
            assert top3[0]["name"] == "r0", f"expected r0, got {top3[0]['name']}"
            print("  [OK ] recall top-K returns highest-scored first")
        finally:
            restore()


def test_recall_skips_low_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "high", confidence=0.8)
        _make_longterm_entry(lt, "low", confidence=0.2)
        restore = _swap_longterm(lt)
        try:
            top5 = rc.recall(top_k=5, ctx={})
            names = [e["name"] for e in top5]
            assert "high" in names
            assert "low" not in names, f"low should be skipped: {names}"
            print("  [OK ] recall skips confidence < 0.3")
        finally:
            restore()


def test_recall_skips_superseded():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "newer", confidence=0.9)
        _make_longterm_entry(lt, "older", confidence=0.7, superseded_by="newer")
        restore = _swap_longterm(lt)
        try:
            top5 = rc.recall(top_k=5, ctx={})
            names = [e["name"] for e in top5]
            assert "newer" in names
            assert "older" not in names, f"superseded should be skipped: {names}"
            print("  [OK ] recall skips superseded")
        finally:
            restore()


def test_recall_skips_stale_no_citations():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "fresh", age_days=10, citations=0)
        _make_longterm_entry(lt, "stale", age_days=100, citations=1)
        restore = _swap_longterm(lt)
        try:
            top5 = rc.recall(top_k=5, ctx={})
            names = [e["name"] for e in top5]
            assert "fresh" in names
            assert "stale" not in names, f"stale should be skipped: {names}"
            print("  [OK ] recall skips stale-no-citations")
        finally:
            restore()


def test_recall_format_block():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "alpha", confidence=0.9, citations=5)
        restore = _swap_longterm(lt)
        try:
            block = rc.format_block(rc.recall(top_k=5, ctx={}))
            assert "## Recalled rules" in block
            assert "**alpha**" in block
            assert "confidence 0.90" in block
            print("  [OK ] recall format_block produces markdown")
        finally:
            restore()


def test_forget_decay_reduces_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "old_no_cite", confidence=0.5, citations=0, age_days=40)
        restore = _swap_longterm(lt)
        try:
            changes = fg.decay(dry_run=False)
            assert len(changes) == 1
            assert changes[0]["old"] == 0.5
            assert changes[0]["new"] == 0.4
            fm = yaml.safe_load((lt / "old_no_cite.md").read_text(encoding="utf-8").split("---")[1])
            assert fm["metadata"]["confidence"] == 0.4
            print("  [OK ] forget.decay reduces confidence by 0.1")
        finally:
            restore()


def test_forget_decay_archives_at_floor():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "doomed", confidence=0.35, citations=0, age_days=40)
        restore = _swap_longterm(lt)
        try:
            fg.decay(dry_run=False)
            assert not (lt / "doomed.md").exists(), "doomed should be archived"
            assert (lt / ".archived" / "doomed.md").exists(), "should be in .archived/"
            print("  [OK ] forget.decay archives when confidence hits 0.3 floor")
        finally:
            restore()


def test_forget_decay_skips_well_cited():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "popular", confidence=0.7, citations=10, age_days=40)
        restore = _swap_longterm(lt)
        try:
            changes = fg.decay(dry_run=False)
            assert changes == [], f"well-cited should not decay: {changes}"
            print("  [OK ] forget.decay skips well-cited entries")
        finally:
            restore()


def test_forget_supersede_marks_older():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "newer", confidence=0.9)
        _make_longterm_entry(lt, "older", confidence=0.85)
        restore = _swap_longterm(lt)
        try:
            path, applied = fg.supersede("newer", "older", dry_run=False)
            assert applied
            fm = yaml.safe_load((lt / "older.md").read_text(encoding="utf-8").split("---")[1])
            assert fm["metadata"]["superseded_by"] == "newer"
            assert fm["metadata"]["confidence"] == 0.4
            print("  [OK ] forget.supersede marks older with confidence=0.4")
        finally:
            restore()


def test_forget_prune_archives_superseded():
    with tempfile.TemporaryDirectory() as tmp:
        lt = Path(tmp) / "longterm"
        _make_longterm_entry(lt, "active", confidence=0.7, citations=2, age_days=5)
        _make_longterm_entry(lt, "doomed", confidence=0.7, citations=2, age_days=5, superseded_by="newer")
        restore = _swap_longterm(lt)
        try:
            fg.prune(dry_run=False)
            assert (lt / "active.md").exists()
            assert not (lt / "doomed.md").exists()
            assert (lt / ".archived" / "doomed.md").exists()
            print("  [OK ] forget.prune archives superseded entries")
        finally:
            restore()


def test_capture_self_correction_on_skill_edit():
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        longterm = Path(tmp) / "longterm"
        staging.mkdir()
        longterm.mkdir()
        original_memory_dir = mc.MEMORY_DIR
        original_staging = mc.STAGING_DIR
        original_distill_script = mc.DISTILL_SCRIPT
        mc.MEMORY_DIR = Path(tmp)
        mc.STAGING_DIR = staging
        mc.DISTILL_SCRIPT = longterm / "distill.py"
        try:
            payload = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(Path(__file__).resolve().parent.parent.parent / "SKILL.md")},
                "tool_result": "ok",
            }
            cls = mc.classify_event(payload)
            assert cls is not None
            tag, context = cls
            assert tag == "self-correction"
            path = mc.write_staging_entry(tag, context)
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "self-correction" in content
            print("  [OK ] capture fires on SKILL.md Edit")
        finally:
            mc.MEMORY_DIR = original_memory_dir
            mc.STAGING_DIR = original_staging
            mc.DISTILL_SCRIPT = original_distill_script


def test_capture_worker_failure_on_agent_tool():
    payload = {
        "tool_name": "Agent",
        "tool_input": {"description": "[T1 tools=grep] claim C-001 ..."},
        "tool_result": "Worker status: blocked: cannot find bins/<sha>",
    }
    cls = mc.classify_event(payload)
    assert cls is not None
    tag, context = cls
    assert tag == "worker-failure"
    assert "blocked" in context["status"]
    print("  [OK ] capture fires on Agent blocked result")


def test_capture_dispatch_reject():
    payload = {
        "tool_name": "Agent",
        "tool_input": {"description": "[T1 tools=...] claim C-001 ..."},
        "tool_result": "REJECT workers: active_workers=3 >= 3",
    }
    cls = mc.classify_event(payload)
    assert cls is not None
    tag, _ = cls
    assert tag == "dispatch-reject"
    print("  [OK ] capture fires on dispatch REJECT")


def test_capture_no_match_for_unrelated_event():
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/some/other/file.md"},
        "tool_result": "ok",
    }
    cls = mc.classify_event(payload)
    assert cls is None
    print("  [OK ] capture correctly returns None for unrelated events")


def test_capture_triggers_distill_at_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        longterm = Path(tmp) / "longterm"
        staging.mkdir()
        longterm.mkdir()
        original_staging = mc.STAGING_DIR
        original_longterm = mc.LONGTERM_DIR
        original_distill_script = mc.DISTILL_SCRIPT
        original_dt_staging = dt.STAGING_DIR
        original_dt_longterm = dt.LONGTERM_DIR
        mc.MEMORY_DIR = Path(tmp)
        mc.STAGING_DIR = staging
        mc.LONGTERM_DIR = longterm
        mc.DISTILL_SCRIPT = Path(tmp) / "scripts" / "distill.py"
        (Path(tmp) / "scripts").mkdir()
        shutil.copy(Path(__file__).resolve().parent / "distill.py",
                    mc.DISTILL_SCRIPT)
        dt.STAGING_DIR = staging
        dt.LONGTERM_DIR = longterm
        try:
            for i in range(10):
                p = staging / f"2026-07-31-prefill-{i}.md"
                p.write_text(f"---\nname: pre{i}\n---\n## Symptom\nx\n## Repro\ny\n## Fix applied\nz\n", encoding="utf-8")
            rc.maybe_auto_distill() if hasattr(rc, 'maybe_auto_distill') else mc.maybe_auto_distill()
            lt_files = [f for f in longterm.glob("*.md") if f.name != "INDEX.md"]
            assert len(lt_files) == 1, f"expected distill to fire, got {len(lt_files)} longterm files"
            st_files = [f for f in staging.glob("*.md") if f.name not in {"INDEX.md", ".distill.lock"} and not f.name.startswith(".snapshot")]
            assert len(st_files) == 0, f"expected staging cleared, got {st_files}"
            print("  [OK ] auto-distill fires at threshold (10 entries)")
        finally:
            mc.STAGING_DIR = original_staging
            mc.LONGTERM_DIR = original_longterm
            mc.DISTILL_SCRIPT = original_distill_script
            dt.STAGING_DIR = original_dt_staging
            dt.LONGTERM_DIR = original_dt_longterm


def main() -> int:
    print("=" * 70)
    print("kunglao-agent cognitive memory smoke suite (F1+F2+F3+F4)")
    print("=" * 70)
    tests = [
        test_recall_top_k_basic,
        test_recall_skips_low_confidence,
        test_recall_skips_superseded,
        test_recall_skips_stale_no_citations,
        test_recall_format_block,
        test_forget_decay_reduces_confidence,
        test_forget_decay_archives_at_floor,
        test_forget_decay_skips_well_cited,
        test_forget_supersede_marks_older,
        test_forget_prune_archives_superseded,
        test_capture_self_correction_on_skill_edit,
        test_capture_worker_failure_on_agent_tool,
        test_capture_dispatch_reject,
        test_capture_no_match_for_unrelated_event,
        test_capture_triggers_distill_at_threshold,
    ]
    fails = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            fails.append(t.__name__)
        except Exception as e:
            print(f"  [ERR ] {t.__name__}: {e}")
            fails.append(t.__name__)
    print("=" * 70)
    if not fails:
        print(f"ALL_OK ({len(tests)} tests passed)")
        return 0
    print(f"FAILURES: {fails}")
    return 1


if __name__ == "__main__":
    sys.exit(main())