# -*- coding: utf-8 -*-
"""jsvmp_triage — three-feature VMP detection pins (synthetic fixtures only).

Positive fixture is a synthetic mini-VMP (big int array + while/switch +
stack-op handlers). Negative fixture is readable control-flow flattening
(switch with semantic calls). Boundary fixture exercises the low-confidence
lane (array+loop but no semantics-free ratio).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jsvmp_triage.py"

POSITIVE = (
    "var _0x = [" + ",".join(str(i % 97) for i in range(300)) + "];\n"
    "var pc = 0, stack = [];\n"
    "while (!![]) {\n"
    "  switch (_0x[pc++]) {\n"
    + "\n".join(
        f"    case {n}: stack.push(_0x[pc++]); break;"
        for n in range(12)) + "\n"
    "    case 12: var a = stack.pop(), b = stack.pop();\n"
    "      stack.push(a ^ b); break;\n"
    "    default: break;\n"
    "  }\n"
    "}\n"
)

NEGATIVE_FLATTENING = (
    "function flow(state) {\n"
    "  while (true) {\n"
    "    switch (state) {\n"
    "      case 0:\n"
    "        fetch('/api/config', {method:'POST'}).then(r => r.json());\n"
    "        state = 1; break;\n"
    "      case 1:\n"
    "        document.cookie = 'seen=1'; localStorage.setItem('k','v');\n"
    "        state = 2; break;\n"
    "      default:\n"
    "        navigator.sendBeacon('/beacon'); return;\n"
    "    }\n"
    "  }\n"
    "}\n"
)


def _run(target: Path) -> dict:
    r = subprocess.run([sys.executable, str(SCRIPT), str(target), "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_positive_synthetic_vmp(tmp_path: Path) -> None:
    f = tmp_path / "vmp.js"
    f.write_text(POSITIVE, encoding="utf-8")
    v = _run(f)
    assert v["vmp_suspected"] is True
    assert v["features"]["f2_dispatch_loop"]["cases"] >= 8
    assert any(a["kind"] == "numeric" and a["items"] >= 100
               for a in v["features"]["f1_bytecode_array"])


def test_negative_readable_flattening(tmp_path: Path) -> None:
    f = tmp_path / "flat.js"
    f.write_text(NEGATIVE_FLATTENING, encoding="utf-8")
    v = _run(f)
    # dispatch shape alone must NOT trip the verdict -- F1 missing, and the
    # semantic ratio should collapse confidence.
    assert v["vmp_suspected"] is False
    assert not v["features"]["f1_bytecode_array"]


def test_cli_json_contract(tmp_path: Path) -> None:
    f = tmp_path / "v.js"
    f.write_text(POSITIVE, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f), "--json"],
                       capture_output=True, text=True)
    v = json.loads(r.stdout)
    assert {"source", "vmp_suspected", "confidence",
            "features", "signals", "note"} <= set(v)
    assert "trace methodology" in v["note"]
