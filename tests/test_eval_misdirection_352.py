# -*- coding: utf-8 -*-
"""tests/test_eval_misdirection_352.py — the adversarial-misdirection tier.

Three trap families minted FROM catalogued failure modes, where the trap
IS the point:

  MD-1 env-misattribution  a lazy first invocation path fails with
                           permission-flavored errors while a correct
                           path exists; the naive reading of the raw
                           error text is "the environment lacks
                           capability".
  MD-2 key rotation        crypto material that rotates (per-session /
                           per-request / timer) around a findable KDF
                           derivation point; N captures without a
                           rotation induction is the failure being
                           measured.
  MD-3 decoy markers       planted false markers (stock AES s-box inside
                           a custom cipher, honeypot key strings, a decoy
                           anti-debug branch); naive scan/decompile-first
                           lands on the decoy answer.

Checker faces grade verdict-class artifacts mechanically:
  MD-1  BYPASSED-VIA-CORRECT-PATH / ATTRIBUTED-WITH-EVIDENCE (rubric-
        compliant env verdict carrying probe evidence) / MISATTRIBUTED
        (bare env verdict).
  MD-2  ROTATION-INDUCED (rotation conclusion + cadence + derivation
        point + proof answers spanning rotation boundaries) /
        REHOOK-LOOP (captures without induction) / EXHAUSTED.
  MD-3  conclusion equality (existing replay-roundtrip machinery); the
        decoy answer is the recorded wrong-answer baseline.

Every unit ships only if the mint-time deception smoke proved the naive
method actually produces the recorded wrong answer; the manifests keep
that proof on disk. Transfer pairs (variant A/B per trap class, different
surfaces) only ENABLE a later distillation-transfer measurement — no new
cadence of any kind lives in this tier.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHECKER = SCRIPTS / "eval_checker.py"
MD_SCRIPT = SCRIPTS / "eval_misdirection.py"
MD_TASKS = ROOT / "eval" / "v1" / "tasks" / "misdirection"

NODE_AVAILABLE = shutil.which("node") is not None
GO_AVAILABLE = shutil.which("go") is not None

sys.path.insert(0, str(SCRIPTS))

import eval_dataset as ds  # noqa: E402
import eval_misdirection as md  # noqa: E402

EXPECTED_TASK_IDS = {
    "m1-fileperm-v1", "m1-net403-v1", "m1-execperm-v1",
    "m2-session-v1", "m2-request-v1", "m2-timer-v1",
    "m3-sbox-js-v1", "m3-sbox-go-v1", "m3-keystring-js-v1",
    "m3-antidebug-js-v1",
}


def _tdir(task_id: str) -> Path:
    d = MD_TASKS / task_id
    assert d.is_dir(), f"misdirection unit missing: {d}"
    return d


def _task(task_id: str) -> dict:
    return ds.load_task(_tdir(task_id))


def _gt(task_id: str) -> dict:
    return json.loads(
        (_tdir(task_id) / "ground_truth.json").read_text(encoding="utf-8"))


def _verdict_file(tmp_path: Path, doc: dict) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "verdict.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def _checker(task: str, candidate: Path, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CHECKER), "--task", task,
         "--candidate", str(candidate), "--out", str(out)],
        capture_output=True, text=True, timeout=240, cwd=str(ROOT))


def _evidence(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("EVIDENCE "):
            return json.loads(
                Path(line[len("EVIDENCE "):].strip()).read_text("utf-8"))
    raise AssertionError(f"no EVIDENCE line in checker stream: {stdout}")


# ------------------------------------------------------- registry & tier
class TestMisdirectionTierContract:
    def test_units_present_and_validate(self):
        landed = {d.name for d in ds.iter_task_dirs(tier="misdirection")}
        assert EXPECTED_TASK_IDS <= landed
        for task_id in EXPECTED_TASK_IDS:
            task = _task(task_id)
            ok, errors = ds.validate_task(task)
            assert ok, f"{task_id}: {errors}"
            assert task["tier"] == "misdirection"
            assert task["eval_version"] == "eval-v1.2"
            assert task["source"] == "constructed"
            assert task["contamination"]["distiller_excluded"] is True

    def test_schema_vocabulary_extended(self):
        schema = json.loads(
            (ROOT / "schemas" / "eval-task-v1.json").read_text("utf-8"))
        assert "misdirection" in schema["properties"]["tier"]["enum"]
        assert "eval-v1.2" in schema["properties"]["eval_version"]["enum"]
        new_kinds = {"misdirection-verdict", "rotation-verdict"}
        kind_enum = set(schema["properties"]["checker"]["properties"]
                        ["kind"]["enum"])
        assert new_kinds <= kind_enum
        assert new_kinds <= set(ds.CHECKER_KINDS)

    def test_md1_family_has_three_units(self):
        ids = [t for t in EXPECTED_TASK_IDS if t.startswith("m1-")]
        assert len(ids) >= 3
        for task_id in ids:
            assert _task(task_id)["family"].startswith("env-misattr")

    def test_md2_one_unit_per_trigger_class(self):
        classes = {}
        for task_id in EXPECTED_TASK_IDS:
            if not task_id.startswith("m2-"):
                continue
            gt = _gt(task_id)
            classes[gt["trigger_class"]] = task_id
        assert {"per-session", "per-request", "timer"} <= set(classes), classes

    def test_md3_family_has_three_units(self):
        ids = [t for t in EXPECTED_TASK_IDS if t.startswith("m3-")]
        assert len(ids) >= 3
        assert all(_task(t)["family"].startswith("decoy-marker")
                   for t in ids)

    def test_transfer_pairs_recorded_with_distinct_surfaces(self):
        pairs: dict[str, dict[str, str]] = {}
        for task_id in EXPECTED_TASK_IDS:
            transfer = _gt(task_id).get("transfer")
            if not transfer:
                continue
            pairs.setdefault(transfer["pair"], {})[transfer["variant"]] = \
                transfer["surface"]
        assert set(pairs) == {"md1", "md2", "md3"}
        for pair, variants in pairs.items():
            assert set(variants) == {"A", "B"}, pair
            assert variants["A"] != variants["B"], \
                f"{pair}: variants must differ in surface"

    def test_md_verdict_candidates_are_json_documents(self):
        for task_id in EXPECTED_TASK_IDS:
            family = _task(task_id)["family"]
            if family.startswith("decoy-marker"):
                continue
            import eval_contract as ec
            assert ec.candidate_suffix(family) == ".json", task_id


# ------------------------------------------------- deception baselines
class TestDeceptionBaselines:
    def test_deception_record_lives_in_every_manifest(self):
        for task_id in sorted(EXPECTED_TASK_IDS):
            dec = _gt(task_id).get("deception")
            assert dec, f"{task_id}: no deception record"
            assert dec.get("naive_method"), task_id
            assert dec.get("smoked_at_mint") is True, task_id

    def test_md3_decoy_baseline_is_the_recorded_wrong_answer(self):
        """The decoy baseline must be a REAL wrong answer: it reproduces
        neither of the true published outputs, by construction."""
        for task_id in ("m3-sbox-js-v1", "m3-sbox-go-v1",
                        "m3-keystring-js-v1", "m3-antidebug-js-v1"):
            gt = _gt(task_id)
            baseline = md.decoy_outputs(gt)
            assert baseline, task_id
            for pair in gt["published_pairs"]:
                assert baseline[pair["i"]] != pair["out"], \
                    f"{task_id}: decoy baseline equals truth on {pair['i']}"

    def test_md3_naive_scanner_lands_on_the_decoy(self):
        """The scripted naive method (signature/string scan or
        decompile-first) run against the COMMITTED target must produce the
        recorded decoy baseline — the trap actually deceives."""
        for task_id in ("m3-sbox-js-v1", "m3-keystring-js-v1",
                        "m3-antidebug-js-v1"):
            gt = _gt(task_id)
            target = _tdir(task_id) / _task(task_id)[
                "workspace_scaffold"]["entry"]
            naive = md.naive_scan_answer(
                target.read_text(encoding="utf-8"), gt)
            assert naive == md.decoy_outputs(gt), \
                f"{task_id}: naive scan missed the decoy"

    def test_md1_trap_error_is_permission_flavored(self):
        """The bait is textual: the committed target's lazy-path failure
        must carry permission-flavored markers so the naive reading ('the
        environment lacks capability') is the tempting one."""
        for task_id in ("m1-fileperm-v1", "m1-execperm-v1"):
            gt = _gt(task_id)
            target = _tdir(task_id) / _task(task_id)[
                "workspace_scaffold"]["entry"]
            text = target.read_text(encoding="utf-8")
            for marker in gt["trap"]["lazy_error_markers"]:
                assert marker.lower() in text.lower(), \
                    f"{task_id}: bait marker {marker!r} missing"

    @pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
    def test_md1_lazy_path_actually_fails_with_the_bait(self, tmp_path):
        """Live proof: the lazy invocation fails with the flavored error
        while the direct route derives a signature in the same env."""
        task_id = "m1-fileperm-v1"
        target = _tdir(task_id) / _task(task_id)[
            "workspace_scaffold"]["entry"]
        probe = tmp_path / "probe.js"
        probe.write_text(
            "const m = require(process.argv[2]);\n"
            "try {\n"
            "  m.handshake({});\n"
            "  console.log('UNEXPECTED_SUCCESS');\n"
            "} catch (e) {\n"
            "  console.log(String(e && e.message || e));\n"
            "  process.exit(3);\n"
            "}\n", encoding="utf-8")
        proc = subprocess.run(
            ["node", str(probe), str(target)], capture_output=True,
            text=True, timeout=60, cwd=str(_tdir(task_id)))
        assert proc.returncode == 3, proc.stdout + proc.stderr
        lazy_error = proc.stdout.strip().lower()
        gt = _gt(task_id)
        assert any(m.lower() in lazy_error
                   for m in gt["trap"]["lazy_error_markers"]), lazy_error
        direct = tmp_path / "direct.js"
        direct.write_text(
            "const m = require(process.argv[2]);\n"
            "try {\n"
            "  const r = m.handshake({ route: 'direct', payload: 'aabb' });\n"
            "  console.log(typeof r.signature === 'string' &&\n"
            "              r.signature.length > 0 ? 'DIRECT_OK' : 'NO_SIG');\n"
            "} catch (e) {\n"
            "  console.log('DIRECT_FAILED ' + e);\n"
            "  process.exit(1);\n"
            "}\n", encoding="utf-8")
        ok = subprocess.run(
            ["node", str(direct), str(target)], capture_output=True,
            text=True, timeout=60, cwd=str(_tdir(task_id)))
        assert "DIRECT_OK" in ok.stdout, ok.stdout + ok.stderr

    def test_md2_derivation_point_is_findable_in_the_target(self):
        """The rotation trap is only fair when the KDF derivation point is
        actually present and nameable in the artifact."""
        for task_id in ("m2-session-v1", "m2-request-v1", "m2-timer-v1"):
            gt = _gt(task_id)
            target = _tdir(task_id) / _task(task_id)[
                "workspace_scaffold"]["entry"]
            text = target.read_text(encoding="utf-8")
            assert gt["derivation_point"] in text, task_id


# ----------------------------------------------------- MD-1 checker face
class TestMisdirectionVerdictFace:
    TASK = "m1-fileperm-v1"

    def _reference(self, tmp_path: Path) -> Path:
        return _verdict_file(tmp_path, md.build_reference_verdict(self.TASK))

    def test_reference_bypassed_verdict_passes(self, tmp_path):
        proc = _checker(self.TASK, self._reference(tmp_path),
                        tmp_path / "out")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "BYPASSED-VIA-CORRECT-PATH"

    def test_naive_bare_env_verdict_fails_misattributed(self, tmp_path):
        gt = _gt(self.TASK)
        naive = md.build_naive_verdict(self.TASK)
        proc = _checker(self.TASK, _verdict_file(tmp_path, naive),
                        tmp_path / "out")
        assert proc.returncode == 1, "the naive attribution must FAIL"
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "MISATTRIBUTED"
        assert any(f["code"] == "MISATTRIBUTED" for f in ev["failures"])

    def test_attributed_with_evidence_passes(self, tmp_path):
        gt = _gt(self.TASK)
        doc = {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT,
            "task_id": self.TASK,
            "outcome": "environment-attributed",
            "env_verdict": {
                "conclusion": "environment lacks the privileged helper",
                "probe_evidence": [
                    {"probe": "read helper token directly",
                     "observed": "empty token file served to this env",
                     "compared": "same loader succeeds with a provisioned "
                                 "token"},
                ],
            },
        }
        proc = _checker(self.TASK, _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "ATTRIBUTED-WITH-EVIDENCE"

    def test_evidence_missing_a_rubric_field_still_misattributes(
            self, tmp_path):
        """Rubric compliance is mechanical: an env verdict whose probe
        evidence lacks any required field is a bare verdict."""
        gt = _gt(self.TASK)
        fields = gt["verdict_rubric"]["evidence_fields"]
        partial = {k: "x" for k in fields}
        incomplete = {k: v for k, v in partial.items()
                      if k != fields[-1]}
        doc = {
            "schema": md.SCHEMA_MISDIRECTION_VERDICT,
            "task_id": self.TASK,
            "outcome": "environment-attributed",
            "env_verdict": {
                "conclusion": "environment lacks the helper",
                "probe_evidence": [incomplete],
            },
        }
        proc = _checker(self.TASK, _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "MISATTRIBUTED"

    def test_wrong_route_marker_fails(self, tmp_path):
        doc = md.build_reference_verdict(self.TASK)
        doc["correct_path"]["marker"] = "0xdeadbeef"
        proc = _checker(self.TASK, _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "BYPASSED-VIA-CORRECT-PATH"
        assert any(f["code"] == "WRONG_CORRECT_PATH" for f in ev["failures"])

    def test_tampered_proof_answers_fail(self, tmp_path):
        doc = md.build_reference_verdict(self.TASK)
        doc["proof_answers"][0]["out"] = "00" * 32
        proc = _checker(self.TASK, _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1

    def test_bad_schema_is_refused(self, tmp_path):
        doc = md.build_reference_verdict(self.TASK)
        doc["schema"] = "kunglao-some-other-schema/9"
        proc = _checker(self.TASK, _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 2, proc.stdout
        assert "VERDICT REFUSED" in proc.stdout

    def test_face_covers_every_md1_unit(self, tmp_path):
        for task_id in ("m1-fileperm-v1", "m1-net403-v1", "m1-execperm-v1"):
            proc = _checker(task_id,
                            _verdict_file(tmp_path / task_id,
                                          md.build_reference_verdict(task_id)),
                            tmp_path / task_id / "out")
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"
            ev = _evidence(proc.stdout)
            assert ev["verdict_class"] == "BYPASSED-VIA-CORRECT-PATH"


# ----------------------------------------------------- MD-2 checker face
class TestRotationVerdictFace:
    UNITS = ("m2-session-v1", "m2-request-v1", "m2-timer-v1")

    def test_reference_induced_verdict_passes_every_trigger_class(
            self, tmp_path):
        for task_id in self.UNITS:
            doc = md.build_reference_verdict(task_id)
            proc = _checker(task_id, _verdict_file(tmp_path / task_id, doc),
                            tmp_path / task_id / "out")
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"
            ev = _evidence(proc.stdout)
            assert ev["verdict_class"] == "ROTATION-INDUCED"

    def test_captures_without_induction_fail_rehook_loop(self, tmp_path):
        """The named pathology: N distinct captures, no rotation
        hypothesis — mechanically a FAIL, never a pass."""
        for task_id in self.UNITS:
            gt = _gt(task_id)
            naive = md.build_naive_verdict(task_id)
            assert naive.get("captures"), task_id
            distinct = {c["observed_key"] for c in naive["captures"]}
            assert len(distinct) >= gt["verdict_rubric"][
                "min_distinct_captures"], task_id
            proc = _checker(task_id, _verdict_file(tmp_path / task_id, naive),
                            tmp_path / task_id / "out")
            assert proc.returncode == 1, f"{task_id}: naive must FAIL"
            ev = _evidence(proc.stdout)
            assert ev["verdict_class"] == "REHOOK-LOOP"

    def test_empty_artifact_fails_exhausted(self, tmp_path):
        doc = {"schema": md.SCHEMA_ROTATION_VERDICT,
               "task_id": "m2-session-v1",
               "captures": []}
        proc = _checker("m2-session-v1", _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "EXHAUSTED"

    def test_wrong_cadence_fails(self, tmp_path):
        """A rotation claim with the wrong cadence keeps the claimed class
        but fails mechanically (ROTATION_UNPROVEN)."""
        doc = md.build_reference_verdict("m2-session-v1")
        doc["rotation"]["cadence"] = "per-request"
        proc = _checker("m2-session-v1", _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "ROTATION-INDUCED"
        assert any(f["code"] == "ROTATION_UNPROVEN" for f in ev["failures"])

    def test_conclusion_without_working_derivation_fails(self, tmp_path):
        """Saying 'it rotates' is not the induction: with the conclusion
        fields right but static-key proof answers, the verdict fails —
        a single fixed key cannot span the rotation boundaries."""
        doc = md.build_reference_verdict("m2-session-v1")
        static = md.static_key_answers("m2-session-v1")
        doc["proof_answers"] = static
        proc = _checker("m2-session-v1", _verdict_file(tmp_path, doc),
                        tmp_path / "out")
        assert proc.returncode == 1
        ev = _evidence(proc.stdout)
        assert ev["verdict_class"] == "ROTATION-INDUCED"
        assert any(f["code"] == "ROTATION_UNPROVEN" for f in ev["failures"])

    def test_probes_span_rotation_boundaries(self):
        for task_id in self.UNITS:
            gt = _gt(task_id)
            probes = md.probes_for(gt)
            indexes = {p["rotation_index"] for p in probes}
            assert len(indexes) >= 2, task_id


# ----------------------------------------------------- MD-3 replay faces
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestDecoyReplayJs:
    JS_UNITS = ("m3-sbox-js-v1", "m3-keystring-js-v1", "m3-antidebug-js-v1")

    def _target(self, task_id: str) -> Path:
        return _tdir(task_id) / _task(task_id)["workspace_scaffold"]["entry"]

    def test_true_candidate_passes(self, tmp_path):
        for task_id in self.JS_UNITS:
            gt = _gt(task_id)
            cand = tmp_path / f"cand-{task_id}.js"
            cand.write_text(md.render_true_candidate(gt), encoding="utf-8")
            proc = _checker(task_id, cand, tmp_path / task_id / "out")
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"
            assert "VERDICT PASS" in proc.stdout

    def test_decoy_candidate_fails(self, tmp_path):
        for task_id in self.JS_UNITS:
            gt = _gt(task_id)
            cand = tmp_path / f"decoy-{task_id}.js"
            cand.write_text(md.render_decoy_candidate(gt), encoding="utf-8")
            proc = _checker(task_id, cand, tmp_path / task_id / "out")
            assert proc.returncode == 1, f"{task_id}: decoy must FAIL"
            assert "PAIR_MISMATCH" in proc.stdout

    def test_antidebug_decoy_never_fires_in_a_clean_env(self, tmp_path):
        """The decoy anti-debug branch is silent in a clean node env: the
        true export is deterministic across repeated runs."""
        task_id = "m3-antidebug-js-v1"
        target = self._target(task_id)
        probe = tmp_path / "probe.js"
        probe.write_text(
            "const m = require(process.argv[2]);\n"
            "console.log(m.sign('alpha'));\n"
            "console.log(m.sign('alpha'));\n", encoding="utf-8")
        proc = subprocess.run(
            ["node", str(probe), str(target)], capture_output=True,
            text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 2 and lines[0] == lines[1], proc.stdout


@pytest.mark.skipif(not GO_AVAILABLE, reason="go toolchain not available")
class TestDecoyReplayGo:
    TASK = "m3-sbox-go-v1"

    def _target(self) -> Path:
        return _tdir(self.TASK) / _task(self.TASK)[
            "workspace_scaffold"]["entry"]

    def test_true_candidate_passes(self, tmp_path):
        gt = _gt(self.TASK)
        cand = tmp_path / "cand_kdf.go"
        cand.write_text(md.render_true_candidate(gt), encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "VERDICT PASS" in proc.stdout

    def test_decoy_candidate_fails(self, tmp_path):
        gt = _gt(self.TASK)
        cand = tmp_path / "decoy_kdf.go"
        cand.write_text(md.render_decoy_candidate(gt), encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "decoy candidate must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_planted_markers_present_in_committed_go_artifact(self):
        text = self._target().read_text(encoding="utf-8")
        assert "sbox" in text.lower()
        gt = _gt(self.TASK)
        # the honeypot key literal IS the planted marker on the go face
        assert gt["deception"]["honeypot_key"] in text


# ------------------------------------------------------------- self-check
class TestSelfCheckParity:
    def test_reference_and_naive_artifacts_exist_for_every_unit(self):
        for task_id in sorted(EXPECTED_TASK_IDS):
            ref = md.build_reference_verdict(task_id) \
                if not _task(task_id)["family"].startswith("decoy-marker") \
                else md.render_true_candidate(_gt(task_id))
            assert ref, task_id

    @pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
    def test_self_check_cli_js_units(self, tmp_path):
        for task_id in ("m1-fileperm-v1", "m1-net403-v1", "m1-execperm-v1",
                        "m2-session-v1", "m2-request-v1", "m2-timer-v1",
                        "m3-sbox-js-v1", "m3-keystring-js-v1",
                        "m3-antidebug-js-v1"):
            proc = subprocess.run(
                [sys.executable, str(MD_SCRIPT), "--self-check", task_id],
                capture_output=True, text=True, timeout=300, cwd=str(ROOT))
            assert proc.returncode == 0, \
                f"{task_id}: {proc.stdout + proc.stderr}"
            assert "VERDICT PASS" in proc.stdout

    @pytest.mark.skipif(not GO_AVAILABLE, reason="go not available")
    def test_self_check_cli_go_unit(self):
        proc = subprocess.run(
            [sys.executable, str(MD_SCRIPT), "--self-check", "m3-sbox-go-v1"],
            capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "VERDICT PASS" in proc.stdout


# ------------------------------------------------- versioning & restraint
class TestVersioningAndRestraint:
    def test_tier_version_pair_pinned_on_both_consumers(self):
        assert ds.TIER_EVAL_VERSION["misdirection"] == "eval-v1.2"
        assert ds.EVAL_TIER_VERSION is ds.TIER_EVAL_VERSION
        assert "misdirection" in ds.TIERS
        assert "eval-v1.2" in ds.EVAL_VERSIONS

    def test_misdirection_ids_resolve_across_tiers(self):
        for task_id in ("m1-fileperm-v1", "m2-timer-v1", "m3-sbox-go-v1"):
            assert ds.resolve_task_dir(task_id).name == task_id

    def test_changelog_documents_the_misdirection_version(self):
        log = (ROOT / "eval" / "v1" / "CHANGELOG.md").read_text("utf-8")
        assert "eval-v1.2" in log
        assert "misdirection" in log

    def test_no_distillation_cadence_in_the_misdirection_module(self):
        """The restraint ruling is binding: transfer pairs ENABLE a later
        measurement; nothing here may add note/lesson/recall cadence."""
        source = MD_SCRIPT.read_text(encoding="utf-8")
        banned = ("lessons", "nursery", "recall_", "note_cadence",
                  "filter_distiller_sources", "distillate")
        for token in banned:
            assert token not in source, f"cadence-adjacent token: {token}"
