"""Tests for scripts/reconcile_intents.py — WAL cold-restart reconciliation (DESIGN §14).

On cold-restart, scan intents. Report:
  - in_flight intent → 're-dispatch' the claim (idempotent via fact_id)
  - fact file (content-hash id, len 17) with NO intent at all → 'orphan' → blockers/

Pre-existing ordinal facts (F001, len 4) are exempt — they predate kunglao-agent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from reconcile_intents import reconcile, read_intents  # noqa: E402


def _write_intents(path, intents):
    lines = ['[current_task]', 'sample=x', '[/current_task]', '']
    if intents:
        lines.append('[intents]')
        for i in intents:
            lines.append(
                f"intent_id={i['intent_id']} | claim_id={i['claim_id']} | "
                f"worker_id={i.get('worker_id','')} | fact_id={i.get('fact_id','')} | "
                f"status={i['status']}"
            )
        lines.append('[/intents]')
    path.write_text('\n'.join(lines), encoding='utf-8')


def _make_fact(d, fact_id):
    (d / 'facts').mkdir(exist_ok=True)
    (d / 'facts' / f'{fact_id}.md').write_text(f'# {fact_id}\n', encoding='utf-8')


def test_read_intents_empty(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [])
    assert read_intents(p) == []


def test_read_intents_entries(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'Faaa', 'status': 'completed'},
        {'intent_id': 'i2', 'claim_id': 'C-002', 'fact_id': 'Fbbb', 'status': 'in_flight'},
    ])
    ints = read_intents(p)
    assert len(ints) == 2
    assert ints[0]['status'] == 'completed'
    assert ints[1]['status'] == 'in_flight'


def test_all_completed_no_issues(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'Faaa', 'status': 'completed'},
    ])
    issues = reconcile(p, tmp_path / 'facts')
    assert issues == []


def test_in_flight_reports_redispatch(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'Faaa', 'status': 'completed'},
        {'intent_id': 'i2', 'claim_id': 'C-002', 'fact_id': 'Fbbb', 'status': 'in_flight'},
    ])
    issues = reconcile(p, tmp_path / 'facts')
    assert len(issues) == 1
    assert issues[0]['kind'] == 're-dispatch'
    assert issues[0]['claim_id'] == 'C-002'
    assert issues[0]['fact_id'] == 'Fbbb'


def test_orphan_fact_flagged(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [])
    _make_fact(tmp_path, 'F0123456789abcdef')
    issues = reconcile(p, tmp_path / 'facts')
    assert len(issues) == 1
    assert issues[0]['kind'] == 'orphan'
    assert issues[0]['fact_id'] == 'F0123456789abcdef'


def test_ordinal_fact_not_flagged(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [])
    _make_fact(tmp_path, 'F001')
    issues = reconcile(p, tmp_path / 'facts')
    assert issues == []


def test_orphan_with_completed_intent_not_flagged(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'F0123456789abcdef', 'status': 'completed'},
    ])
    _make_fact(tmp_path, 'F0123456789abcdef')
    issues = reconcile(p, tmp_path / 'facts')
    assert issues == []


def test_no_state_file(tmp_path):
    issues = reconcile(tmp_path / 'nonexistent.txt', tmp_path / 'facts')
    assert issues == []


def test_no_facts_dir(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'Faaa', 'status': 'in_flight'},
    ])
    issues = reconcile(p, tmp_path / 'facts')
    assert len(issues) == 1
    assert issues[0]['kind'] == 're-dispatch'


def test_mixed_in_flight_and_orphan(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_intents(p, [
        {'intent_id': 'i1', 'claim_id': 'C-001', 'fact_id': 'Faaa', 'status': 'completed'},
        {'intent_id': 'i2', 'claim_id': 'C-002', 'fact_id': 'Fbbb', 'status': 'in_flight'},
    ])
    _make_fact(tmp_path, 'Fcccc1234567890ab')  # orphan, len 17
    issues = reconcile(p, tmp_path / 'facts')
    kinds = sorted(i['kind'] for i in issues)
    assert kinds == ['orphan', 're-dispatch']


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
