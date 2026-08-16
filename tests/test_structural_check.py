"""test_structural_check.py -- CI structural integrity (#141)."""
from __future__ import annotations
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from structural_check import check_re_library_orphans, check_index_drift, check_reference_links

def test_orphan_detection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        re_lib = root / 'references' / 're-library'
        re_lib.mkdir(parents=True)
        (re_lib / 'tools.md').write_text('referenced', encoding='utf-8')
        (re_lib / 'orphan.md').write_text('not referenced', encoding='utf-8')
        (root / 'SKILL.md').write_text('See tools.md here.', encoding='utf-8')
        orphans = check_re_library_orphans(root)
        assert any('orphan.md' in o for o in orphans)
        assert not any('tools.md' in o for o in orphans)

def test_index_drift_missing_in_index():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        facts = root / 'facts'
        facts.mkdir()
        (facts / 'F001.md').write_text('test', encoding='utf-8')
        (facts / '_INDEX.md').write_text('No facts here.', encoding='utf-8')
        drift = check_index_drift(root)
        assert any('MISSING_IN_INDEX' in d for d in drift)

def test_reference_links():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        refs = root / 'references'
        refs.mkdir()
        (refs / 'a.md').write_text('Link to [b](b.md).', encoding='utf-8')
        broken = check_reference_links(root)
        assert any('b.md' in b for b in broken)

def test_no_false_positives():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        refs = root / 'references'
        refs.mkdir()
        (refs / 'a.md').write_text('Link to [b](b.md).', encoding='utf-8')
        (refs / 'b.md').write_text('content', encoding='utf-8')
        broken = check_reference_links(root)
        assert broken == []
