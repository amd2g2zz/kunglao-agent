# -*- coding: utf-8 -*-
"""Contract tests for the silent-swallow ratchet gate (issue 275).

Fixtures are built in tmp trees. The offending handler shapes live only
in string literals, never as real try/except constructs in this file, so
the gate's self-scan stays clean and this module carries zero silent
handlers of its own.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import silent_except_lint as sel  # noqa: E402


# --------------------------------------------------------------- fixtures
# Payload sources: each is a full module whose handler shapes are known
# by construction. String literals here are inert for the AST scan.

_TRY = "try:\n    value = compute()\n"

_SILENT_PASS = _TRY + "except OSError:\n    pass\n"
_SILENT_ELLIPSIS = _TRY + "except OSError:\n    ...\n"
_SILENT_DOCSTRING_BODY = _TRY + "except OSError:\n    'no-op'\n"
_EMIT_BODY = _TRY + "except OSError:\n    emit(ws, action='degraded')\n"
_WARN_BODY = _TRY + "except OSError:\n    log.warning('degraded')\n"
_BARE_RAISE = _TRY + "except OSError:\n    raise\n"
_RERAISE_NEW = _TRY + "except OSError as exc:\n    raise RuntimeError(str(exc)) from exc\n"
_COMMENTED_SILENCE = _TRY + "except OSError:  # fail-open: side channel stays quiet\n    pass\n"
_CONTINUE_BODY = _TRY + "except OSError:\n    continue\n"
_ASSIGN_DEFAULT = _TRY + "except OSError:\n    value = None\n"
_RETURN_DEFAULT = _TRY + "except OSError:\n    return []\n"
_CLEAN = "value = compute()\n"

# Inner silent handler nested under an outer try whose handler body is a
# traced no-op-free call: only the inner handler is silent.
_NESTED = (
    "try:\n"
    "    try:\n"
    "        value = compute()\n"
    "    except OSError:\n"
    "        pass\n"
    "except Exception:\n"
    "    emit(ws, action='outer')\n"
)

_TRYSTAR = (
    "try:\n"
    "    value = compute()\n"
    "except* OSError:\n"
    "    pass\n"
)

_SYNTAX_ERR = "def broken(:\n"
_UNREADABLE = "value = compute()\n"  # written as raw bytes with bad encoding below


def _proj(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    for rel, src in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, bytes):
            target.write_bytes(src)
        else:
            target.write_text(src, encoding="utf-8")
    return tmp_path


def _baseline(tmp_path: Path, entries: dict) -> Path:
    path = tmp_path / "scripts" / "silent_except_baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": sel.BASELINE_SCHEMA, "files": entries}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str) -> int:
    return sel.main(["--root", str(tmp_path), *extra])


def _kinds(tmp_path: Path, *extra: str) -> list[str]:
    payload = sel.build_report(["--root", str(tmp_path), "--json", *extra])
    return [v["kind"] for v in payload["violations"]]


# ------------------------------------------------- detector: silent shapes

def test_silent_pass_is_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_silent_ellipsis_is_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_ELLIPSIS})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_silent_constant_expr_body_is_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_DOCSTRING_BODY})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_emit_body_is_not_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _EMIT_BODY})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_warn_body_is_not_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _WARN_BODY})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_bare_raise_is_not_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _BARE_RAISE})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_reraise_is_not_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _RERAISE_NEW})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_comment_documented_silence_is_still_counted(tmp_path: Path):
    """Pinned ruling: a comment records intent, it is not a runtime trace.

    The issue's own evidence counts comment-annotated pass sites
    (convergence_check.py is its worst file precisely because of them),
    so the calibrated rule does not exempt them.
    """
    _proj(tmp_path, {"scripts/mod.py": _COMMENTED_SILENCE})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_continue_body_is_out_of_scope(tmp_path: Path):
    """The ledger freezes the issue's `except: pass` surface only."""
    _proj(tmp_path, {"scripts/mod.py": _CONTINUE_BODY})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_assign_default_body_is_out_of_scope(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _ASSIGN_DEFAULT})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_return_default_body_is_out_of_scope(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _RETURN_DEFAULT})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 0


def test_only_inner_nested_handler_is_counted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _NESTED})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_each_handler_in_one_try_counts_separately(tmp_path: Path):
    src = (_TRY + "except OSError:\n    pass\n"
           + "except ValueError:\n    pass\n")
    _proj(tmp_path, {"scripts/mod.py": src})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 2


@pytest.mark.skipif(sys.version_info < (3, 11),
                    reason="except* requires ast.TryStar (3.11+)")
def test_trystar_handlers_are_scanned(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _TRYSTAR})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == 1


def test_hooks_root_is_scanned(tmp_path: Path):
    _proj(tmp_path, {"hooks/mod.py": _SILENT_PASS, "scripts/other.py": _CLEAN})
    counts, _ = sel.scan_counts(tmp_path)
    assert counts == {"hooks/mod.py": 1, "scripts/other.py": 0}


# -------------------------------------------------- structural fail-closed

def test_syntax_error_fails_closed(tmp_path: Path):
    _proj(tmp_path, {"scripts/bad.py": _SYNTAX_ERR})
    kinds = _kinds(tmp_path)
    assert "syntax" in kinds
    assert _run(tmp_path) == 1


def test_unreadable_file_fails_closed(tmp_path: Path):
    _proj(tmp_path, {"scripts/bad.py": b"\xff\xfe\x81\x81"})
    kinds = _kinds(tmp_path)
    assert "unreadable" in kinds
    assert _run(tmp_path) == 1


def test_clean_tree_passes_without_baseline(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    assert _run(tmp_path) == 0


# ------------------------------------------------------- baseline ratchet

def test_exact_baseline_passes(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    _baseline(tmp_path, {"scripts/mod.py": 1})
    assert _run(tmp_path) == 0


def test_increase_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    _baseline(tmp_path, {"scripts/mod.py": 1})
    second = _TRY + "except ValueError:\n    pass\n"
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS + second})
    kinds = _kinds(tmp_path)
    assert kinds == ["increase"]
    assert _run(tmp_path) == 1


def test_cleared_entry_must_be_deleted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    _baseline(tmp_path, {"scripts/mod.py": 2})
    assert "cleared-entry" in _kinds(tmp_path)
    assert _run(tmp_path) == 1


def test_loose_entry_must_be_tightened(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    _baseline(tmp_path, {"scripts/mod.py": 3})
    assert "loose-entry" in _kinds(tmp_path)
    assert _run(tmp_path) == 1


def test_stale_entry_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    _baseline(tmp_path, {"scripts/gone.py": 1})
    assert "stale-entry" in _kinds(tmp_path)
    assert _run(tmp_path) == 1


def test_new_debt_without_entry_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    _baseline(tmp_path, {"scripts/other.py": 1})
    assert "unbaselined" in _kinds(tmp_path)
    assert _run(tmp_path) == 1


def test_missing_baseline_with_debt_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    assert "no-baseline" in _kinds(tmp_path)
    assert _run(tmp_path) == 1


def test_partial_ratchet_two_files(tmp_path: Path):
    """One file shrinks, one grows: exactly the growth is flagged."""
    a_src = _SILENT_PASS
    b_src = _SILENT_PASS + _TRY + "except ValueError:\n    pass\n"
    _proj(tmp_path, {"scripts/a.py": a_src, "scripts/b.py": b_src})
    _baseline(tmp_path, {"scripts/a.py": 2, "scripts/b.py": 1})
    kinds = _kinds(tmp_path)
    assert sorted(kinds) == ["increase", "loose-entry"]
    payload = sel.build_report(["--root", str(tmp_path), "--json"])
    increase = [v for v in payload["violations"] if v["kind"] == "increase"]
    assert increase[0]["file"] == "scripts/b.py"


# ------------------------------------------------------------ CLI contract

def test_emit_baseline_is_deterministic_and_minimal(tmp_path: Path):
    _proj(tmp_path, {"scripts/a.py": _SILENT_PASS, "scripts/b.py": _CLEAN})
    out = tmp_path / "scripts" / "silent_except_baseline.yaml"
    assert sel.main(["--root", str(tmp_path), "--emit-baseline"]) == 0
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["schema"] == sel.BASELINE_SCHEMA
    assert doc["files"] == {"scripts/a.py": 1}
    # deterministic: a second emit is byte-identical
    first = out.read_text(encoding="utf-8")
    sel.main(["--root", str(tmp_path), "--emit-baseline"])
    assert out.read_text(encoding="utf-8") == first


def test_emit_baseline_refuses_syntax_errors(tmp_path: Path):
    _proj(tmp_path, {"scripts/bad.py": _SYNTAX_ERR})
    out = tmp_path / "scripts" / "silent_except_baseline.yaml"
    assert sel.main(["--root", str(tmp_path), "--emit-baseline"]) == 1
    assert not out.exists()


def test_json_payload_shape(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    payload = sel.build_report(["--root", str(tmp_path), "--json"])
    assert set(payload) == {"violations", "exit", "summary"}
    assert payload["exit"] == 1
    assert isinstance(payload["summary"], str)


def test_baseline_path_override(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _SILENT_PASS})
    ledger = tmp_path / "custom_ledger.yaml"
    ledger.write_text(
        yaml.safe_dump({"schema": sel.BASELINE_SCHEMA,
                        "files": {"scripts/mod.py": 1}}, sort_keys=False),
        encoding="utf-8")
    assert sel.main(["--root", str(tmp_path), "--baseline", str(ledger)]) == 0


def test_exit_codes_via_subprocess(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    argv = [sys.executable, str(SCRIPTS / "silent_except_lint.py"),
            "--root", str(tmp_path)]
    clean = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert clean.returncode == 0
    (tmp_path / "scripts" / "mod.py").write_text(_SILENT_PASS, encoding="utf-8")
    dirty = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert dirty.returncode == 1


# ---------------------------------------------------------------- tree gate

def test_real_tree_gate_is_green():
    """The committed baseline ratchets the live tree to a zero exit."""
    assert sel.main([]) == 0
