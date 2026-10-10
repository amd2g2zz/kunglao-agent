# -*- coding: utf-8 -*-
"""tests/test_gate4_baseline_663.py — Gate 4 is evidence-based.

Gate 4 used to PASS on `find_spec('mutmut')` alone (tool availability =
effectiveness — the vacuous pass this change closes). It now reads the
committed mutation baseline (devkit/mutation-baseline.json, schema
mutation-baseline/1) and fails on: missing artifact, bad schema, zero
totals, partial runs (not_checked > 0), scores below the 0.7 floor,
stale recorded_at, or a base_commit that is not an ancestor of HEAD.

Also pins the recorder's sidecar parsing (devkit/mutation_baseline.py):
mutmut exit codes map through mutmut's own status table, and an
unparseable sidecar is an ERROR, never a fabricated zero.

quality_gates / mutation_baseline are loaded BY PATH (devkit is not a
package; the repo's by-path convention) so this suite never imports
half the worth of scripts/ onto sys.path."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


QG = _load("quality_gates_663_by_path", "devkit/quality_gates.py")
MB = _load("mutation_baseline_663_by_path", "devkit/mutation_baseline.py")


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True
                          ).stdout.strip()


def _doc(**over) -> dict:
    base = {
        "schema": "mutation-baseline/1",
        "tool": "mutmut",
        "tool_version": "3.7.0",
        "recorded_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "base_commit": _head(),
        "scope": {"source_paths": ["scripts"],
                  "only_mutate": ["scripts/slot_monitor.py"],
                  "test_selection": ["tests/test_slot_monitor_636.py"]},
        "totals": {"killed": 8, "survived": 2, "timeout": 0,
                   "suspicious": 0, "skipped": 0, "no_tests": 0,
                   "type_check_error": 0, "interrupted": 0,
                   "not_checked": 0, "total": 10},
        "score": 0.8,
    }
    base.update(over)
    return base


def _write(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "mutation-baseline.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _gate(path: Path) -> bool:
    return QG._gate4_test_effectiveness(verbose=False, baseline_path=path)


# ------------------------------------------------ gate branches

def test_missing_artifact_fails(tmp_path) -> None:
    assert _gate(tmp_path / "nope.json") is False


def test_valid_fresh_artifact_passes(tmp_path) -> None:
    assert _gate(_write(tmp_path, _doc())) is True


def test_wrong_schema_fails(tmp_path) -> None:
    assert _gate(_write(tmp_path, _doc(schema="mutation-baseline/0"))) is False


def test_zero_totals_fail(tmp_path) -> None:
    doc = _doc()
    doc["totals"] = {**doc["totals"], "total": 0, "killed": 0}
    assert _gate(_write(tmp_path, doc)) is False


def test_partial_run_fails(tmp_path) -> None:
    """not_checked > 0 = an unfinished run — never evidence."""
    doc = _doc()
    doc["totals"] = {**doc["totals"], "not_checked": 1, "total": 11}
    assert _gate(_write(tmp_path, doc)) is False


def test_below_floor_score_fails(tmp_path) -> None:
    """A recorded score under the 0.7 floor is not effective evidence."""
    doc = _doc(score=0.6)
    assert _gate(_write(tmp_path, doc)) is False


def test_missing_score_fails(tmp_path) -> None:
    doc = _doc()
    del doc["score"]
    assert _gate(_write(tmp_path, doc)) is False


def test_stale_age_fails(tmp_path) -> None:
    old = datetime.now(timezone.utc) - timedelta(
        days=QG.MUTATION_BASELINE_MAX_AGE_DAYS + 1)
    doc = _doc(recorded_at=old.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert _gate(_write(tmp_path, doc)) is False


def test_bad_recorded_at_fails(tmp_path) -> None:
    assert _gate(_write(tmp_path, _doc(recorded_at="yesterday-ish"))) is False


def test_non_ancestor_base_commit_fails(tmp_path) -> None:
    assert _gate(_write(tmp_path, _doc(base_commit="0" * 40))) is False


def test_missing_base_commit_fails(tmp_path) -> None:
    assert _gate(_write(tmp_path, _doc(base_commit=""))) is False


def test_real_repo_baseline_passes_when_present() -> None:
    """The bootstrap artifact committed with this change must PASS the gate
    on the tree that carries it (this change's acceptance)."""
    path = ROOT / QG.MUTATION_BASELINE_REL
    assert path.is_file(), "the bootstrap baseline artifact is missing"
    assert _gate(path) is True


# ------------------------------------------------ recorder units

def test_sidecar_parse_maps_mutmut_exit_codes(tmp_path) -> None:
    meta = tmp_path / "x.py.meta"
    meta.write_text(json.dumps({"exit_code_by_key": {
        "k1": 1, "k2": 3, "k3": -24,   # killed family
        "k4": 0,                       # survived
        "k5": 36,                      # timeout
        "k6": 34,                      # skipped
        "k7": None,                    # not_checked
        "k8": 999,                     # unknown -> suspicious (mutmut rule)
    }}), encoding="utf-8")
    counts = MB._parse_sidecar(meta)
    assert counts["killed"] == 3 and counts["survived"] == 1
    assert counts["timeout"] == 1 and counts["skipped"] == 1
    assert counts["not_checked"] == 1 and counts["suspicious"] == 1


def test_sidecar_without_rows_refuses(tmp_path) -> None:
    meta = tmp_path / "empty.py.meta"
    meta.write_text(json.dumps({"exit_code_by_key": {}}), encoding="utf-8")
    try:
        MB._parse_sidecar(meta)
    except SystemExit:
        return
    raise AssertionError("an empty sidecar must refuse, never fabricate zeros")


def test_recorder_reads_the_declared_bounded_scope() -> None:
    cfg = MB._load_mutmut_config(ROOT)
    assert cfg["only_mutate"] == ["scripts/slot_monitor.py"]
    assert cfg["pytest_add_cli_args_test_selection"] \
        == ["tests/test_slot_monitor_636.py"]
