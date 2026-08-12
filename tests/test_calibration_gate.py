"""Calibration gate (#204): every delivered claim MUST carry confidence +
falsifier. A claim without them is incomplete — never silently wrong."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import calibration_gate


def _claim(**overrides) -> dict:
    base = {
        "id": "C-001",
        "status": "PROVEN",
        "confidence": 0.8,
        "falsifier": "re-running strings on a clean capture shows the strings",
    }
    base.update(overrides)
    return base


def test_claim_with_confidence_and_falsifier_passes():
    ok, reason = calibration_gate.check_claim(_claim())
    assert ok, reason


def test_claim_missing_confidence_fails():
    ok, reason = calibration_gate.check_claim(_claim(confidence=None))
    assert not ok
    assert "confidence" in reason


def test_claim_missing_falsifier_fails():
    ok, reason = calibration_gate.check_claim(_claim(falsifier=None))
    assert not ok
    assert "falsifier" in reason
