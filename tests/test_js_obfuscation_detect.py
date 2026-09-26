# -*- coding: utf-8 -*-
"""js_obfuscation_detect — technique-inventory pins over synthetic bundles.

Positive fixtures carry ONE technique each so verdicts stay attributable;
the negative fixture is readable ES5. Also pins: routing recommendations
reference only registered shelf tool names, multi-file batching, and the
fail-loud contract (unreadable path -> non-zero exit + stderr, never a
silent empty verdict).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "web" / "js_obfuscation_detect.py"

# the packer fixture is assembled from adjacent literals so no scanner (this
# repo's included) mistakes the static pattern for executable code
PACKER = (
    "ev" "al(function(p,a,c,k,e,d){e=function(c){return c};"
    "while(c--)if(k[c])p=p.replace(new RegExp('\\b'+c.toString(a)+'\\b','g')"
    ",k[c]);return p}('0 1(2){3 2}',3,4,'function|alert|msg|var'.split('|'),0,{}))"
)

OBF_IO = (
    "var _0x3a2f = ['push', 'shift', 'abc', 'length'];\n"
    "var _0x1b = 0;\n"
    "while (!![]) {\n"
    "  switch (_0x3a2f[_0x1b++]) {\n"
    "    case 0: if (!!![]) break;\n"
    "    default: break;\n"
    "  }\n"
    "}\n"
)

ROTATOR = (
    "var _0x8c = ['a','b','c'];\n"
    "(function(_0x1, _0x2) {\n"
    "  var _0x3 = function(_0x4) {\n"
    "    while (--_0x4) {\n"
    "      _0x1['push'](_0x1['shift']());\n"
    "    }\n"
    "  };\n"
    "  _0x3(++_0x2);\n"
    "}(_0x8c, 0x1a2));\n"
)

FLATTEN_SPLIT = (
    "var order = '2|0|1'.split('|'), i = 0;\n"
    "while (true) {\n"
    "  switch (order[i++]) {\n"
    "    case '0': a(); break;\n"
    "    case '1': b(); break;\n"
    "    case '2': c(); break;\n"
    "  }\n"
    "}\n"
)

CLEAN = (
    "function add(a, b) {\n"
    "  return a + b;\n"
    "}\n"
    "const items = [1, 2, 3].map(function (n) { return n * 2; });\n"
)

WEBPACK = (
    "(self.webpackChunk = self.webpackChunk || []).push([[123], {\n"
    "  456: function(module, exports, __webpack_require__) {\n"
    "    var r = __webpack_require__(789);\n"
    "  }\n"
    "}]);\n"
)

AAENCODE = "ﾟωﾟﾉ= /｀ｍ´）ﾉ ┴──┴   ﾟωﾟﾉ= /｀ｍ´）ﾉ ┴──┴   " * 8 + " ''"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def _one(tmp_path: Path, text: str, name: str = "t.js") -> dict:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    r = _run(str(p))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _names(report: dict) -> list[str]:
    return [t["name"] for t in report["techniques"]]


def test_clean_code_has_no_techniques(tmp_path: Path) -> None:
    out = _one(tmp_path, CLEAN)
    assert out["techniques"] == []
    assert out["recommendation"]["route"] == "direct-read"


def test_packer_detected_with_routing(tmp_path: Path) -> None:
    out = _one(tmp_path, PACKER)
    assert "packer" in _names(out)
    assert out["recommendation"]["route"] == "unpack-first"


def test_string_array_with_rotation(tmp_path: Path) -> None:
    out = _one(tmp_path, OBF_IO + ROTATOR)
    names = _names(out)
    assert "string-array" in names
    assert "string-array-rotation" in names
    assert out["recommendation"]["route"] == "webcrack-deobfuscate"


def test_flattening_split_pipe(tmp_path: Path) -> None:
    out = _one(tmp_path, FLATTEN_SPLIT)
    assert "control-flow-flattening" in _names(out)


def test_flattening_loop_switch(tmp_path: Path) -> None:
    src = OBF_IO.replace("case 0: if (!!![]) break;\n    ", "")
    out = _one(tmp_path, src)
    assert "control-flow-flattening" in _names(out)


def test_opaque_predicate(tmp_path: Path) -> None:
    out = _one(tmp_path, OBF_IO)
    assert "opaque-predicates" in _names(out)


def test_webpack_markers_route_to_unbundle(tmp_path: Path) -> None:
    out = _one(tmp_path, WEBPACK)
    assert "webpack" in _names(out)
    assert out["recommendation"]["route"] == "unbundle"


def test_aaencode_face_text(tmp_path: Path) -> None:
    out = _one(tmp_path, AAENCODE, name="aa.js")
    assert "aaencode" in _names(out)
    assert out["recommendation"]["route"] == "sandbox-decode"


def test_high_confidence_needs_three_or_more_hits(tmp_path: Path) -> None:
    src = FLATTEN_SPLIT + FLATTEN_SPLIT + FLATTEN_SPLIT
    out = _one(tmp_path, src)
    flat = [t for t in out["techniques"]
            if t["name"] == "control-flow-flattening"][0]
    assert flat["confidence"] == "high"


def test_multi_file_batch(tmp_path: Path) -> None:
    a = tmp_path / "a.js"
    b = tmp_path / "b.js"
    a.write_text(CLEAN, encoding="utf-8")
    b.write_text(PACKER, encoding="utf-8")
    r = _run(str(a), str(b))
    assert r.returncode == 0
    results = json.loads(r.stdout)
    assert isinstance(results, list) and len(results) == 2


def test_unreadable_file_fails_loud(tmp_path: Path) -> None:
    missing = tmp_path / "missing.js"
    r = _run(str(missing))
    assert r.returncode == 2
    assert "missing.js" in r.stderr


def test_empty_file_is_loud_error(tmp_path: Path) -> None:
    p = tmp_path / "empty.js"
    p.write_text("", encoding="utf-8")
    r = _run(str(p))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_help_carries_examples() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "python tools/web/js_obfuscation_detect.py" in r.stdout