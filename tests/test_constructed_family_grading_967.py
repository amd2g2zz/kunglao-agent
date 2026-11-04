# -*- coding: utf-8 -*-
"""tests/test_constructed_family_grading_967.py — #967: the constructed-unit
families grade through the mechanical checker without registration.

Pins the #967 checker face (scripts/eval_checker.py):

  1. every unit family under the operator-local constructed corpus
     (experiments/blocked-path-units/) resolves family meta through the
     checker WITHOUT a static registry row (self-describing task.yaml
     derivation; the loud KeyError without unit context is preserved);
  2. the smoke round-1 candidate (the workspace's delivered program
     text) is ACCEPTED — graded, not refused, not crashed: the grader
     stops refusing constructed families;
  3. a byte-exact answer document earns PASS (the smoke F2 proof: a
     correct solution can earn PASS now);
  4. zero-registration end-to-end on a SYNTHETIC constructed unit (CI
     runs this without the operator corpus): the next constructed unit
     grades with no contract row and no registry row;
  5. ungradable unknowns refuse loudly and structurally (BAD_TASK),
     never mis-grade.

The operator-local corpus never ships (gitignored by ruling); tests
reading it skip when absent. Dot-prefixed unit dirs are rejected mints
(`.rejected-*`) — not corpus members, skipped.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_checker as chk  # noqa: E402

# The constructed corpus: the worktree-local copy, the main checkout's
# copy (worktree ROOT.parent.parent == the main repo), or the env face.
_BP_CANDIDATES = (
    ROOT / "experiments" / "blocked-path-units",
    ROOT.parent.parent / "experiments" / "blocked-path-units",
)
_BP_LOCAL = next(
    (p for p in (Path(os.environ["KUNGLAO_BP_UNITS"]).resolve()
                 if os.environ.get("KUNGLAO_BP_UNITS") else None,
                 *_BP_CANDIDATES)
     if p is not None and p.is_dir()),
    None)

R1_CANDIDATE_GLOB = ("runs/smoke-*/round1/workspaces/"
                     "ws-tf-hardwall-beacon-py-v1-*/runs/deliverables/"
                     "candidate.txt")

_CORPUS_ABSENT = "the constructed corpus is operator-local (skip when absent)"


def _corpus_units() -> list[Path]:
    assert _BP_LOCAL is not None
    return [d for d in sorted(_BP_LOCAL.iterdir())
            if d.is_dir() and not d.name.startswith(".")
            and (d / "task.yaml").is_file()]


def _run_checker(tdir: Path, candidate: Path) -> tuple[int, dict, str]:
    """chk.run against a temp out-dir; returns (rc, evidence, stream)."""
    import contextlib
    import io
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        with contextlib.redirect_stdout(buf):
            rc, ev = chk.run(str(tdir), candidate, out)
    return rc, ev, buf.getvalue()


def _synthetic_unit(tmp_path: Path, family: str,
                    *, pairs: list[dict] | None = None,
                    source: str = "constructed",
                    kind: str = "replay-roundtrip") -> Path:
    """A minimal valid constructed unit (schema-valid for ds.validate_task)
    with the self-describing answer-document ground truth."""
    if pairs is None:
        pairs = [{"i": 0, "file": "probes/payload-0.bin", "out": "a" * 16},
                 {"i": 1, "file": "probes/payload-1.bin", "out": "b" * 16}]
    unit = tmp_path / "unit"
    unit.mkdir(exist_ok=True)
    (unit / "task.yaml").write_text(yaml.safe_dump({
        "schema": "kunglao-eval-task/1",
        "task_id": f"{family}-v1",
        "eval_version": "eval-v1.3",
        "tier": "toolflex",
        "source": source,
        "family": family,
        "seed": 424242,
        "anchors": {
            "goal_verbatim": "produce answer.txt with the digests",
            "success_criterion": "answer.txt carries the digests byte-exact",
            "verification_method": "reproduction",
        },
        "workspace_scaffold": {
            "language": "python",
            "files": ["target/README.txt"],
            "entry": "target/README.txt",
            "candidate_contract": "answer.txt — the digest lines.",
        },
        "checker": {
            "kind": kind,
            "oracles": [kind],
            "entrypoint": "checker.py",
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": {"min_pair_ratio": 1.0},
        },
        "ground_truth": {"file": "ground_truth.json", "space_bits": 256},
        "contamination": {"held_out": True, "distiller_excluded": True,
                          "provenance": "constructed"},
    }), encoding="utf-8")
    (unit / "ground_truth.json").write_text(json.dumps({
        "schema": "kunglao-eval-ground-truth/1",
        "task_id": f"{family}-v1",
        "family": family,
        "seed": 424242,
        "eval_version": "eval-v1.3",
        "space_bits": 256,
        "published_pairs": pairs,
        "minted_probe_count": 0,
    }), encoding="utf-8")
    return unit


# ---------------------------------------------------------------------
# (1) the live corpus: every unit family resolves meta without a registry
# ---------------------------------------------------------------------
@pytest.mark.skipif(_BP_LOCAL is None, reason=_CORPUS_ABSENT)
def test_every_constructed_unit_family_meta_resolves():
    units = _corpus_units()
    assert units, "the corpus exists but no unit dirs were found"
    checked = 0
    for tdir in units:
        _, task, gt = chk.load_unit(str(tdir))
        family = task["family"]
        # the constructed class: no static registry row owns these
        assert not chk._family_registered(family), family
        # #967: the meta resolves from the self-describing unit — no
        # KeyError (the smoke F2 crash) even though no registry row exists
        meta = chk._family_meta(family, task)
        assert isinstance(meta, dict) and "toolchain" in meta, family
        # the discriminator reads the oracle contract off the ground truth
        pairs = chk._constructed_face_pairs(family, gt)
        import eval_contract as contract
        unit_graded = contract.FAMILY_CONTRACT.get(family, {}) \
            .get("grading") == "unit-entrypoint"
        if task.get("checker", {}).get("kind") == "replay-roundtrip" \
                and not unit_graded:
            assert pairs is not None, f"{family}: answer-doc oracle missing"
            assert meta["thresholds"] == task["checker"]["thresholds"]
    assert {d.name for d in units} >= {
        "tf-hardwall-beacon-py-v1", "tf-hardwall-ledger-py-v1",
        "tf-novelcipher-c-v1", "tf-novelvm-rust-v1",
    }, "the four #967 units must be present in the live corpus"


# ---------------------------------------------------------------------
# (2) the r1 candidate: ACCEPTED — graded, not refused, not crashed
# ---------------------------------------------------------------------
@pytest.mark.skipif(
    _BP_LOCAL is None
    or not list(_BP_LOCAL.glob(R1_CANDIDATE_GLOB)),
    reason="the smoke r1 workspace is operator-local material")
def test_r1_candidate_is_accepted_not_refused():
    tdir = _BP_LOCAL / "tf-hardwall-beacon-py-v1"
    candidate = sorted(_BP_LOCAL.glob(R1_CANDIDATE_GLOB))[0]
    rc, ev, stream = _run_checker(tdir, candidate)
    # ACCEPTED: a real grade, not a refusal and not a crash
    assert rc in (chk.RC_PASS, chk.RC_FAIL), stream
    assert rc != chk.RC_REFUSED, stream
    assert ev["verdict"] in ("PASS", "FAIL"), stream
    assert ev["faces"]["replay"]["face"] == "constructed-answer-doc"
    assert ev["faces"]["replay"]["count"] == 4
    # the r1 deliverable is the solver PROGRAM text, not the contracted
    # answer document — the honest grade is FAIL with a line-level gap
    assert ev["verdict"] == "FAIL"
    assert any(f["code"] == "PAIR_MISMATCH" for f in ev["failures"])


# ---------------------------------------------------------------------
# (3) the byte-exact answer document earns PASS (the F2 proof)
# ---------------------------------------------------------------------
@pytest.mark.skipif(_BP_LOCAL is None, reason=_CORPUS_ABSENT)
def test_true_answer_document_earns_pass():
    tdir = _BP_LOCAL / "tf-hardwall-beacon-py-v1"
    _, task, gt = chk.load_unit(str(tdir))
    doc = ("".join(p["out"] + "\n" for p in gt["published_pairs"]))
    with tempfile.TemporaryDirectory() as td:
        cand = Path(td) / "candidate.txt"
        cand.write_text(doc, encoding="utf-8")
        rc, ev, stream = _run_checker(tdir, cand)
    assert rc == chk.RC_PASS, stream
    assert ev["verdict"] == "PASS"
    assert ev["faces"]["replay"]["matched"] == \
        ev["faces"]["replay"]["count"] == 4
    assert ev["metrics"]["converged"] == 1
    assert "VERDICT PASS" in stream


# ---------------------------------------------------------------------
# (4) zero registration end-to-end: the NEXT constructed unit grades
# ---------------------------------------------------------------------
def test_next_constructed_unit_grades_with_zero_registration(tmp_path):
    family = "tf-next-wall-synth"
    import eval_contract as contract
    with pytest.raises(KeyError):
        contract.require_family(family)  # no contract row, by design
    unit = _synthetic_unit(tmp_path, family)
    doc = "a" * 16 + "\n" + "b" * 16 + "\n"
    cand = tmp_path / "candidate.txt"
    cand.write_text(doc, encoding="utf-8")
    rc, ev, stream = _run_checker(unit, cand)
    assert rc == chk.RC_PASS, stream
    assert ev["faces"]["replay"]["face"] == "constructed-answer-doc"
    assert ev["metrics"]["converged"] == 1
    assert "VERDICT PASS" in stream


def test_constructed_candidate_suffix_defaults_to_txt(tmp_path):
    family = "tf-next-wall-suffix"
    unit = _synthetic_unit(tmp_path, family)
    cand = tmp_path / "candidate.txt"
    cand.write_text("aa\nbb\n", encoding="utf-8")
    rc, ev, stream = _run_checker(unit, cand)
    assert rc == chk.RC_FAIL
    assert ev["faces"]["replay"]["face"] == "constructed-answer-doc"
    assert ev["faces"]["replay"]["matched"] == 0  # wrong lines, real grade
    assert any(f["detail"] == "line 0 mismatched" for f in ev["failures"])


def test_constructed_pass_and_line_semantics(tmp_path):
    unit = _synthetic_unit(tmp_path, "tf-next-wall-pass")
    doc = "a" * 16 + "\n" + "b" * 16 + "\n"
    cand = tmp_path / "candidate.txt"
    cand.write_text(doc, encoding="utf-8")
    rc, ev, stream = _run_checker(unit, cand)
    assert rc == chk.RC_PASS, stream
    assert ev["metrics"]["converged"] == 1
    # trailing blank lines are noise; extra answer lines are a failure
    cand.write_text(doc + "\n", encoding="utf-8")
    rc2, ev2, _ = _run_checker(unit, cand)
    assert rc2 == chk.RC_PASS
    cand.write_text(doc + "c" * 16 + "\n", encoding="utf-8")
    rc3, ev3, _ = _run_checker(unit, cand)
    assert rc3 == chk.RC_FAIL
    assert any(f["detail"] == "1 extra line(s)" for f in ev3["failures"])
    # missing line: a short document fails with the missing-line gap
    cand.write_text("a" * 16 + "\n", encoding="utf-8")
    rc4, ev4, _ = _run_checker(unit, cand)
    assert rc4 == chk.RC_FAIL
    assert any(f["detail"] == "line 1 missing" for f in ev4["failures"])


# ---------------------------------------------------------------------
# (5) ungradable unknowns refuse loudly and structurally
# ---------------------------------------------------------------------
def test_ungradable_unknown_family_refuses_structurally(tmp_path):
    """Replay-armed, unregistered, and NOT the answer-document contract:
    a structured BAD_TASK refusal (never a crash, never a mis-grade)."""
    family = "tf-unknown-inputpairs"
    pairs = [{"i": 0, "input": [1, 2, 3], "out": "ff"}]
    unit = _synthetic_unit(tmp_path, family, pairs=pairs)
    cand = tmp_path / "candidate.txt"
    cand.write_text("ff\n", encoding="utf-8")
    import contextlib
    import io
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        with contextlib.redirect_stdout(buf), pytest.raises(chk.Refusal) as ei:
            chk.run(str(unit), cand, Path(td) / "out")
    assert ei.value.code == "BAD_TASK"
    assert "#967" in ei.value.detail


def test_unregistered_family_meta_stays_loud_without_unit():
    with pytest.raises(KeyError):
        chk._family_meta("tf-not-anywhere")


def test_registered_family_faces_unchanged():
    """Registry families keep byte-identical routing (regression guard):
    the constructed face never fires for a registered family."""
    assert chk._family_meta("go-arx")["toolchain"] == "go"
    assert chk._family_meta("arm-native-kdf")["toolchain"] == "python3"
    assert chk._family_meta("chain-py") == {"toolchain": "python3"}
    assert chk._family_meta("py-derive")["toolchain"] == "python3"
    for fam in ("go-arx", "chain-py", "web-pack-sign", "arm-native-kdf",
                "env-misattr-js", "net-verify-license"):
        assert chk._constructed_face_pairs(fam, {"published_pairs": [
            {"i": 0, "file": "x", "out": "y"}]}) is None, fam
