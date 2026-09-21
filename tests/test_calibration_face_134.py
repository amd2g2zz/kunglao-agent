# -*- coding: utf-8 -*-
"""#134 rho/Platt calibration cockpit face — producer graduation, PRODUCE only.

The #823-P2 shadow: (rho, z_self) pairs accumulate in the ledger feeding
Platt calibration, but the calibration machinery idles — nothing computes
the curve, and nothing shows whether the rho sampler is even alive. This
card graduates the producer + face:

  1. calibration curve + current gap, offline over ledger rho_pair rows
     (the tuition_curve offline contract: tolerant reads, 4-decimal
     rounding, ledger-only, nothing written back);
  2. NO gating — consumption decisions belong to v0.2 (#129/#135). Pinned
     here by an import-graph test: no gate module may consume the face;
  3. liveness — the rho sampler rides the #127 detector_eval/detector_fired
     vocabulary, so a sampler whose pairs never settle is a loud DORMANT
     finding (statusline health dot + face status), never silence.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import calibration_face as cf  # noqa: E402
import rho_checkpoint  # noqa: E402
import rho_verifier as rv  # noqa: E402


# ---------------------------------------------------------------- fixtures

def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1\n", encoding="utf-8")
    return ws


def _seed_pairs(ws, rows):
    """rows: (rho, z); z=None is a pending checkpoint sample (still a
    sampler liveness observation, never a calibration pair)."""
    p = ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for rho, z in rows:
            f.write(json.dumps({
                "ts": "2026-09-01T00:00:00Z", "actor": "rho_verifier",
                "action": "rho_pair", "claim": None, "tool": None,
                "artifact": None, "exit": None,
                "detail": json.dumps({"rho": rho, "z": z}),
            }, ensure_ascii=False) + "\n")


def _rows(ws, action):
    out = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("action") == action:
                out.append(json.loads(line))
    return out


# ------------------------------------------- 1. calibration curve (RED first)

def test_curve_perfectly_calibrated_fixture_has_zero_error():
    """rho = mechanical probability of z: a fixture whose in-bin observed
    pass rate equals the mean rho must give ECE 0 (within rounding). All
    four pairs share one bin (mean 0.5, observed 0.5)."""
    pairs = [{"score": 0.5, "outcome": 1.0}, {"score": 0.5, "outcome": 0.0},
             {"score": 0.5, "outcome": 1.0}, {"score": 0.5, "outcome": 0.0}]
    data = cf.curve(pairs)
    assert data["n"] == 4
    assert data["ece"] < 0.02
    # current_gap contract: the LATEST settled pair's |rho - z| -> |0.5-0.0|
    assert abs(data["current_gap"] - 0.5) < 1e-9


def test_curve_miscalibrated_fixture_has_positive_error():
    """rho claims 0.9 everywhere but the anchor says failed: the gap must be
    large and positive — the curve face EXISTS to show this."""
    pairs = ([{"score": 0.9, "outcome": 0.0}] * 4
             + [{"score": 0.1, "outcome": 1.0}] * 4)
    data = cf.curve(pairs)
    assert data["ece"] > 0.5
    bins = {b["mean_score"]: b for b in data["bins"]}
    assert bins[0.9]["observed"] == 0.0
    assert bins[0.9]["gap"] == pytest.approx(0.9)
    # Platt fit separates the classes: high score -> low calibrated prob
    w, b = data["platt"]["w"], data["platt"]["b"]
    assert rho_checkpoint.sigmoid(w * 0.9 + b) < 0.5
    assert rho_checkpoint.sigmoid(w * 0.1 + b) > 0.5


def test_curve_empty_is_insistent_not_silent():
    data = cf.curve([])
    assert data["n"] == 0
    assert data["ece"] is None          # insufficient, never 0.0
    assert data["current_gap"] is None
    assert data["bins"] == []


def test_platt_is_single_sourced_not_a_second_fit():
    """The face reuses rho_checkpoint.fit_platt (the #823 stdlib fit) — no
    second logistic-regression implementation may appear on this card."""
    pairs = [{"score": 0.2, "outcome": 0.0}, {"score": 0.8, "outcome": 1.0}]
    data = cf.curve(pairs)
    assert (data["platt"]["w"], data["platt"]["b"]) == \
        tuple(round(v, 6) for v in rho_checkpoint.fit_platt(pairs))


# ------------------------------------------------ 2. offline ledger contract

def test_face_from_fixture_ledger(tmp_path):
    """tuition_curve discipline: fixture ledger rows -> face, offline."""
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, [(0.9, 1.0), (0.1, 0.0), (0.5, None), (0.4, None)])
    face = cf.face(ws)
    assert face["n_samples"] == 4          # every checkpoint sample counts
    assert face["n_pairs"] == 2            # only settled anchors calibrate
    assert face["status"] == "ACTIVE"
    assert face["ece"] is not None
    assert face["schema"] == "rho-calibration/1"
    # settled pairs match the ledger replay single source exactly
    replay = rv.pairs_from_ledger(ws)
    assert face["n_pairs"] == len(replay)
    assert sorted(p["score"] for p in replay) == [0.1, 0.9]


def test_face_empty_ledger_is_no_data(tmp_path):
    ws = _mk_ws(tmp_path)
    face = cf.face(ws)
    assert face["status"] == "NO_DATA"
    assert face["n_samples"] == 0 and face["n_pairs"] == 0


def test_face_pending_only_is_loud_dormant(tmp_path):
    """The digest: pairs never settling in real runs is a loud DORMANT
    finding, not silence."""
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, [(0.5, None), (0.6, None)])
    face = cf.face(ws)
    assert face["status"] == "DORMANT"
    assert face["n_samples"] == 2 and face["n_pairs"] == 0
    text = cf.summarize(face)
    assert "DORMANT" in text


def test_face_malformed_rows_are_skipped(tmp_path):
    ws = _mk_ws(tmp_path)
    p = ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl"
    p.write_text(
        "\n"
        + json.dumps({"action": "rho_pair", "detail": "{bad json"})
        + "\n"
        + json.dumps({"action": "dispatch", "detail": "{}"}) + "\n"
        + json.dumps({"action": "rho_pair",
                      "detail": json.dumps({"rho": 0.7, "z": 1.0})}) + "\n",
        encoding="utf-8")
    face = cf.face(ws)
    # the corrupt row still counts as a SAMPLE (liveness is row-honest: the
    # sampler fired) but can never calibrate (its payload is unreadable)
    assert face["n_samples"] == 2 and face["n_pairs"] == 1
    assert face["status"] == "ACTIVE"


# ------------------------------------------- 3. rho sampler liveness (#127)

def test_rho_sampler_emits_detector_liveness_pair(tmp_path):
    """Every checkpoint sample is a detector_eval; a settled anchor is the
    detector_fired the sampler exists for. detector_liveness reads the SAME
    rows — the #127 vocabulary, no second mechanism."""
    import detector_liveness as dl
    ws = _mk_ws(tmp_path)
    rv.sample_and_pair(ws)                       # pending: eval, no fire
    rv.sample_and_pair(ws, z=1.0)                # settled: eval + fire
    assert len(_rows(ws, "detector_eval")) == 2
    assert len(_rows(ws, "detector_fired")) == 1
    report = dl.liveness_report(ws)
    entry = report["detectors"]["rho_sampler"]
    assert entry == {"evaluations": 2, "fires": 1, "status": "ACTIVE"}
    assert report["dormant"] == []


def test_rho_sampler_never_settling_is_dormant(tmp_path):
    import detector_liveness as dl
    ws = _mk_ws(tmp_path)
    rv.sample_and_pair(ws)
    rv.sample_and_pair(ws)
    report = dl.liveness_report(ws)
    assert report["detectors"]["rho_sampler"]["status"] == "DORMANT"
    assert "rho_sampler" in report["dormant"]


def test_rho_sampler_diagnostic_face_writes_nothing(tmp_path):
    """emit=False stays the read-only face (#466 contract) — no liveness
    rows either."""
    import detector_liveness as dl
    ws = _mk_ws(tmp_path)
    rv.sample_and_pair(ws, emit=False)
    assert _rows(ws, "detector_eval") == []
    assert dl.liveness_report(ws)["detectors"] == {}


# ------------------------------------------------- 4. cockpit face renders

def test_snapshot_carries_calibration_face(tmp_path):
    import statusline_snapshot as sls
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, [(0.9, 1.0), (0.1, 0.0)])
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    snap = sls.build_snapshot(ws)
    cal = snap["calibration"]
    assert cal["status"] == "ACTIVE"
    assert cal["n_pairs"] == 2
    assert "ece" in cal and "current_gap" in cal


def test_snapshot_calibration_absent_ws_is_fail_open(tmp_path):
    import statusline_snapshot as sls
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    snap = sls.build_snapshot(ws)
    assert snap["calibration"]["status"] == "NO_DATA"


@pytest.mark.skipif(__import__("shutil").which("node") is None,
                    reason="node unavailable")
def test_renderer_shows_calibration_segments(tmp_path):
    """The cockpit face RENDERS: active face shows ece+n; dormant is loud;
    NO_DATA hides the segment (renderer hides absent, never a placeholder)."""
    import subprocess
    import os
    renderer = SCRIPTS / "statusline_render.mjs"
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    base = {"schema": 2, "ts": "2026-09-21T00:00:00Z", "state": "idle",
            "flash": {"seq": 0, "reason": None, "ts": None, "text": None}}

    def run(snap):
        (ws / "runs" / ".kunglao-statusline.json").write_text(
            json.dumps(snap), encoding="utf-8")
        env = dict(os.environ, KUNGLAO_STATUSLINE_HUD="",
                   KUNGLAO_STATUSLINE_NOW_MS="1789987200000")
        return subprocess.run(["node", str(renderer)],
                              input=json.dumps({"workspace": {
                                  "current_dir": str(ws)},
                                  "model": {"display_name": "t"}}),
                              capture_output=True, text=True, timeout=30,
                              cwd=str(ws.parent), env=env)

    active = dict(base, calibration={"status": "ACTIVE", "n_samples": 8,
                                     "n_pairs": 6, "ece": 0.0423,
                                     "current_gap": 0.1, "bins": [],
                                     "platt": {"w": 1.0, "b": 0.0},
                                     "schema": "rho-calibration/1"})
    r = run(active)
    assert r.returncode == 0, r.stderr
    assert "ρ-z" in r.stdout and "0.04" in r.stdout
    dormant = dict(base, calibration={"status": "DORMANT", "n_samples": 5,
                                      "n_pairs": 0, "ece": None,
                                      "current_gap": None, "bins": [],
                                      "platt": None,
                                      "schema": "rho-calibration/1"})
    r = run(dormant)
    assert r.returncode == 0, r.stderr
    assert "DORMANT" in r.stdout
    r = run(base)  # NO_DATA / absent -> segment hidden
    assert r.returncode == 0, r.stderr
    assert "ρ-z" not in r.stdout


# --------------------------------------------------- 5. zero-gating pin

_GATE_SUFFIX = "_gate.py"


def _imports(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_no_gate_consumes_the_calibration_face():
    """Shadow preserved: no gate/hook module may import calibration_face or
    the rho Platt data path. Consumption decisions are v0.2 (#129) — this
    card graduates the producer + display face ONLY. The ONE sanctioned
    consumer is statusline_snapshot (the display face mount); anything else
    (any gate, any hook) fails this pin."""
    sanctioned = {"statusline_snapshot"}
    offenders = []
    for d in ("scripts", "hooks"):
        for p in sorted((ROOT / d).glob("*.py")):
            if p.name == "calibration_face.py":
                continue
            names = _imports(p)
            if "calibration_face" in names and p.stem not in sanctioned:
                offenders.append(f"{p.relative_to(ROOT)}: imports "
                                 "calibration_face")
            if p.name.endswith(_GATE_SUFFIX):
                refs = names & {"calibration_face", "rho_verifier",
                                "rho_checkpoint"}
                if refs:
                    offenders.append(f"GATE {p.relative_to(ROOT)}: "
                                     f"{sorted(refs)}")
    assert not offenders, f"gating consumption appeared: {offenders}"


def test_face_module_is_produce_only():
    """And the face itself must stay read-only: it imports no gate module."""
    names = _imports(SCRIPTS / "calibration_face.py")
    gate_mods = {p.stem for p in SCRIPTS.glob("*_gate.py")}
    assert not (names & gate_mods), names & gate_mods
