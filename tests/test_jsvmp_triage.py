# -*- coding: utf-8 -*-
"""jsvmp_triage — three-feature VMP detection pins (synthetic fixtures only).

Positive fixture is a synthetic mini-VMP (big int array + while/switch +
stack-op handlers). Negative fixture is readable control-flow flattening
(switch with semantic calls). Pair fixtures pin the three-of-two-votes
verdict (#884): {F1,F3} and {F2,F3} must each reach "suspected/medium".
The big-array-alone fixture is the hollow-F3 tripwire: a consumed integer
array with NO dispatch/case table must stay "low" (the semantic ratio is
1.0 by absence -- has_cases anchors F3 so absence cannot vote).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "web" / "jsvmp_triage.py"

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

# {F1,F3} pair: big consumed array + semantic-free case bodies, but no
# infinite-loop dispatch head -> F2 absent. Three-of-two must still suspect.
PAIR_F1_F3 = (
    "var tbl = [" + ",".join(str(i % 89) for i in range(250)) + "];\n"
    "var stack = [];\n"
    "function step(op) {\n"
    "  switch (op) {\n"
    + "\n".join(
        f"    case {n}: stack.push(tbl[{n}]); break;"
        for n in range(10)) + "\n"
    "    default: break;\n"
    "  }\n"
    "}\n"
)

# {F2,F3} pair: dispatch loop with a real case table, but the array is
# below the F1 threshold (50 < 100 items). Three-of-two must still suspect.
PAIR_F2_F3 = (
    "var small = [" + ",".join(str(i % 7) for i in range(50)) + "];\n"
    "var pc = 0, stack = [];\n"
    "while (true) {\n"
    "  switch (small[pc++]) {\n"
    + "\n".join(
        f"    case {n}: stack.push(small[pc++]); break;"
        for n in range(12)) + "\n"
    "    default: break;\n"
    "  }\n"
    "}\n"
)

# Hollow-F3 tripwire (#884): a big consumed integer array with no dispatch
# and no case table. The semantic ratio reads 1.0 by ABSENCE -- has_cases
# must anchor F3 so that absence cannot vote, keeping this at one feature.
BIG_ARRAY_ONLY = (
    "var data = [" + ",".join(str(i % 101) for i in range(400)) + "];\n"
    "function render(items) {\n"
    "  var out = [];\n"
    "  for (var i = 0; i < items.length; i++) {\n"
    "    out.push(document.createElement('div'));\n"
    "  }\n"
    "  return out;\n"
    "}\n"
)

# F2-only lane: a real dispatch table whose case bodies are all business/
# env semantics -> F3 collapses, single feature stays "low".
SEMANTIC_DISPATCH = (
    "var cfg = [" + ",".join(str(i % 5) for i in range(40)) + "];\n"
    "while (true) {\n"
    "  switch (state) {\n"
    + "\n".join(
        f"    case {n}: fetch('/api/{n}'); localStorage.setItem('k{n}','v');"
        " break;"
        for n in range(12)) + "\n"
    "    default: break;\n"
    "  }\n"
    "}\n"
)


def _run(target: Path) -> dict:
    r = subprocess.run([sys.executable, str(SCRIPT), str(target), "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_positive_synthetic_vmp(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "vmp.js", POSITIVE))
    assert v["vmp_suspected"] is True
    assert v["votes"] == 3
    assert v["confidence"] == "high"
    assert v["features"]["f2_dispatch_loop"]["cases"] >= 8
    assert any(a["kind"] == "numeric" and a["items"] >= 100
               for a in v["features"]["f1_bytecode_array"])
    assert v["features"]["f3_semanticless_handlers"]["case_bodies_found"]


def test_f1_f3_pair_suspected_medium(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "pair_f1_f3.js", PAIR_F1_F3))
    f = v["features"]
    assert f["f1_bytecode_array"], "F1 fixture broken: no big array"
    assert f["f2_dispatch_loop"] is None, "F2 fixture broken: loop head hit"
    assert f["f3_semanticless_handlers"]["case_bodies_found"]
    assert v["vmp_suspected"] is True
    assert v["votes"] == 2
    assert v["confidence"] == "medium"


def test_f2_f3_pair_suspected_medium(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "pair_f2_f3.js", PAIR_F2_F3))
    f = v["features"]
    assert not f["f1_bytecode_array"], "F1 fixture broken: array over threshold"
    assert f["f2_dispatch_loop"] is not None, "F2 fixture broken: no dispatch"
    assert f["f3_semanticless_handlers"]["case_bodies_found"]
    assert v["vmp_suspected"] is True
    assert v["votes"] == 2
    assert v["confidence"] == "medium"


def test_big_array_alone_not_suspected(tmp_path: Path) -> None:
    """Hollow-F3 regression tripwire (#884): absence must not vote."""
    v = _run(_write(tmp_path, "array_only.js", BIG_ARRAY_ONLY))
    f = v["features"]
    assert f["f1_bytecode_array"], "F1 fixture broken: no big array"
    assert f["f2_dispatch_loop"] is None
    assert f["f3_semanticless_handlers"]["case_bodies_found"] is False
    assert v["vmp_suspected"] is False
    assert v["votes"] == 1
    assert v["confidence"] == "low"


def test_semantic_dispatch_stays_low(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "sem_disp.js", SEMANTIC_DISPATCH))
    f = v["features"]
    assert not f["f1_bytecode_array"]
    assert f["f2_dispatch_loop"] is not None
    assert f["f3_semanticless_handlers"]["ratio"] < 0.9
    assert v["vmp_suspected"] is False
    assert v["votes"] == 1
    assert v["confidence"] == "low"


def test_negative_readable_flattening(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "flat.js", NEGATIVE_FLATTENING))
    # readable business calls + tiny case table: no feature may stack into
    # a suspicion under the three-of-two verdict.
    assert v["vmp_suspected"] is False
    assert v["votes"] < 2
    assert not v["features"]["f1_bytecode_array"]


def test_cli_json_contract(tmp_path: Path) -> None:
    v = _run(_write(tmp_path, "v.js", POSITIVE))
    assert {"source", "vmp_suspected", "confidence", "votes",
            "features", "signals", "note"} <= set(v)
    assert "trace methodology" in v["note"]
