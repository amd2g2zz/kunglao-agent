"""test_review_gate_hardening.py -- gate hardening tests (#147)."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / 'scripts' / 'review_gate.py'

def _run_gate(args, cwd=None):
    result = subprocess.run([sys.executable, str(GATE)] + args,
                           capture_output=True, text=True, cwd=cwd or REPO)
    return result.returncode, result.stdout + result.stderr

def test_mint_rejects_empty_key():
    with tempfile.TemporaryDirectory() as tmp:
        empty_key = Path(tmp) / 'empty.key'
        empty_key.write_text('')
        rc, out = _run_gate(['mint', str(REPO), str(empty_key), 'test-branch',
                            str(REPO / 'runs' / 'review-r2-gate-*.md'),
                            'r2-gate-a', 'r2-gate-b', 'r2-gate-c'])
        assert rc == 2, f'Expected rc=2, got {rc}: {out}'
        assert 'too short' in out.lower()

def test_check_rejects_empty_key():
    with tempfile.TemporaryDirectory() as tmp:
        empty_key = Path(tmp) / 'empty.key'
        empty_key.write_text('')
        gate_dir = REPO / '.review-gate'
        gate_dir.mkdir(exist_ok=True)
        outfile = gate_dir / 'test-branch.json'
        outfile.write_text(json.dumps({'branch': 'test-branch', 'diff_sha256': 'x',
                               'reviewers': ['r2-gate-a','r2-gate-b','r2-gate-c'],
                               'minted_ts': 0, 'hmac': 'x'}))
        rc, out = _run_gate(['check', str(REPO), str(outfile), 'test-branch', str(empty_key)])
        assert rc != 0, f'Expected non-zero rc, got {rc}: {out}'
        outfile.unlink(missing_ok=True)

def test_check_rejects_missing_key():
    gate_dir = REPO / '.review-gate'
    gate_dir.mkdir(exist_ok=True)
    outfile = gate_dir / 'missing-key-test.json'
    outfile.write_text(json.dumps({'branch': 'missing-key-test', 'diff_sha256': 'x',
                           'reviewers': ['r2-gate-a'], 'minted_ts': 0, 'hmac': 'x'}))
    rc, out = _run_gate(['check', str(REPO), str(outfile), 'missing-key-test',
                        str(Path(tempfile.gettempdir()) / 'nonexistent.key')])
    assert rc != 0
    outfile.unlink(missing_ok=True)

def test_mint_rejects_bad_prefix_reviewer():
    real_key = Path(os.path.expanduser('~/.claude/kunglao-review.key'))
    if not real_key.exists():
        import pytest; pytest.skip('no review key available')
    rc, out = _run_gate(['mint', str(REPO), str(real_key), 'prefix-test',
                        str(REPO / 'runs' / 'review-nonexist-*.md'),
                        'bad-prefix-a', 'bad-prefix-b', 'bad-prefix-c'])
    assert rc == 2

def test_key_init_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        k = Path(tmp) / 'newkey.key'
        rc, out = _run_gate(['key-init', str(k)])
        assert rc == 0
        assert k.exists()
        content = k.read_text().strip()
        assert len(content) >= 64
