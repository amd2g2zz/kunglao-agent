# -*- coding: utf-8 -*-
"""DiscoveryEmitted → ObligationCreated: fact bodies that disclose
un-analyzed payloads / shellcode / next-stage URLs must create child
obligations (research replay #1), and decide() must refuse CONVERGED
while any disclosure is unconsumed."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import obligation_discovery


def _write_fact(facts_dir: Path, fact_id: str, body: str) -> None:
    (facts_dir / f"{fact_id}.md").write_text(body, encoding="utf-8")


def test_shellcode_disclosure_creates_obligation(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    _write_fact(
        ws / "facts", "F001",
        "Evidence says embedded shellcode exists.\n"
        "Next question: extract and analyze the payload.\n",
    )
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    obs = obligation_discovery.scan_discoveries(ws / "facts", ws / "claim-register.yaml")
    assert len(obs) == 1
    assert obs[0]["type"] == "shellcode"
    assert "F001" in obs[0]["trigger"]
    assert obs[0]["obligation_template"] == "payload-analysis"


def test_no_disclosure_no_obligation(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    _write_fact(ws / "facts", "F002", "Static strings are benign.\n")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    assert obligation_discovery.scan_discoveries(ws / "facts", ws / "claim-register.yaml") == []


def test_decide_downgrades_when_disclosures_unconsumed(tmp_path):
    """A workspace whose facts disclose un-analyzed payloads must NOT
    reach CONVERGED (research replay #1)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import convergence_check

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\nF001 | PROVEN | C-001 | embedded shellcode discovered; "
        "downstream payload analysis not performed\n", encoding="utf-8")
    (ws / "facts" / "F001.md").write_text(
        "Evidence says embedded shellcode exists.\n"
        "Next question: extract and analyze the payload.\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [{"id": "C-001", "status": "PROVEN",
                          "answers_question": "q1"}]}, sort_keys=False),
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: What behavior was found?\n"
        "    need: yes_no_with_evidence\n", encoding="utf-8")

    d = convergence_check.decide(ws)
    assert d["decision"] != "CONVERGED", d
    assert "obligation" in (d.get("action") or "").lower()
