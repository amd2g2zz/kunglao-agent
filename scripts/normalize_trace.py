# -*- coding: utf-8 -*-
"""normalize_trace — dynamic VERIFY trace normalization (DESIGN §12).

Dynamic claims (Qiling emulation / Frida hook) produce traces whose pointer
values, timestamps, and addresses vary per run. VERIFY must diff them
deterministically: the logical API-call sequence hashes identically across
runs, so re-running the same tool with the same inputs reproduces the same
normalized trace.

normalize(trace, tool) -> [(api_name, sha256(cleaned_args)[:8]), ...] ordered.

Pointers (0x[hex]+) are stripped from args before hashing; non-pointer args
(e.g. file paths) are kept so genuinely different calls hash differently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# hex pointer-like values: 0x followed by 1+ hex digits
HEX_PTR = re.compile(r'0x[0-9a-fA-F]+')
# frida call log line: "ApiName(arg1=val1, arg2=val2)"
FRIDA_LINE = re.compile(r'^\s*(\w+)\s*\((.*)\)\s*$')


def normalize(trace, tool: str) -> list[tuple[str, str]]:
    """Return ordered [(api_name, args_hash[:8]), ...] with pointers stripped.

    trace: dict|json-str (qiling) or str (frida log).
    tool: 'qiling' | 'frida'.
    """
    if tool == 'qiling':
        events = _parse_qiling(trace)
    elif tool == 'frida':
        events = _parse_frida(trace)
    else:
        raise ValueError(f'unknown tool: {tool!r}')
    return [(api, _hash(_clean(args))) for api, args in events]


def _parse_qiling(trace) -> list[tuple[str, str]]:
    if isinstance(trace, str):
        trace = json.loads(trace)
    out = []
    for call in trace.get('api_calls', []):
        name = call.get('name', '')
        args = call.get('args', [])
        if isinstance(args, (list, tuple)):
            args = ', '.join(str(a) for a in args)
        out.append((name, args))
    return out


def _parse_frida(trace: str) -> list[tuple[str, str]]:
    out = []
    for line in trace.splitlines():
        m = FRIDA_LINE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _clean(args: str) -> str:
    """Strip pointer-like hex values; keep semantic content (paths, names)."""
    return HEX_PTR.sub('', args)


def _hash(args: str) -> str:
    return hashlib.sha256(args.encode('utf-8')).hexdigest()[:8]


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description='Normalize a dynamic-tool trace for VERIFY diff.')
    p.add_argument('trace_file', help='path to trace (JSON for qiling, text for frida)')
    p.add_argument('--tool', required=True, choices=['qiling', 'frida'])
    a = p.parse_args(argv)
    content = Path(a.trace_file).read_text(encoding='utf-8')
    trace = json.loads(content) if a.tool == 'qiling' else content
    for api, h in normalize(trace, a.tool):
        print(f'{api}|{h}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
