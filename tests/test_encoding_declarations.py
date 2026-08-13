"""Encoding declaration contract (#224): every .py file that contains
non-ASCII characters MUST declare a PEP 263 coding header.

Root cause: the Stop hook executed hooks/completion_gate.py with a bare
`python` (Python 2.7 on this machine). Python 2 parses source as ASCII
unless a coding declaration exists — the em-dash (U+2014) in the module
docstring raised SyntaxError and killed the hook.

Contract: for every .py under scripts/ hooks/ tests/ (plus the
research replay script), if the file bytes contain any non-ASCII
character, the first two lines must carry a `coding` declaration.
Pure-ASCII files are exempt (no header needed).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["scripts", "hooks", "tests"]


def _py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        files.extend(sorted((ROOT / d).glob("*.py")))
    return files


def _has_non_ascii(data: bytes) -> bool:
    return any(b > 0x7F for b in data)


def test_non_ascii_py_files_have_coding_declaration():
    """Every .py containing non-ASCII bytes must declare a coding header
    in its first two lines (PEP 263)."""
    violators = []
    for p in _py_files():
        data = p.read_bytes()
        if not _has_non_ascii(data):
            continue  # pure ASCII — exempt
        head_lines = data.splitlines()[:2]
        declared = any(b"coding" in ln for ln in head_lines)
        if not declared:
            violators.append(str(p.relative_to(ROOT)))
    assert not violators, (
        f"{len(violators)} file(s) contain non-ASCII but no coding "
        f"declaration: {violators}"
    )
