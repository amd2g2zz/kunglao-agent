"""Template contracts for the completion transaction (issue #201).

The delivery gate (#204) needs task_spec to declare calibration, and the
second-stop persistent adjudication (#199/#200) needs a standard
task-oracle shape. These tests pin the TEMPLATES so the contract cannot
drift from the enforcing code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_task_spec_template_declares_calibration_requirement():
    """Batch 1 acceptance: task_spec template must declare calibration
    (confidence + falsifier) so the delivery gate can enforce it."""
    import yaml

    text = (ROOT / "templates/task_spec.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    cal = data.get("calibration", {})
    assert cal.get("require_confidence", False) is True
    assert cal.get("require_falsifier", False) is True


def test_task_oracle_template_has_persistent_adjudication():
    """Task oracle template must carry the persistent adjudication fields
    (second-stop anti-loop lives here, not in the shim)."""
    import yaml

    data = yaml.safe_load((ROOT / "templates/task-oracle.yaml").read_text(encoding="utf-8"))
    adj = data.get("adjudication", {})
    assert "stop_hook_active" in adj
    assert "second_stop" in adj.get("stop_hook_active", {})
