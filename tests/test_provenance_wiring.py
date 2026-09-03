# -*- coding: utf-8 -*-
"""Contract: the PROVEN migration path (kunglao_record.claim_migrator) MUST
call provenance_gate.check_provenance_gate — the research replay showed the
checker exists but is not on the mandatory path (summary-only promotion)."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import kunglao_record


def _write_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    facts = ws / "facts"
    evidence = ws / "evidence"
    facts.mkdir(parents=True)
    evidence.mkdir()
    (facts / "_INDEX.md").write_text(
        "F001 | PROVEN | C-001 | verified conclusion\n", encoding="utf-8"
    )
    (evidence / "cap.txt").write_text("captured evidence", encoding="utf-8")
    (evidence / "_index.json").write_text(
        '{"entries": [{"eid": "E001", "path": "evidence/cap.txt", '
        '"sha256": "SENTINEL_WRONG"}], "schema": "evidence-index/1"}',
        encoding="utf-8",
    )
    fact_text = (
        "---\n"
        "claim_id: C-001\n"
        "---\n"
        "conclusion verified\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: kunglao-redteam-w2\n"
        "  refute_attempt: tried to break; held\n"
        "  sign_off_at: 2026-08-13T00:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n\n"
        "```yaml\n"
        "provenance:\n"
        "  - eid: E001\n"
        "```\n"
    )
    (facts / "F001.md").write_text(fact_text, encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [{"id": "C-001", "status": "OPEN", "worker_id": "w1"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return ws


def test_promotion_blocked_when_provenance_hash_mismatches(tmp_path):
    """Summary-only / hash-drifted provenance must NOT reach PROVEN through
    the formal migration entry point."""
    ws = _write_ws(tmp_path)
    ok, msg = kunglao_record.claim_migrator(ws, "C-001", "PROVEN", "orchestrator")
    assert not ok, f"expected rejection, got: {msg}"
    assert "PROVENANCE" in msg.upper()

    register = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    status = register["claims"][0]["status"]
    assert status != "PROVEN", "summary-only provenance must not reach PROVEN"
