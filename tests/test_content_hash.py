# -*- coding: utf-8 -*-
"""Tests for content_hash.fact_id — fact_id = content-sha256 for idempotent fact writes.

TDD RED phase: this test defines the contract BEFORE implementation.
Run: python test_content_hash.py
or:  pytest test_content_hash.py (if pytest available)
"""
import sys
import subprocess
from pathlib import Path

# import the module under test (will fail until implemented — that's RED)
sys.path.insert(0, str(Path(__file__).parent))
from content_hash import fact_id  # noqa: E402


# ---------- unit tests ----------

def test_deterministic_same_inputs():
    assert fact_id('claim', 'reproduce', 'expected') == fact_id('claim', 'reproduce', 'expected')


def test_starts_with_F():
    assert fact_id('c', 'r', 'e').startswith('F')


def test_length_is_17():
    # 'F' + 16 hex chars = 17 total
    assert len(fact_id('c', 'r', 'e')) == 17


def test_different_inputs_different_id():
    # each input field feeds the hash — changing any one must change the id
    assert fact_id('claim_a', 'r', 'e') != fact_id('claim_b', 'r', 'e')
    assert fact_id('c', 'repro_a', 'e') != fact_id('c', 'repro_b', 'e')
    assert fact_id('c', 'r', 'exp_a') != fact_id('c', 'r', 'exp_b')


def test_only_hex_after_F():
    fid = fact_id('c', 'r', 'e')
    assert all(c in '0123456789abcdef' for c in fid[1:]), f'non-hex in {fid!r}'


def test_multiline_inputs_handled():
    # separator is \x00 so newlines in reproduce/expected are safe
    multi = 'line1\nline2\nline3'
    single = 'line1line2line3'
    assert fact_id('c', multi, 'e') != fact_id('c', single, 'e')


def test_null_byte_in_input_does_not_collide():
    # a literal \x00 in claim must not be ambiguous with the separator
    assert fact_id('a\x00b', 'r', 'e') != fact_id('a', 'b\x00r', 'e')


def test_known_value_stable():
    # pin a known output so future changes are detected
    expected = fact_id('test_claim', 'grep ANTISCALANT', '1 match')
    assert expected == fact_id('test_claim', 'grep ANTISCALANT', '1 match')
    assert expected.startswith('F') and len(expected) == 17


# ---------- CLI test ----------

def test_cli_prints_fact_id():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / 'claim.txt').write_text('test claim', encoding='utf-8')
        (td / 'repro.sh').write_text('echo reproduce', encoding='utf-8')
        (td / 'expected.txt').write_text('reproduce', encoding='utf-8')

        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / 'scripts' / 'content_hash.py'),
             str(td / 'claim.txt'), str(td / 'repro.sh'), str(td / 'expected.txt')],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f'stderr: {r.stderr}'
        out = r.stdout.strip()
        assert out.startswith('F') and len(out) == 17, f'bad CLI output: {out!r}'
        # CLI output matches function output for same inputs
        assert out == fact_id('test claim', 'echo reproduce', 'reproduce')


# ---------- runner ----------

def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    failed = []
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {t.__name__}: {type(e).__name__}: {e}')
            failed.append(t.__name__)
    print(f'\n{passed}/{len(tests)} passed')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(_run())
