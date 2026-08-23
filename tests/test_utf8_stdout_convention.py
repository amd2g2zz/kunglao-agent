# -*- coding: utf-8 -*-
"""UTF-8 stdout convention contract (#317, #314 A1): every tools/ CLI must
reconfigure sys.stdout to UTF-8 under a try/except guard.

Background: three independent tool batches (1b: tools/static, 1c:
_common.py + die_probe, 2b: qiling-tool) each hit the same defect — tool
output carrying U+FFFD (the decode(errors="replace") artifact) or any other
non-ASCII crashes a GBK console (Windows) with a bare UnicodeEncodeError
traceback + exit 1, breaking the "structured error, never a traceback" CLI
contract. Each batch fixed it ad hoc; nothing stopped the next batch from
regressing. This test is the mechanical enforcement: delete any tool's
reconfigure block and this file goes red.

User decision (2026-08-14): unify stdout on UTF-8, NOT an errors="replace"
patch — the contract therefore demands the full
``sys.stdout.reconfigure(encoding="utf-8", errors="replace")`` form inside
``try/except (AttributeError, ValueError)`` (the canonical guard from
tools/static/c_normalize.py).

CLI definition: a .py under tools/ that runs as an entry point (contains an
``if __name__ == "__main__"`` block). Pure helper modules (static/common.py,
_lib/lib_disasm.py, crypto/algorithms.py, __init__.py — imported by CLIs
and covered transitively) have no __main__ and are exempt automatically.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# Exemptions with a reason each — remove the exemption once the reason lapses:
EXEMPT_CLIS: dict[str, str] = {
    # tool-search.py's former exemption (test helper decoded with the
    # locale) lapsed in #476: the helper now decodes UTF-8 and the CLI
    # carries the canonical guard. Kept here as the pattern for future
    # exemptions: name the file, name the coupled fix, remove when done.
}


def _cli_files() -> list[tuple[str, str]]:
    """(relpath, source) for every tools/ .py entry point, exempting helpers
    (no __main__ block) and the documented EXEMPT_CLIS."""
    out = []
    for p in sorted(TOOLS.rglob("*.py")):
        rel = p.relative_to(TOOLS).as_posix()
        src = p.read_text(encoding="utf-8")
        if '"__main__"' not in src:
            continue  # helper module — covered transitively by its importers
        if rel in EXEMPT_CLIS:
            continue
        out.append((rel, src))
    return out


def _guard_status(src: str) -> str:
    """Return "ok", or a human-readable reason the UTF-8 guard is missing.

    Contract: a call ``sys.stdout.reconfigure(encoding="utf-8",
    errors="replace")`` inside a try block whose handlers catch both
    AttributeError and ValueError (the canonical #317 guard shape).
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        call = None
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "reconfigure"
                        and isinstance(sub.func.value, ast.Attribute)
                        and sub.func.value.attr == "stdout"
                        and isinstance(sub.func.value.value, ast.Name)
                        and sub.func.value.value.id == "sys"):
                    call = sub
                    break
            if call is not None:
                break
        if call is None:
            continue
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        enc = kwargs.get("encoding")
        errs = kwargs.get("errors")
        if not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
            return (f"reconfigure present but encoding="
                    f"{ast.unparse(enc) if enc is not None else None!r}")
        if not (isinstance(errs, ast.Constant) and errs.value == "replace"):
            return (f"reconfigure present but errors="
                    f"{ast.unparse(errs) if errs is not None else None!r}")
        caught: set[str] = set()
        for handler in node.handlers:
            if handler.type is None:
                caught.add("bare-except")
            elif isinstance(handler.type, ast.Tuple):
                caught.update(e.id for e in handler.type.elts
                              if isinstance(e, ast.Name))
            elif isinstance(handler.type, ast.Name):
                caught.add(handler.type.id)
        if not ({"AttributeError", "ValueError"} <= caught):
            return f"guard present but try/except catches {sorted(caught)}"
        return "ok"
    return ('missing sys.stdout.reconfigure(encoding="utf-8", '
            'errors="replace") try/except guard')


def test_every_tools_cli_has_utf8_stdout_guard():
    """Every tools/ CLI carries the canonical UTF-8 stdout guard."""
    violators = []
    for rel, src in _cli_files():
        status = _guard_status(src)
        if status != "ok":
            violators.append(f"{rel}: {status}")
    assert not violators, (
        f"{len(violators)} tools/ CLI(s) violate the UTF-8 stdout contract "
        f"(#317):\n" + "\n".join(f"  {v}" for v in violators) +
        "\nAdd: try: sys.stdout.reconfigure(encoding=\"utf-8\", "
        "errors=\"replace\") / except (AttributeError, ValueError): pass")


def test_non_ascii_output_survives_non_utf8_locale(tmp_path):
    """Behavioral proof (#314 A1): non-ASCII output must not crash a CLI
    under a non-UTF-8 stdio encoding.

    PYTHONIOENCODING=ascii + strict errors reproduces the GBK-console crash
    without a real GBK terminal: without any reconfigure guard, printing the
    CJK comment raises UnicodeEncodeError (traceback, exit != 0); with the
    guard — the CLI's own, or the transitively imported tools/static/common.py
    one — stdout is UTF-8 and the run exits 0. This tests the observable
    contract end-to-end; per-file guard presence is the scan test above.
    """
    src = tmp_path / "sample.c"
    src.write_text(
        "int f(int x) { x = x - (x/4)*4; return x; } /* 中文注释 */\n",
        encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"}
    r = subprocess.run(
        [sys.executable, str(TOOLS / "static" / "c_normalize.py"),
         "--in", str(src)],
        env=env, capture_output=True, timeout=60)
    assert r.returncode == 0, (
        f"non-ASCII output crashed under PYTHONIOENCODING=ascii: "
        f"exit {r.returncode}\nstderr={r.stderr!r}")
    out = r.stdout.decode("utf-8", errors="replace")
    assert "中文注释" in out, "UTF-8 stdout lost the non-ASCII text"
    assert "x % 4" in out, "normalization did not run (bad fixture)"
