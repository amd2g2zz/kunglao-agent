"""Tests for scripts/update_index.py — atomic facts/_INDEX.md maintenance (DESIGN §13.6).

_INDEX.md is the orchestrator's O(1) status-count source. Format: one row per fact:
  F<hash> | <status> | <claim_id> | <one-line conclusion>

upsert must be atomic (tmp→rename) so concurrent writers don't lose rows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from update_index import upsert, read_index, count_by_status  # noqa: E402


def _new_index(tmp_path):
    return tmp_path / '_INDEX.md'


def test_upsert_to_empty(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Faaa', 'PROVEN', 'C-001', 'ANTISCALANT is a map key')
    rows = read_index(idx)
    assert len(rows) == 1
    assert rows[0]['fact_id'] == 'Faaa'
    assert rows[0]['status'] == 'PROVEN'
    assert rows[0]['claim_id'] == 'C-001'
    assert rows[0]['conclusion'] == 'ANTISCALANT is a map key'


def test_upsert_replaces_existing(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Faaa', 'INFERRED', 'C-001', 'pending')
    upsert(idx, 'Faaa', 'PROVEN', 'C-001', 'confirmed now')
    rows = read_index(idx)
    assert len(rows) == 1
    assert rows[0]['status'] == 'PROVEN'
    assert rows[0]['conclusion'] == 'confirmed now'


def test_upsert_preserves_others(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Faaa', 'PROVEN', 'C-001', 'first')
    upsert(idx, 'Fbbb', 'DEFERRED', 'C-002', 'second')
    upsert(idx, 'Faaa', 'NEGATIVE', 'C-001', 'updated first')
    rows = read_index(idx)
    assert len(rows) == 2
    by_id = {r['fact_id']: r for r in rows}
    assert by_id['Faaa']['status'] == 'NEGATIVE'
    assert by_id['Fbbb']['status'] == 'DEFERRED'


def test_upsert_preserves_file_header_comments(tmp_path):
    idx = _new_index(tmp_path)
    idx.write_text('# facts/_INDEX.md — orchestrator-maintained\n# do not edit\n', encoding='utf-8')
    upsert(idx, 'Faaa', 'PROVEN', 'C-001', 'first fact')
    text = idx.read_text(encoding='utf-8')
    assert text.startswith('# facts/_INDEX.md')
    rows = read_index(idx)
    assert len(rows) == 1


def test_upsert_atomic_no_tmp_linger(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Faaa', 'PROVEN', 'C-001', 'x')
    assert not (tmp_path / '_INDEX.md.tmp').exists()


def test_count_by_status(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Fa', 'PROVEN', 'C-001', 'a')
    upsert(idx, 'Fb', 'PROVEN', 'C-002', 'b')
    upsert(idx, 'Fc', 'DEFERRED', 'C-003', 'c')
    upsert(idx, 'Fd', 'OPEN', 'C-004', 'd')
    counts = count_by_status(idx)
    assert counts['PROVEN'] == 2
    assert counts['DEFERRED'] == 1
    assert counts['OPEN'] == 1
    assert counts.get('NEGATIVE', 0) == 0


def test_count_all_terminal(tmp_path):
    idx = _new_index(tmp_path)
    upsert(idx, 'Fa', 'PROVEN', 'C-001', 'a')
    upsert(idx, 'Fb', 'DEFERRED', 'C-002', 'b')
    upsert(idx, 'Fc', 'NEGATIVE', 'C-003', 'c')
    counts = count_by_status(idx)
    terminal = counts.get('PROVEN', 0) + counts.get('VERIFIED', 0) + counts.get('NEGATIVE', 0) + counts.get('REFUTED', 0) + counts.get('DEFERRED', 0)
    assert terminal == 3


def test_read_empty(tmp_path):
    idx = _new_index(tmp_path)
    assert read_index(idx) == []
    assert count_by_status(idx) == {}


def _run():
    import inspect
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    failed = []
    for name, t in tests:
        sig = inspect.signature(t)
        try:
            if 'tmp_path' in sig.parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    t(Path(td))
            else:
                t()
            print(f'  PASS  {name}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {name}: {type(e).__name__}: {e}')
            failed.append(name)
    print(f'\n{passed}/{len(tests)} passed')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(_run())
