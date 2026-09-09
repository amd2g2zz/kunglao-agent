# -*- coding: utf-8 -*-
"""tests/test_difficulty_calibration_15.py — #15 sample difficulty calibration.

Difficulty is calibrated from SAMPLE-INTRINSIC observable factors only
(owner ruling): features composed from existing scanner outputs
(evidence/die.json from tools/static/die_probe.py, evidence/apkid.json from
scripts/apkid_scanner.py). Difficulty is an OPEN-LOOP INPUT for #16 — it must
be machine-readable and stable. Missing evidence defaults to easy + an
explicit evidence_gap factor (absence is never scored as MAX).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import difficulty_calibration as dc  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "difficulty_15"

# #16 consumption contract: these keys MUST exist in every calibrate() result.
REQUIRED_KEYS = {"schema", "tier", "score", "dominant_factor",
                 "factors", "families", "coverage", "notes"}


# ---------- fixture corpus helpers ----------

def _corpus() -> dict[str, dict]:
    """profile name -> {"die": {...}|None, "apkid": {...}|None}."""
    out: dict[str, dict] = {}
    for prof_dir in sorted(FIXTURES.iterdir()):
        if not prof_dir.is_dir():
            continue
        ev: dict = {"die": None, "apkid": None}
        for name in ("die", "apkid"):
            p = prof_dir / "evidence" / f"{name}.json"
            if p.is_file():
                ev[name] = json.loads(p.read_text(encoding="utf-8"))
        out[prof_dir.name] = ev
    return out


def _intended() -> dict[str, str]:
    import yaml
    manifest = yaml.safe_load(
        (FIXTURES / "corpus.yaml").read_text(encoding="utf-8"))
    return {row["profile"]: row["intended_tier"] for row in manifest["profiles"]}


def _evidence_by_profile(name: str) -> dict:
    return _corpus()[name]


# ---------- RED bar: endpoints + tier separation ----------

class TestTierSeparation:
    def test_easy_profiles(self):
        for name, tier in _intended().items():
            if tier != "easy":
                continue
            res = dc.calibrate(dc.features_from_evidence(_evidence_by_profile(name)))
            assert res["tier"] == "easy", (name, res)

    def test_max_profile(self):
        for name, tier in _intended().items():
            if tier != "max":
                continue
            res = dc.calibrate(dc.features_from_evidence(_evidence_by_profile(name)))
            assert res["tier"] == "max", (name, res)

    def test_medium_profiles(self):
        for name, tier in _intended().items():
            if tier != "medium":
                continue
            res = dc.calibrate(dc.features_from_evidence(_evidence_by_profile(name)))
            assert res["tier"] == "medium", (name, res)

    def test_hard_profiles(self):
        for name, tier in _intended().items():
            if tier != "hard":
                continue
            res = dc.calibrate(dc.features_from_evidence(_evidence_by_profile(name)))
            assert res["tier"] == "hard", (name, res)

    def test_corpus_experiment_green(self):
        """The 9-profile separation bar runs green as a test (plan PASS bar):
        the experiment harness exits 0 only when the fixture corpus separates
        (4-way preferred; easy/MAX endpoints mandatory, else fallback bar)."""
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "experiment_difficulty_15.py")],
            capture_output=True, text=True)
        assert proc.returncode == 0, (
            f"experiment failed:\n{proc.stdout}\n{proc.stderr}")


# ---------- evidence-gap contract (never guess MAX from absence) ----------

class TestEvidenceGap:
    def test_missing_evidence_defaults_easy_with_gap_factor(self):
        res = dc.calibrate(dc.features_from_evidence({"die": None, "apkid": None}))
        assert res["tier"] == "easy"
        assert "evidence_gap" in res["factors"]
        assert res["dominant_factor"] == "evidence_gap"
        assert res["coverage"] == {"die": False, "apkid": False}

    def test_gap_note_documented_not_crash(self):
        res = dc.calibrate(dc.features_from_evidence({}))
        assert res["score"] == 0.0
        assert any("gap" in k for k in res["factors"])

    def test_apkid_unavailable_status_is_absent_plus_note(self):
        """status:unavailable (tool missing) = source absent, gap noted."""
        ev = {"die": None, "apkid": {"status": "unavailable", "reason": "not on PATH"}}
        res = dc.calibrate(dc.features_from_evidence(ev))
        assert res["coverage"]["apkid"] is False
        assert res["tier"] == "easy"
        assert "apkid" in json.dumps(res["factors"]["evidence_gap"])

    def test_apkid_error_status_is_absent(self):
        ev = {"die": None, "apkid": {"status": "error", "reason": "boom"}}
        res = dc.calibrate(dc.features_from_evidence(ev))
        assert res["coverage"]["apkid"] is False


# ---------- partial evidence (documented subset scoring) ----------

class TestPartialEvidence:
    def test_die_only_scores_from_available_subset(self):
        ev = {"die": _evidence_by_profile("go_stripped_medium")["die"],
              "apkid": None}
        res = dc.calibrate(dc.features_from_evidence(ev))
        assert res["coverage"] == {"die": True, "apkid": False}
        assert res["tier"] == "medium"
        # partial coverage is documented in notes, not silently scored
        assert any("apkid" in n for n in res["notes"])

    def test_apkid_only_never_invents_die_features(self):
        ev = {"die": None,
              "apkid": _evidence_by_profile("android_max_hardened")["apkid"]}
        res = dc.calibrate(dc.features_from_evidence(ev))
        assert res["coverage"] == {"die": False, "apkid": True}
        for factor, payload in res["factors"].items():
            if factor == "evidence_gap":
                continue
            assert payload["source"].startswith("apkid"), (factor, payload)

    def test_missing_die_sections_robust(self):
        """die present but section_table empty -> no crash, entropy feature 0."""
        die = {"derived": {"language": "C/C++", "detected_packer": None,
                           "section_table": [], "high_entropy_sections": []},
               "resources": {"VERSION_INFO": {"ProductName": "x"}}}
        res = dc.calibrate(dc.features_from_evidence({"die": die, "apkid": None}))
        assert res["tier"] in ("easy", "medium", "hard", "max")


# ---------- output schema stability (#16 consumption contract) ----------

class TestSchemaStability:
    def test_calibrate_result_keys(self):
        for name, ev in _corpus().items():
            res = dc.calibrate(dc.features_from_evidence(ev))
            assert REQUIRED_KEYS <= set(res), (name, sorted(res))
        res = dc.calibrate(dc.features_from_evidence({"die": None, "apkid": None}))
        assert REQUIRED_KEYS <= set(res)

    def test_factor_payload_shape(self):
        ev = _evidence_by_profile("android_max_hardened")
        res = dc.calibrate(dc.features_from_evidence(ev))
        for factor, payload in res["factors"].items():
            if factor == "evidence_gap":
                continue
            assert {"score", "weight", "contribution", "source"} <= set(payload), factor

    def test_schema_version_string(self):
        res = dc.calibrate(dc.features_from_evidence({"die": None, "apkid": None}))
        assert res["schema"] == "difficulty-calibration/1"


# ---------- pure-function determinism ----------

class TestDeterminism:
    def test_same_evidence_same_result_twice(self):
        for name, ev in _corpus().items():
            a = dc.calibrate(dc.features_from_evidence(ev))
            b = dc.calibrate(dc.features_from_evidence(ev))
            assert a == b, name

    def test_no_timestamp_in_pure_core(self):
        import re
        ev = _evidence_by_profile("android_max_hardened")
        text = json.dumps(dc.calibrate(dc.features_from_evidence(ev)))
        assert not re.search(r"generated_at|scanned_at|20\d\d-", text)


# ---------- CLI end-to-end ----------

class TestCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "difficulty_calibration.py"),
             *args], capture_output=True, text=True, env=None)

    def test_end_to_end_json_schema(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "evidence").mkdir(parents=True)
        ev = _evidence_by_profile("android_max_hardened")
        for name in ("die", "apkid"):
            if ev.get(name):
                (ws / "evidence" / f"{name}.json").write_text(
                    json.dumps(ev[name]), encoding="utf-8")
        p = self._run(str(ws), "--json")
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)
        assert REQUIRED_KEYS <= set(out)
        assert out["tier"] == "max"
        # evidence/difficulty.json written + same tier
        written = json.loads((ws / "evidence" / "difficulty.json").read_text())
        assert written["tier"] == "max"

    def test_cli_missing_evidence_easy_not_crash(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        p = self._run(str(ws), "--json")
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)
        assert out["tier"] == "easy"
        assert "evidence_gap" in out["factors"]

    def test_cli_mount_merges_into_task_spec(self, tmp_path):
        import yaml
        ws = tmp_path / "ws"
        (ws / "evidence").mkdir(parents=True)
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump({"constraints": {"dynamic_re": "allowed"}}),
            encoding="utf-8")
        p = self._run(str(ws), "--mount")
        assert p.returncode == 0, p.stderr
        spec = yaml.safe_load((ws / "task_spec.yaml").read_text())
        assert spec["constraints"] == {"dynamic_re": "allowed"}  # user keys kept
        assert spec["difficulty"]["tier"] in ("easy", "medium", "hard", "max")

    def test_cli_mount_without_task_spec_is_nonfatal(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        p = self._run(str(ws), "--mount", "--json")
        assert p.returncode == 0, p.stderr

    def test_cli_accepts_evidence_dir_directly(self, tmp_path):
        ev_dir = tmp_path / "evidence"
        ev_dir.mkdir()
        ev = _evidence_by_profile("upx_windows_tool")
        (ev_dir / "die.json").write_text(json.dumps(ev["die"]), encoding="utf-8")
        p = self._run(str(ev_dir), "--json")
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout)["tier"] == "hard"
