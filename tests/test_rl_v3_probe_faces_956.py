#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rl_v3_probe_faces_956.py — the probe-face contract.

Every unit family ships a MECHANICAL V(s) partial-credit probe: the
unit-local ``probe.py <ws>`` shim (checker.py's trust boundary, mirrored)
emits one kunglao-probe-reading/1 doc, and scripts/rlvr/probe_face.py is
the registered interface + the direction face's ΔV seam. Pinned here:

  D1  determinism: same ws state twice -> byte-same reading (contract
      face on a synthetic unit, and byte-same stdout on the real corpus
      shims)
  D2  fail-closed matrix: missing unit / missing entrypoint / missing ws
      / crashing shim / non-JSON output / schema mismatch / scalar out
      of range / harness-cap timeout -> scalar 0.0 + reason, NEVER a
      raise
  D3  the ΔV arithmetic: clamped scalars, monotone in the readings,
      bounded in [-1, 1], fail-closed (garbage readings price 0.0)
  G1  validate_task: NEW units (not in PROBE_FACE_GRANDFATHERED) reject
      without a probe block / with a bad entrypoint or cadence;
      grandfathered units pass without one (the existing corpus keeps
      validating)
  G2  corpus lint: the missing-probe face is a WARN (non-fatal, exit 0),
      present on grandfathered units, absent on declared ones
  G3  schemas/eval-task-v1.json declares the probe block (const
      entrypoint + cadence enum), NOT in required (grandfather)
  R1  real-corpus runs (skipif: operator-local corpus, never tracked):
      the tf-novelvm probe on a partial answer (solved count + hamming
      gradient + saturation at the exact answer), the tf-snake probe on
      a synthetic ws (no-candidate fail-closed; a spawn-path exercise
      with a no-op candidate -> no-record fail-closed), the stock-
      baseline scalar pin, and the end-to-end ΔV seam reading through
      run_probe over two ws states with a positive ΔV

stdlib + PyYAML only (house eval-script rule).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rlvr import probe_face

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "eval-task-v1.json"
# operator-local corpus: KUNGLAO_BP_UNITS wins, else the repo-relative
# face (the lint's corpus_roots logic, mirrored); CI carries no corpus
BP_UNITS = Path(os.environ.get(
    "KUNGLAO_BP_UNITS", str(ROOT / "experiments" / "blocked-path-units")))
CORPUS_PRESENT = (BP_UNITS / "tf-novelvm-rust-v1" / "probe.py").is_file() \
    and (BP_UNITS / "tf-snake-trainer-v1" / "probe.py").is_file()

requires_corpus = pytest.mark.skipif(
    not CORPUS_PRESENT, reason="operator-local blocked-path corpus absent")


# ---- helpers --------------------------------------------------------------
def _synthetic_unit(tmp: Path, body: str, *, task_id: str = "syn-probe-v1",
                    family: str = "tf-novelvm",
                    task_extra: str = "") -> Path:
    d = tmp / "units" / task_id
    d.mkdir(parents=True)
    (d / "task.yaml").write_text(
        f"schema: kunglao-eval-task/1\n"
        f"task_id: {task_id}\n"
        f"family: {family}\n"
        f"probe:\n"
        f"  entrypoint: probe.py\n"
        f"  cadence: instant\n"
        f"{task_extra}",
        encoding="utf-8")
    (d / "probe.py").write_text(body, encoding="utf-8")
    return d


HAPPY_BODY = '''#!/usr/bin/env python3
"""synthetic probe: scalar = min(1, int(ws/prog.txt)/10) — deterministic."""
import json, sys, os
ws = sys.argv[1]
try:
    with open(os.path.join(ws, "prog.txt"), encoding="utf-8") as fh:
        n = int(fh.read().strip() or "0")
except OSError:
    n = 0
doc = {"schema": "kunglao-probe-reading/1", "task_id": "syn-probe-v1",
       "family": "tf-novelvm", "scalar": round(min(1.0, n / 10), 6),
       "vector": {"n": n}, "reason": "prog-read"}
sys.stdout.write(json.dumps(doc, sort_keys=True) + "\\n")
'''

CRASH_BODY = '''#!/usr/bin/env python3
raise RuntimeError("boom")
'''

SLEEP_BODY = '''#!/usr/bin/env python3
import time
time.sleep(30)
'''

NONJSON_BODY = '''#!/usr/bin/env python3
import sys
sys.stdout.write("not json at all")
'''

BADSCHEMA_BODY = '''#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps({"schema": "kunglao-other/1", "scalar": 0.5}))
'''

OVERRANGE_BODY = '''#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps({
    "schema": "kunglao-probe-reading/1", "scalar": 1.5,
    "vector": {}, "reason": "lying"}))
'''

NONNUMERIC_BODY = '''#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps({
    "schema": "kunglao-probe-reading/1", "scalar": "high",
    "vector": {}, "reason": "lying differently"}))
'''


def _bytes(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True)


def _valid_task(task_id: str, probe: dict | None = None,
                *, tier: str = "toolflex",
                eval_version: str = "eval-v1.3") -> dict:
    task = {
        "schema": "kunglao-eval-task/1",
        "task_id": task_id,
        "eval_version": eval_version,
        "tier": tier,
        "source": "constructed",
        "family": "tf-novelvm",
        "seed": 54601,
        "anchors": {
            "goal_verbatim": "produce answer.txt",
            "success_criterion": "four digests byte-exact",
            "verification_method": "reproduction",
        },
        "workspace_scaffold": {
            "language": "rust",
            "files": ["target/README.txt"],
            "entry": "target/README.txt",
            "candidate_contract": "answer.txt — four 16-hex lines",
        },
        "checker": {
            "kind": "replay-roundtrip",
            "oracles": ["replay-roundtrip"],
            "entrypoint": "checker.py",
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": {"min_pair_ratio": 1.0},
        },
        "ground_truth": {"file": "ground_truth.json", "space_bits": 256},
        "contamination": {"held_out": True, "distiller_excluded": True,
                          "provenance": "constructed"},
        "material_class": "black-box",
    }
    if probe is not None:
        task["probe"] = probe
    return task


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_shim(unit: Path, ws: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(unit / "probe.py"), str(ws)],
        capture_output=True, text=True, timeout=120)


# ---- D1/D2: the contract faces (synthetic units, CI-green) ---------------
def test_run_probe_happy_path_and_ws_reaches_shim(tmp_path):
    unit = _synthetic_unit(tmp_path, HAPPY_BODY)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "prog.txt").write_text("7", encoding="utf-8")
    doc = probe_face.run_probe(unit, ws)
    assert doc["schema"] == probe_face.PROBE_SCHEMA
    assert doc["scalar"] == 0.7
    assert doc["vector"] == {"n": 7}
    assert doc["reason"] == "prog-read"
    assert doc["task_id"] == "syn-probe-v1"
    assert doc["entrypoint"] == "probe.py"


def test_run_probe_envelope_byte_deterministic(tmp_path):
    unit = _synthetic_unit(tmp_path, HAPPY_BODY)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "prog.txt").write_text("7", encoding="utf-8")
    a = _bytes(probe_face.run_probe(unit, ws))
    b = _bytes(probe_face.run_probe(unit, ws))
    assert a == b


def test_run_probe_missing_unit_dir_fail_closed(tmp_path):
    doc = probe_face.run_probe(tmp_path / "no-such-unit", tmp_path)
    assert doc["scalar"] == 0.0
    assert doc["reason"]


@pytest.mark.parametrize("body,reason", [
    (CRASH_BODY, "probe-crash rc=1"),
    (NONJSON_BODY, "non-json-output"),
    (BADSCHEMA_BODY, "schema-mismatch"),
    (OVERRANGE_BODY, "scalar-out-of-range"),
    (NONNUMERIC_BODY, "scalar-out-of-range"),
])
def test_run_probe_fault_matrix_fail_closed(tmp_path, body, reason):
    unit = _synthetic_unit(tmp_path, body)
    ws = tmp_path / "ws"
    ws.mkdir()
    doc = probe_face.run_probe(unit, ws)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == reason
    assert doc["schema"] == probe_face.PROBE_SCHEMA


def test_run_probe_missing_entrypoint_file_fail_closed(tmp_path):
    unit = _synthetic_unit(tmp_path, HAPPY_BODY)
    (unit / "probe.py").unlink()
    doc = probe_face.run_probe(unit, tmp_path)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "probe-entrypoint-missing"


def test_run_probe_missing_ws_fail_closed(tmp_path):
    unit = _synthetic_unit(tmp_path, HAPPY_BODY)
    doc = probe_face.run_probe(unit, tmp_path / "no-such-ws")
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "workspace-missing"


def test_run_probe_timeout_fail_closed(tmp_path):
    unit = _synthetic_unit(tmp_path, SLEEP_BODY)
    ws = tmp_path / "ws"
    ws.mkdir()
    doc = probe_face.run_probe(unit, ws, timeout_s=2.0)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "probe-timeout"


def test_run_probe_default_entrypoint_without_task_yaml(tmp_path):
    """A unit dir with no (or unreadable) task.yaml still dispatches on
    the checker-mirroring default entrypoint — grandfathered corpus
    units probe even before they declare the face."""
    d = tmp_path / "units" / "bare-unit"
    d.mkdir(parents=True)
    (d / "probe.py").write_text(HAPPY_BODY, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "prog.txt").write_text("3", encoding="utf-8")
    doc = probe_face.run_probe(d, ws)
    assert doc["scalar"] == 0.3
    assert doc["task_id"] == "bare-unit"


# ---- D3: the ΔV arithmetic -----------------------------------------------
def test_probe_delta_monotone():
    assert probe_face.probe_delta(None, {"scalar": 0.2},
                                  {"scalar": 0.7}) == 0.5
    assert probe_face.probe_delta(None, {"scalar": 0.7},
                                  {"scalar": 0.7}) == 0.0
    assert probe_face.probe_delta(None, {"scalar": 0.7},
                                  {"scalar": 0.2}) == -0.5


def test_probe_delta_clamped_bounded():
    # out-of-range scalars clamp BEFORE the difference
    assert probe_face.probe_delta(None, {"scalar": 0.2},
                                  {"scalar": 1.5}) == 0.8
    assert probe_face.probe_delta(None, {"scalar": -3},
                                  {"scalar": 0.2}) == 0.2
    # the result is bounded in [-1, 1]
    assert -1.0 <= probe_face.probe_delta(
        None, {"scalar": -1}, {"scalar": 2}) <= 1.0


def test_probe_delta_fail_closed_garbage_readings():
    assert probe_face.probe_delta(None, None, {"scalar": 0.4}) == 0.4
    assert probe_face.probe_delta(None, {"scalar": 0.4}, None) == -0.4
    assert probe_face.probe_delta(None, None, None) == 0.0
    assert probe_face.probe_delta(None, "garbage", {"scalar": 0.4}) == 0.4
    assert probe_face.probe_delta(None, {"scalar": "high"},
                                  {"scalar": 0.4}) == 0.4
    assert probe_face.probe_delta(None, {"scalar": float("nan")},
                                  {"scalar": 0.4}) == 0.4


def test_probe_delta_seam_end_to_end_synthetic(tmp_path):
    """The ΔV acceptance face in miniature: two real run_probe readings
    over two ws states, ΔV strictly positive, byte-deterministic."""
    unit = _synthetic_unit(tmp_path, HAPPY_BODY)
    ws0 = tmp_path / "ws0"
    ws1 = tmp_path / "ws1"
    for ws, n in ((ws0, "2"), (ws1, "9")):
        ws.mkdir()
        (ws / "prog.txt").write_text(n, encoding="utf-8")
    r0 = probe_face.run_probe(unit, ws0)
    r1 = probe_face.run_probe(unit, ws1)
    assert probe_face.probe_delta(ws1, r0, r1) == 0.7
    assert _bytes(probe_face.run_probe(unit, ws0)) == _bytes(r0)


# ---- G1: the probe contract (review round 1 semantics) --------------------
def test_new_unit_without_probe_passes_validate_task():
    """validate_task is the GRADING entry: synthetic/test units ship
    without a probe legitimately; the live-corpus enforcement is the
    corpus lint's violation face (see the lint pins below)."""
    import eval_dataset
    ok, errors = eval_dataset.validate_task(_valid_task("tf-new-unit-956"))
    assert ok, errors
    assert not any("probe block" in e for e in errors)


def test_new_unit_with_malformed_probe_rejected():
    import eval_dataset
    task = _valid_task("tf-new-unit-956", {
        "entrypoint": "judge.py", "cadence": "whenever"})
    ok, errors = eval_dataset.validate_task(task)
    assert not ok
    assert any("#956" in e for e in errors)


def test_new_unit_with_probe_passes():
    import eval_dataset
    task = _valid_task("tf-new-unit-956", {
        "entrypoint": "probe.py", "cadence": "instant"})
    ok, errors = eval_dataset.validate_task(task)
    assert ok, errors


@pytest.mark.parametrize("probe,frag", [
    ({"entrypoint": "checker.py", "cadence": "instant"}, "probe.entrypoint"),
    ({"entrypoint": "probe.py", "cadence": "per-hour"}, "probe.cadence"),
    ({"cadence": "instant"}, "probe.entrypoint"),
    ({"entrypoint": "probe.py"}, "probe.cadence"),
])
def test_new_unit_malformed_probe_rejected(probe, frag):
    import eval_dataset
    ok, errors = eval_dataset.validate_task(
        _valid_task("tf-new-unit-956", probe))
    assert not ok
    assert any(frag in e for e in errors), errors


def test_grandfathered_unit_without_probe_passes():
    import eval_dataset
    ok, errors = eval_dataset.validate_task(_valid_task("py-derive-v1"))
    assert ok, errors
    assert not any("#956" in e for e in errors)


def test_grandfathered_unit_still_validated_elsewhere():
    """Grandfathering the probe face must not mute the other faces."""
    import eval_dataset
    task = _valid_task("py-derive-v1")
    task["checker"]["entrypoint"] = ""
    ok, errors = eval_dataset.validate_task(task)
    assert not ok
    assert any("checker.entrypoint" in e for e in errors)


def test_grandfather_set_covers_both_corpus_surfaces():
    import eval_dataset
    for task_id in ("tf-snake-trainer-v1", "tf-novelvm-rust-v1",
                    "tf-novelcipher-c-v1", "tf-hardwall-ledger-py-v1",
                    "web-pack-sign-l2-v1", "chain-l3-py-v1",
                    "go-arx-v1", "smc-x86-l2"):
        assert task_id in eval_dataset.PROBE_FACE_GRANDFATHERED, task_id
    assert "tf-new-unit-956" not in eval_dataset.PROBE_FACE_GRANDFATHERED


def test_probe_cadences_enum():
    import eval_dataset
    assert eval_dataset.PROBE_CADENCES == ("instant", "bounded",
                                           "unit-defined")


# ---- G2: the corpus-lint WARN face ---------------------------------------
def _lint_fixture_unit(corpus: Path, unit: str, *,
                       probe: dict | None = None) -> Path:
    d = corpus / unit
    d.mkdir(parents=True)
    task = {
        "schema": "kunglao-eval-task/1",
        "task_id": unit,
        "family": "tf-novelvm",
        "material_class": "black-box",
    }
    if probe is not None:
        task["probe"] = probe
    (d / "task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
    (d / "target").mkdir()
    (d / "target" / "vm.bin").write_bytes(b"\x7fELF-mock")
    return d


def _run_lint(*roots: Path) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(ROOT / "scripts" / "eval_corpus_lint.py")]
    for r in roots:
        argv += ["--corpus-root", str(r)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def test_lint_violation_on_new_unit_missing_probe(tmp_path):
    _lint_fixture_unit(tmp_path, "lint-956-a")
    out = _run_lint(tmp_path)
    assert out.returncode == 1, out.stdout
    assert "PROBE lint-956-a" in out.stdout


def test_lint_warns_on_grandfathered_unit_missing_probe(tmp_path):
    _lint_fixture_unit(tmp_path, "py-derive-v1")  # in the grandfather set
    out = _run_lint(tmp_path)
    assert "PROBE[WARN] py-derive-v1" in out.stdout


def test_lint_silent_with_declared_probe_block(tmp_path):
    _lint_fixture_unit(tmp_path, "lint-956-b", probe={
        "entrypoint": "probe.py", "cadence": "instant"})
    out = _run_lint(tmp_path)
    assert out.returncode == 0, out.stdout
    assert "PROBE[WARN]" not in out.stdout
    assert "0 probe-face grandfather warn(s)" in out.stdout


def test_lint_warns_do_not_shadow_violations(tmp_path):
    """Violations dominate: a red corpus stays red, warns stay warns."""
    d = _lint_fixture_unit(tmp_path, "lint-956-c")
    (d / "target" / "vm.rs").write_text("fn main() {}", encoding="utf-8")
    out = _run_lint(tmp_path)
    assert out.returncode == 1
    assert "CONTAMINATED[TARGET_SOURCE]" in out.stdout


# ---- G3: the schema declaration ------------------------------------------
def test_schema_declares_probe_block_not_required():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    probe = schema["properties"]["probe"]
    assert probe["properties"]["entrypoint"]["const"] == "probe.py"
    assert probe["properties"]["cadence"]["enum"] == [
        "instant", "bounded", "unit-defined"]
    assert set(probe["required"]) == {"entrypoint", "cadence"}
    assert "probe" not in schema["required"]  # grandfathered corpus


# ---- R1: real-corpus probe runs ------------------------------------------
def _gt_outs(unit: str) -> list[str]:
    gt = json.loads(
        (BP_UNITS / unit / "ground_truth.json").read_text(encoding="utf-8"))
    return [str(p["out"]) for p in sorted(gt["published_pairs"],
                                          key=lambda p: p["i"])]


@requires_corpus
def test_corpus_novelvm_probe_partial_answer(tmp_path):
    unit = BP_UNITS / "tf-novelvm-rust-v1"
    e = _gt_outs("tf-novelvm-rust-v1")
    near = format(int(e[1], 16) ^ 0x1, "016x")  # one-bit near miss
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "answer.txt").write_text(
        f"{e[0]}\n{near}\n{'0' * 16}\n", encoding="utf-8")
    first = _run_shim(unit, ws)
    assert first.returncode == 0, first.stderr
    second = _run_shim(unit, ws)
    assert first.stdout == second.stdout  # D1 on the real shim
    doc = json.loads(first.stdout)
    assert doc["schema"] == probe_face.PROBE_SCHEMA
    assert 0.0 < doc["scalar"] < 1.0
    assert doc["vector"]["solved"] == 1
    assert doc["vector"]["hamming_0"] == 0
    assert doc["vector"]["hamming_1"] == 1
    assert doc["vector"]["hamming_2"] == 32
    assert doc["vector"]["hamming_3"] == 64  # missing line reads worst


@requires_corpus
def test_corpus_novelvm_probe_saturates_only_at_truth(tmp_path):
    unit = BP_UNITS / "tf-novelvm-rust-v1"
    e = _gt_outs("tf-novelvm-rust-v1")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "answer.txt").write_text("\n".join(e) + "\n", encoding="utf-8")
    doc = json.loads(_run_shim(unit, ws).stdout)
    assert doc["scalar"] == 1.0
    assert doc["reason"] == "answer-graded solved=4/4"
    # one nibble off on every line: strictly below saturation
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    almost = [format(int(x, 16) ^ 0x8, "016x") for x in e]
    (ws2 / "answer.txt").write_text("\n".join(almost) + "\n",
                                    encoding="utf-8")
    doc2 = json.loads(_run_shim(unit, ws2).stdout)
    assert 0.0 < doc2["scalar"] < 1.0


@requires_corpus
def test_corpus_novelvm_probe_missing_answer_fail_closed(tmp_path):
    unit = BP_UNITS / "tf-novelvm-rust-v1"
    ws = tmp_path / "ws"
    ws.mkdir()
    doc = json.loads(_run_shim(unit, ws).stdout)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "no-answer"


@requires_corpus
def test_corpus_snake_probe_synthetic_ws_fail_closed(tmp_path):
    """tf-snake probe on a synthetic ws: no candidate -> fail-closed,
    byte-deterministic, exit 0 (never a crash)."""
    unit = BP_UNITS / "tf-snake-trainer-v1"
    ws = tmp_path / "ws"
    ws.mkdir()
    first = _run_shim(unit, ws)
    assert first.returncode == 0, first.stderr
    assert first.stdout == _run_shim(unit, ws).stdout
    doc = json.loads(first.stdout)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "no-candidate"


@requires_corpus
def test_corpus_snake_probe_noop_candidate_no_record(tmp_path):
    """The spawn path exercised end-to-end (tempdir scaffold copy,
    stdin=DEVNULL, bounded): a candidate that exits without launching
    the game leaves no run-log -> fail-closed, not a crash."""
    unit = BP_UNITS / "tf-snake-trainer-v1"
    ws = tmp_path / "ws"
    (ws / "runs" / "deliverables").mkdir(parents=True)
    candidate = ws / "runs" / "deliverables" / "candidate"
    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    candidate.chmod(0o755)
    first = _run_shim(unit, ws)
    assert first.returncode == 0, first.stderr
    assert first.stdout == _run_shim(unit, ws).stdout
    doc = json.loads(first.stdout)
    assert doc["scalar"] == 0.0
    assert doc["reason"] == "no-record rc=0"


@requires_corpus
def test_corpus_snake_stock_baseline_reading():
    """The stock attract log (probes/stock-behavior.json, the game's own
    observed no-trainer behavior) prices a stable partial: structural
    faces true, progress magnitudes small, scalar 0.327833."""
    mod = _load_module(BP_UNITS / "tf-snake-trainer-v1" / "probe.py",
                       "tf_snake_probe_v1")
    stock = json.loads(
        (BP_UNITS / "tf-snake-trainer-v1" / "probes"
         / "stock-behavior.json").read_text(encoding="utf-8"))
    log = {"schema": "snake-log/2", "seed": stock.get("seed", 7),
           "score": stock["score"], "frames": stock["frames"],
           "foods": stock["foods"], "deaths": stock["deaths"],
           "moves": stock["moves"], "poisoned": False,
           "proof": stock["proof"]}
    scalar, vector = mod.reading_from_log(log)
    assert scalar == 0.327833
    assert vector["face_schema"] and vector["face_seed"]
    assert vector["face_clean"] and vector["face_proof"]
    assert not vector["face_score"] and not vector["face_deaths"]
    assert vector["score_mag"] == 0.02
    assert vector["frames_mag"] == round(190 / 1800, 6)
    # the v2 variant carries its own seed/key surface
    mod2 = _load_module(BP_UNITS / "tf-snake-trainer-v2" / "probe.py",
                        "tf_snake_probe_v2")
    assert mod2.SEED == 9
    assert mod2.TASK_ID == "tf-snake-trainer-v2"


@requires_corpus
def test_corpus_snake_scalar_monotone_in_progress():
    mod = _load_module(BP_UNITS / "tf-snake-trainer-v1" / "probe.py",
                       "tf_snake_probe_v1_mono")
    stock = {"schema": "snake-log/2", "seed": 7, "score": 10,
             "frames": 190, "foods": 1, "deaths": 1, "poisoned": False,
             "proof": None}
    s_stock, _ = mod.reading_from_log(stock)
    better = dict(stock, score=120, foods=6, frames=400)
    proofed = dict(better, deaths=0,
                   proof=format(mod.proof_token(7, 120, 400, 6, 0), "016x"))
    s_better, _ = mod.reading_from_log(better)
    s_proofed, _ = mod.reading_from_log(proofed)
    perfect = {"schema": "snake-log/2", "seed": 7, "score": 500,
               "frames": 1800, "foods": 20, "deaths": 0,
               "poisoned": False,
               "proof": format(mod.proof_token(7, 500, 1800, 20, 0),
                               "016x")}
    s_perfect, _ = mod.reading_from_log(perfect)
    assert 0.0 <= s_stock < s_better < s_proofed < s_perfect == 1.0


# ---- the ΔV seam over the REAL corpus probe ------------------------------
@requires_corpus
def test_seam_end_to_end_corpus_novelvm(tmp_path):
    """Card acceptance: the registered interface reads the real
    corpus shim end-to-end and the ΔV seam prices the progress."""
    unit = BP_UNITS / "tf-novelvm-rust-v1"
    e = _gt_outs("tf-novelvm-rust-v1")
    empty = tmp_path / "empty"
    partial = tmp_path / "partial"
    empty.mkdir()
    partial.mkdir()
    (partial / "answer.txt").write_text(
        f"{e[0]}\n{e[1]}\n", encoding="utf-8")
    r0 = probe_face.run_probe(unit, empty)
    r1 = probe_face.run_probe(unit, partial)
    assert r0["scalar"] == 0.0
    assert r1["scalar"] == pytest.approx(0.5, abs=1e-6)
    assert probe_face.probe_delta(partial, r0, r1) == pytest.approx(
        0.5, abs=1e-6)
    assert _bytes(r1) == _bytes(probe_face.run_probe(unit, partial))


# ---- the facade reachability ---------------------------------------------
def test_facade_reaches_probe_face():
    import rlvr
    assert rlvr.probe_face is probe_face
    assert "probe_face" in rlvr.__all__
