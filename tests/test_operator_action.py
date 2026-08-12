"""test_operator_action.py — OPERATOR_ACTION ledger line type (#142)."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from status_defs import LedgerLineType, ledger_line_type


def test_operator_action_exists():
    assert hasattr(LedgerLineType, 'OPERATOR_ACTION')
    assert LedgerLineType.OPERATOR_ACTION == 'operator_action'


def test_record_operator_action():
    from convergence_check import record_operator_action, LEDGER_NAME
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        record_operator_action(ws, 'defer', claim_id='C-001',
                               reason='blocked', before='OPEN', after='DEFERRED')
        ledger = ws / LEDGER_NAME
        assert ledger.exists()
        lines = ledger.read_text(encoding='utf-8').strip().split(chr(10))
        row = json.loads(lines[-1])
        assert row['type'] == 'operator_action'
        assert row['action'] == 'defer'
        assert row['claim_id'] == 'C-001'
        assert ledger_line_type(row) == LedgerLineType.OPERATOR_ACTION


def test_operator_action_distinguishable():
    assert LedgerLineType.OPERATOR_ACTION != LedgerLineType.SNAPSHOT
    assert LedgerLineType.OPERATOR_ACTION != LedgerLineType.OUTCOME
