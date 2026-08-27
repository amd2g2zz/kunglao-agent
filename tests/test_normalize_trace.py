# -*- coding: utf-8 -*-
"""Tests for normalize_trace.normalize — VERIFY-side trace normalization (DESIGN §12).

Dynamic VERIFY must diff traces across runs deterministically. Pointers/timestamps/
addresses vary per run; logical API-call sequence must hash identically.

normalize(trace, tool) -> list[(api_name, sha256(cleaned_args)[:8]), ...] ordered.

TDD RED phase.
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from normalize_trace import normalize  # noqa: E402


QILING_TRACE = {
    'api_calls': [
        {'name': 'WriteFile', 'args': ['handle=0x123', 'buffer=0x7fffabc']},
        {'name': 'CloseHandle', 'args': ['handle=0x123']},
    ],
}

# Same LOGICAL calls, different pointer VALUES — must normalize identically.
QILING_TRACE_DIFF_PTRS = {
    'api_calls': [
        {'name': 'WriteFile', 'args': ['handle=0x999', 'buffer=0xaaa']},
        {'name': 'CloseHandle', 'args': ['handle=0x999']},
    ],
}

QILING_TRACE_SWAPPED = {
    'api_calls': [
        {'name': 'CloseHandle', 'args': ['handle=0x123']},
        {'name': 'WriteFile', 'args': ['handle=0x123', 'buffer=0x7fffabc']},
    ],
}

FRIDA_LOG = (
    'WriteFile(handle=0x123, buffer=0x456)\n'
    'CloseHandle(handle=0x123)\n'
)

FRIDA_LOG_DIFF_PTRS = (
    'WriteFile(handle=0xabc, buffer=0xdef)\n'
    'CloseHandle(handle=0xabc)\n'
)


# ---------- qiling ----------

def test_qiling_basic():
    out = normalize(QILING_TRACE, 'qiling')
    assert len(out) == 2
    assert out[0][0] == 'WriteFile'
    assert out[1][0] == 'CloseHandle'


def test_qiling_pointer_invariance():
    # Same logical calls, different pointer values -> identical normalized output
    assert normalize(QILING_TRACE, 'qiling') == normalize(QILING_TRACE_DIFF_PTRS, 'qiling')


def test_qiling_order_matters():
    assert normalize(QILING_TRACE, 'qiling') != normalize(QILING_TRACE_SWAPPED, 'qiling')


def test_qiling_hash_is_8_hex():
    out = normalize(QILING_TRACE, 'qiling')
    for _api, h in out:
        assert len(h) == 8
        assert all(c in '0123456789abcdef' for c in h)


# ---------- frida ----------

def test_frida_basic():
    out = normalize(FRIDA_LOG, 'frida')
    assert len(out) == 2
    assert out[0][0] == 'WriteFile'
    assert out[1][0] == 'CloseHandle'


def test_frida_pointer_invariance():
    assert normalize(FRIDA_LOG, 'frida') == normalize(FRIDA_LOG_DIFF_PTRS, 'frida')


# ---------- semantic ----------

def test_different_semantic_args_different_hash():
    # Same api, different NON-pointer arg (path is semantic, kept); the
    # path values are built with os.sep per #690 (no path literals).
    import os
    p1 = "path=" + os.sep + "foo"
    p2 = "path=" + os.sep + "bar"
    t1 = {'api_calls': [{'name': 'CreateFile', 'args': [p1]}]}
    t2 = {'api_calls': [{'name': 'CreateFile', 'args': [p2]}]}
    assert normalize(t1, 'qiling')[0][1] != normalize(t2, 'qiling')[0][1]


def test_deterministic():
    assert normalize(QILING_TRACE, 'qiling') == normalize(QILING_TRACE, 'qiling')


def test_empty_trace():
    assert normalize({'api_calls': []}, 'qiling') == []
    assert normalize('', 'frida') == []


def test_qiling_json_string_accepted():
    import json
    s = json.dumps(QILING_TRACE)
    assert normalize(s, 'qiling') == normalize(QILING_TRACE, 'qiling')


# ---------- CLI ----------

def test_cli():
    import tempfile, json
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        f = td / 'trace.json'
        f.write_text(json.dumps(QILING_TRACE), encoding='utf-8')
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / 'scripts' / 'normalize_trace.py'),
             str(f), '--tool', 'qiling'],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f'stderr: {r.stderr}'
        lines = [ln for ln in r.stdout.strip().splitlines() if ln]
        assert len(lines) == 2
        assert lines[0].startswith('WriteFile|')


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
