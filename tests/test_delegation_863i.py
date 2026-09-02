# -*- coding: utf-8 -*-
"""tests/test_delegation_863i.py — #863 Family I/J/K enforcement tests.

Family I: the six tools/static `_error` copies converge on `common.error`.
The historical return-vs-sys.exit contract fork is fixed EXPLICITLY on the
sys.exit (NoReturn) contract: the yara return-value shape (`return
_error(msg)` feeding `sys.exit(main())`) is absorbed — call sites call
`error(msg)` and SystemExit(2) propagates through main() with byte-identical
stderr JSON and exit code.

Family J: the four `_write_evidence` copies converge on
`common.write_evidence(workspace, name, data)` (dexdc's 3-arg signature).
The scripts-side consumer (apkid_scanner) loads common through the #891
`_hooks_path.load_module_by_path` authority under the unique name
`tools_static_common` — no tools/static sys.path insert, no shadow risk.

Family K: the 19 tolerant-JSONL loop sites in 18 scripts converge on
`scripts/kunglao_log.iter_jsonl`. Per-file delegation asserts plus residual
`json.loads` / `json.JSONDecodeError` count pins make any loop
re-introduction a review event. Deliberate non-conversions (out-of-family
shapes): kunglao_upgrade's tolerant REWRITE loop and bench_analyze's strict
list-comp.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"
SCRIPTS = ROOT / "scripts"
for _sub in ("scripts", "hooks", "tools", "tools/static", "tools/_lib"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))

import common  # noqa: E402 — tools/static/common.py, the Family I/J single source

# ---------------------------------------------------------------- Family I --

I_SHAPE_A = ("disasm_dump", "overlay_scan", "pe_analyze", "shellcode_scan")
I_ALL_FILES = tuple(STATIC / f"{name}.py" for name in I_SHAPE_A) + (
    STATIC / "yara-gen.py",
    STATIC / "yara-scan.py",
)


@pytest.mark.parametrize("path", I_ALL_FILES, ids=lambda p: p.name)
def test_family_i_error_copies_removed(path: Path):
    """No local `_error` def or call survives in any of the six tools."""
    src = path.read_text(encoding="utf-8")
    assert "def _error" not in src, f"{path.name}: local _error def survives"
    assert "_error(" not in src, f"{path.name}: local _error call survives"


def test_family_i_error_is_common_error_identity():
    """Shape-A modules bind the ONE common.error object (delegation)."""
    import disasm_dump  # noqa: PLC0415
    import overlay_scan  # noqa: PLC0415
    import pe_analyze  # noqa: PLC0415
    import shellcode_scan  # noqa: PLC0415

    for mod in (disasm_dump, overlay_scan, pe_analyze, shellcode_scan):
        assert mod.error is common.error, mod.__name__


def test_family_i_yara_binds_common_error_identity():
    """yara-gen / yara-scan (dash names) bind the same common.error object."""
    from _path_hygiene import load_module_by_path  # noqa: PLC0415

    yara_gen = load_module_by_path("yara_gen_863i", STATIC / "yara-gen.py")
    yara_scan = load_module_by_path("yara_scan_863i", STATIC / "yara-scan.py")
    assert yara_gen.error is common.error
    assert yara_scan.error is common.error


def test_yara_gen_error_path_raises_system_exit_2(capsys):
    """Contract-fork fix pinned: main() error path raises SystemExit(2) with
    the same structured stderr JSON the return-shape used to produce."""
    from _path_hygiene import load_module_by_path  # noqa: PLC0415

    yara_gen = load_module_by_path("yara_gen_863i", STATIC / "yara-gen.py")
    with pytest.raises(SystemExit) as excinfo:
        yara_gen.main(["--hex", "41 41 41 41", "--name", "bad name"])
    assert excinfo.value.code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["exit_code"] == 2
    assert "not a valid rule identifier" in err["error"]


def test_yara_scan_error_path_raises_system_exit_2(capsys):
    from _path_hygiene import load_module_by_path  # noqa: PLC0415

    yara_scan = load_module_by_path("yara_scan_863i", STATIC / "yara-scan.py")
    with pytest.raises(SystemExit) as excinfo:
        yara_scan.main(["--binary", str(ROOT / "no-such-binary-863i.bin")])
    assert excinfo.value.code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["exit_code"] == 2
    assert "cannot read --binary" in err["error"]


# ---------------------------------------------------------------- Family J --

def test_common_write_evidence_contract(tmp_path):
    """The single source keeps the observed write contract: evidence/<name>,
    UTF-8, indent=2, ensure_ascii=False, parents created, path returned."""
    ws = tmp_path / "ws"
    out = common.write_evidence(ws, "probe.json", {"a": 1, "b": "文本"})
    assert out == ws / "evidence" / "probe.json"
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == {"a": 1, "b": "文本"}
    assert '  "a": 1' in text, "indent=2 contract"
    assert "文本" in text, "ensure_ascii=False contract"
    out2 = common.write_evidence(ws, "probe.json", {"a": 2})
    assert out2 == out
    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 2}


@pytest.mark.parametrize(
    "path",
    (
        STATIC / "apk_mem_gate.py",
        STATIC / "baksmali_index.py",
        STATIC / "dexdc_scanner.py",
        SCRIPTS / "apkid_scanner.py",
    ),
    ids=lambda p: p.name,
)
def test_family_j_copies_removed(path: Path):
    src = path.read_text(encoding="utf-8")
    assert "def _write_evidence" not in src, f"{path.name}: local def survives"
    assert "_write_evidence" not in src, f"{path.name}: local call survives"


def test_family_j_delegates_identity():
    """All four consumers bind the ONE common.write_evidence object."""
    import apk_mem_gate  # noqa: PLC0415
    import baksmali_index  # noqa: PLC0415
    import dexdc_scanner  # noqa: PLC0415

    for mod in (apk_mem_gate, baksmali_index, dexdc_scanner):
        assert mod.write_evidence is common.write_evidence, mod.__name__

    import apkid_scanner  # noqa: PLC0415
    from _hooks_path import load_module_by_path  # noqa: PLC0415

    bridge_common = load_module_by_path(
        "tools_static_common", STATIC / "common.py")
    assert apkid_scanner.write_evidence is bridge_common.write_evidence


# ---------------------------------------------------------------- Family K --

from kunglao_log import iter_jsonl  # noqa: E402 — the Family K single source


def test_iter_jsonl_skips_blank_and_unparseable_lines():
    lines = ['{"a": 1}', "", "   ", "not json", '{"a": 2}', "{broken"]
    assert list(iter_jsonl(lines)) == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_null_line_yields_none():
    """A literal `null` line parses and flows through — consumers keep their
    own dict checks (byte-equivalence with the historical loops)."""
    assert list(iter_jsonl(["null", '{"a": 1}'])) == [None, {"a": 1}]


def test_iter_jsonl_accepts_any_iterable_order():
    rows = list(iter_jsonl(reversed(['{"n": 1}', "junk", '{"n": 2}'])))
    assert rows == [{"n": 2}, {"n": 1}]
    gen = iter_jsonl(line for line in ['{"x": 0}', "bad", '{"x": 1}'])
    assert next(gen) == {"x": 0}
    assert next(gen) == {"x": 1}
    with pytest.raises(StopIteration):
        next(gen)


K_ZERO_FILES = (
    "bench_tokens",
    "convergence_health",
    "event_taxonomy",
    "outcome_capture",
    "recall_metrics",
    "cost_gate",
    "kunglao_status",
    "priority_ratio",
    "lib_kunglao",
    "ask_for_direction_gate",
)

# file -> (json.loads count, json.JSONDecodeError count) after conversion —
# the loop sites are gone; the residuals are non-jsonl-loop parses
# (state/heartbeat file reads, detail-field parses, CLI --event parsing).
# kunglao_log counts include the iter_jsonl util body itself (json.loads in
# the generator + one docstring mention) and its own state-file read.
K_RESIDUAL_PINS = {
    "rho_verifier": (1, 1),
    "kunglao_log": (3, 1),
    "kunglao_record": (1, 1),
    "kunglao_resume": (2, 0),
    "heartbeat": (4, 3),
    "infeasible_signal": (2, 2),
    "mechanism_scheduler": (3, 0),
    "external_kicker": (2, 0),
}


@pytest.mark.parametrize(
    "name", tuple(set(K_RESIDUAL_PINS) - {"kunglao_log"}))
def test_family_k_files_delegate_to_iter_jsonl(name: str):
    src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
    assert "from kunglao_log import iter_jsonl" in src, (
        f"{name}: iter_jsonl delegation import missing")


@pytest.mark.parametrize("name", K_ZERO_FILES)
def test_family_k_zero_files_fully_delegated(name: str):
    src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
    assert src.count("json.loads") == 0, name
    assert src.count("json.JSONDecodeError") == 0, name


@pytest.mark.parametrize(
    "name,expected", sorted(K_RESIDUAL_PINS.items()))
def test_family_k_residual_parse_counts_pinned(name: str, expected: tuple):
    src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
    actual = (src.count("json.loads"), src.count("json.JSONDecodeError"))
    assert actual == expected, f"{name}: residual parse-count drift"
