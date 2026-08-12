"""Smoke test for the kunglao-agent memory pipeline.

Validates:
1. memory_schema.py accepts a well-formed staging entry
2. memory_schema.py rejects malformed entries
3. distill.py --dry-run below threshold = NOOP
4. distill.py at threshold = candidate-first transaction (issue #82):
   one immutable candidate + journal `generated` row; staging KEPT until a
   completed evaluation receipt exists (never cleared merely because a
   candidate was attempted)
5. Schema rejects longterm with claim_id (cross_project purity)

Run: python <skill_root>/memory/scripts/test_memory_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_schema as ms
import distill as dt


def _make_tmp_md(content: str) -> Path:
    fd, name = tempfile.mkstemp(suffix=".md")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return Path(name)


def test_schema_accepts_valid_staging():
    fm = """---
name: test-entry
description: Smoke test entry
metadata:
  node_type: memory
  type: failure
  originSessionId: smoke-test
  modified: 2026-07-31T13:00:00Z
  claim_id: C-001
  confidence: 0.8
---
"""
    body = """## Symptom
Something broke.

## Repro
Run `something`.

## Fix applied
- file:line 42 -> fix description
"""
    tmp = _make_tmp_md(fm + body)
    try:
        ok, errors = ms.validate(tmp, "staging")
        assert ok, f"expected ok, got errors={errors}"
        print("  [OK ] schema accepts valid staging entry")
    finally:
        tmp.unlink()


def test_schema_rejects_missing_section():
    fm = """---
name: bad-entry
description: Missing Symptom
metadata:
  node_type: memory
  type: failure
  originSessionId: smoke-test
  modified: 2026-07-31T13:00:00Z
---
"""
    body = """## Repro
Run something.

## Fix applied
- nope
"""
    tmp = _make_tmp_md(fm + body)
    try:
        ok, errors = ms.validate(tmp, "staging")
        assert not ok, "expected fail, got ok"
        assert any("Symptom" in e for e in errors), f"expected Symptom error, got {errors}"
        print("  [OK ] schema rejects staging without Symptom")
    finally:
        tmp.unlink()


def test_schema_rejects_longterm_with_claim_id():
    fm = """---
name: bad-longterm
description: Has claim_id, should fail
metadata:
  node_type: memory
  type: rule
  originSessionId: smoke-test
  modified: 2026-07-31T13:00:00Z
  cross_project: true
  claim_id: C-001
---
"""
    body = """## Rule
Some rule.

## Examples
- example 1
"""
    tmp = _make_tmp_md(fm + body)
    try:
        ok, errors = ms.validate(tmp, "longterm")
        assert not ok, "expected fail, got ok"
        assert any("claim_id" in e for e in errors), f"expected claim_id error, got {errors}"
        print("  [OK ] schema rejects longterm with claim_id")
    finally:
        tmp.unlink()


def test_distill_threshold_enforcement():
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        longterm = Path(tmp) / "longterm"
        staging.mkdir()
        longterm.mkdir()
        _restore = _swap_paths(staging, longterm)
        try:
            for i in range(3):
                p = staging / f"entry-{i}.md"
                p.write_text("---\nname: e{i}\n---\n## Symptom\nx\n## Repro\ny\n## Fix applied\nz\n", encoding="utf-8")
            rc = dt.distill(threshold=10, dry_run=True)
            assert rc == 2, f"expected NOOP (rc=2), got rc={rc}"
            print("  [OK ] distill below threshold returns NOOP (rc=2)")
        finally:
            _restore()


def test_distill_atomic_transaction():
    """candidate-first (issue #82): 10 staging -> 1 immutable candidate + journal
    generated row; staging KEPT at distill time (receipt-gated clear)."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        longterm = Path(tmp) / "longterm"
        staging.mkdir()
        longterm.mkdir()
        _restore = _swap_paths(staging, longterm)
        try:
            for i in range(10):
                p = staging / f"2026-07-31-entry-{i:02d}.md"
                p.write_text(
                    f"---\nname: e{i}\ndescription: d\nmetadata:\n  type: failure\n  originSessionId: smoke\n  modified: 2026-07-31T13:00:00Z\n---\n## Symptom\nx{i}\n## Repro\ny\n## Fix applied\nz\n",
                    encoding="utf-8",
                )
            rc = dt.distill(threshold=10, force=True, dry_run=False)
            assert rc == 0, f"expected ok, got rc={rc}"

            cand_files = [f for f in dt.CANDIDATE_DIR.glob("*.md")]
            assert len(cand_files) == 1, f"expected 1 candidate record, got {len(cand_files)}: {[f.name for f in cand_files]}"

            lt_files = [f for f in longterm.glob("*.md") if f.name != "INDEX.md"]
            assert len(lt_files) == 0, f"longterm MUST be untouched before promotion, got {[f.name for f in lt_files]}"

            st_files = [f for f in staging.glob("*.md") if not f.name.startswith(".snapshot") and f.name != "INDEX.md"]
            assert len(st_files) == 10, f"staging MUST be kept at distill time (receipt-gated clear), got {len(st_files)}"

            rows = [json.loads(l) for l in dt.JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert any(r["action"] == "generated" for r in rows), f"journal missing generated row: {rows}"
            assert "status: CANDIDATE" in cand_files[0].read_text(encoding="utf-8")

            snap_files = list((staging / ".snapshot").rglob("*.md"))
            assert len(snap_files) == 10, f"expected 10 snapshot files, got {len(snap_files)}"

            print("  [OK ] candidate-first distill: 10 staging -> 1 CANDIDATE record + generated row + staging kept + 10 snapshots")
        finally:
            _restore()


def _swap_paths(staging: Path, longterm: Path):
    """Atomically swap dt path constants for a tmp tree and return a restore closure.

    Captures the *true* module-level originals (read at call time), not stale refs
    from a previous test's mutation.
    """
    pairs = [
        ("STAGING_DIR", staging),
        ("LONGTERM_DIR", longterm),
        ("CANDIDATE_DIR", staging.parent / "candidates"),
        ("RECEIPTS_DIR", staging.parent / "candidates" / "receipts"),
        ("CORPUS_DIR", staging.parent / "candidates" / "corpus"),
        ("BACKUP_DIR", staging.parent / "rules-backup"),
        ("JOURNAL_PATH", staging.parent / "lifecycle-journal.jsonl"),
        ("REGISTRY_PATH", staging.parent / "rules-registry.json"),
    ]
    true_values = {}
    for name, _ in pairs:
        true_values[name] = getattr(dt, name)
    for name, value in pairs:
        setattr(dt, name, value)
    dt.CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

    def restore():
        for name, _ in pairs:
            setattr(dt, name, true_values[name])
    return restore


def main() -> int:
    print("=" * 70)
    print("kunglao-agent memory pipeline smoke suite")
    print("=" * 70)
    tests = [
        test_schema_accepts_valid_staging,
        test_schema_rejects_missing_section,
        test_schema_rejects_longterm_with_claim_id,
        test_distill_threshold_enforcement,
        test_distill_atomic_transaction,
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