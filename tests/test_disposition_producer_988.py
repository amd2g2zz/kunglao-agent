# -*- coding: utf-8 -*-
"""tests/test_disposition_producer_988.py — the runtime disposition
producer (issue-988).

The algebra and both consumers were landed by the projection cards; the
WRITER was missing, so ``settle_mission``'s disposition-signal face
settled zero on every mission. This file pins the producer's assembly:
one ``disposition/1`` row per terminal claim, evidence from the faces the
workspace already carries, never a hand-built verdict (the classifier
owns the disposition), and never a silent "authorized".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(SCRIPTS), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import disposition  # noqa: E402
import rlvr.disposition_producer as disposition_producer  # noqa: E402
from rlvr import route_ledger  # noqa: E402

TS = "2026-11-06T00:00:00Z"


def _spec(ws: Path, *, targets=("target.example",), extra: str = "") -> None:
    auth = ("authorization:\n"
            f"  targets: {list(targets)!r}\n"
            "  excluded: []\n"
            "  authorization_ref: ticket-988\n")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq1\n  q: what is the loader?\n"
        + auth + extra, encoding="utf-8")


def _ws(tmp_path: Path, *, status: str = "REFUTED", claim: str = "C-001",
        targets=("target.example",), authorization: bool = True) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": claim, "status": status}]}),
        encoding="utf-8")
    if authorization:
        _spec(ws, targets=targets)
    else:
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n- id: pq1\n  q: what is the loader?\n",
            encoding="utf-8")
    return ws


def _rows(ws: Path) -> list[dict]:
    base = ws / disposition.DISPOSITION_DIR
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(base.glob("*.json"))] if base.is_dir() else []


def _transition(ws: Path, claim: str, *, status: str,
                action_type: str = "dispatch") -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    row = {"schema": "transition/1", "ts": TS, "dispatch_id": claim,
           "action_type": action_type, "claim_ref": claim,
           "o": {"status": status}}
    with (ws / "runs" / "experience.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_out_of_scope_when_the_scope_authorizes_nothing(tmp_path) -> None:
    ws = _ws(tmp_path, targets=())
    out = disposition_producer.produce(ws)
    assert out["written"] == 1
    assert _rows(ws)[0]["disposition"] == "OUT_OF_SCOPE"


def test_a_proven_claim_is_solved(tmp_path) -> None:
    ws = _ws(tmp_path, status="PROVEN")
    (ws / "runs" / "verification-C-001.md").write_text(
        "verdict: verified\n", encoding="utf-8")
    disposition_producer.produce(ws)
    row = _rows(ws)[0]
    assert row["disposition"] == "SOLVED" and row["gate"] == "oracle_pass"
    assert row["evidence_refs"] == ["runs/verification-C-001.md"]


def test_in_scope_unfinished_is_surrender(tmp_path) -> None:
    ws = _ws(tmp_path)
    disposition_producer.produce(ws)
    assert _rows(ws)[0]["disposition"] == "SURRENDER"


def test_a_blocked_act_is_infra(tmp_path) -> None:
    ws = _ws(tmp_path)
    _transition(ws, "C-001", status="blocked")
    disposition_producer.produce(ws)
    assert _rows(ws)[0]["disposition"] == "INFRA"


def test_a_covered_route_ledger_is_attempted_exhausted(tmp_path) -> None:
    ws = _ws(tmp_path)
    artifact = ws / "runs" / "rt-tests" / "C-001" / "attempt-1.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"MZ\n")
    route_ledger.record_attempt(
        ws, claim="C-001", claim_kind="static_constant",
        route="disasm_constant_check",
        command="file runs/rt-tests/C-001/attempt-1.txt",
        artifact="runs/rt-tests/C-001/attempt-1.txt")
    disposition_producer.produce(ws)
    assert _rows(ws)[0]["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert _rows(ws)[0]["route_ledger_ref"].endswith("routes.json")


def test_a_corroborated_wall_is_censored_env(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "task_spec.yaml").write_text(
        "sample_sha256: " + "a" * 64 + "\n"
        "authorization:\n  targets: ['target.example']\n"
        "  excluded: []\n  authorization_ref: ticket-988\n",
        encoding="utf-8")
    (ws / "blockers").mkdir()
    (ws / "blockers" / "missing.md").write_text(
        "sample-missing: the sample vanished for C-001\n", encoding="utf-8")
    disposition_producer.produce(ws)
    row = _rows(ws)[0]
    assert row["disposition"] == "CENSORED_ENV"
    assert row["gate"] == "wall"


def test_no_authorization_context_writes_nothing(tmp_path) -> None:
    ws = _ws(tmp_path, authorization=False)
    out = disposition_producer.produce(ws)
    assert out["written"] == 0
    assert out["skipped"] == ["C-001"]
    assert _rows(ws) == []


def test_reproducing_is_idempotent(tmp_path) -> None:
    ws = _ws(tmp_path)
    disposition_producer.produce(ws)
    before = (ws / disposition.DISPOSITION_DIR / "C-001.json").read_bytes()
    disposition_producer.produce(ws)
    after = (ws / disposition.DISPOSITION_DIR / "C-001.json").read_bytes()
    assert before == after, "a re-settle must rebuild the identical row"


def test_non_terminal_claims_are_skipped(tmp_path) -> None:
    ws = _ws(tmp_path, status="IN_PROGRESS")
    out = disposition_producer.produce(ws)
    assert out["written"] == 0 and out["skipped"] == ["C-001"]
    assert _rows(ws) == []


def test_proven_without_verification_is_unverified_completion(tmp_path) -> None:
    """A PROVEN status without its verification artifact is a CLAIM, not
    a pass — the algebra's anti-self-certification gate."""
    ws = _ws(tmp_path, status="PROVEN")
    disposition_producer.produce(ws)
    row = _rows(ws)[0]
    assert row["disposition"] == "FAILED"
    assert row["gate"] == "unverified_completion"


def test_a_refuted_verification_never_passes(tmp_path) -> None:
    """Existence is not a pass: the row resolves the canonical surface
    through verifier_integrity, and a ``verdict: refuted`` record is a
    refusal even under a PROVEN register status."""
    ws = _ws(tmp_path, status="PROVEN")
    (ws / "runs" / "verification-C-001.md").write_text(
        "verdict: refuted\n", encoding="utf-8")
    disposition_producer.produce(ws)
    assert _rows(ws)[0]["disposition"] == "FAILED"
    assert _rows(ws)[0]["gate"] == "unverified_completion"


def test_the_mission_trust_mirror_is_not_a_pass(tmp_path) -> None:
    """episode_settle projects the register stamp onto the canonical
    surface; a projection is not evidence (the mirror's own marker)."""
    ws = _ws(tmp_path, status="PROVEN")
    (ws / "runs" / "verification-C-001.md").write_text(
        "# mission-terminal trust mirror (rlvr.episode_settle).\n"
        "verdict: verified\nclaim: C-001\n", encoding="utf-8")
    disposition_producer.produce(ws)
    assert _rows(ws)[0]["disposition"] == "FAILED"


def test_an_ambiguous_multi_target_scope_writes_nothing(tmp_path) -> None:
    """Several declared targets leave the episode target ambiguous: a
    scope verdict minted from targets[0] would be evidence-free."""
    ws = _ws(tmp_path, targets=("t1", "t2"))
    out = disposition_producer.produce(ws)
    assert out["written"] == 0
    assert out["skipped"] == ["C-001"]
    assert _rows(ws) == []


def _pass_surface(ws: Path, kind: str) -> str:
    """Write a PASS on one of the claim's four canonical surfaces."""
    if kind == "verification":
        rel = "runs/verification-C-001.md"
        (ws / rel).write_text("verdict: verified\n", encoding="utf-8")
    elif kind == "verify-note":
        rel = "runs/C-001-verify-note.md"
        (ws / rel).write_text("verdict: verified\n", encoding="utf-8")
    elif kind == "redteam":
        rel = "runs/verify-redteam-C-001.md"
        (ws / rel).write_text("verdict: verified\n", encoding="utf-8")
    else:  # the scorer's conclusion face
        rel = "evidence/verdict.json"
        (ws / "evidence").mkdir(exist_ok=True)
        (ws / rel).write_text(json.dumps(
            {"claims": [{"id": "C-001", "verdict": "verified"}]}),
            encoding="utf-8")
    return rel


@pytest.mark.parametrize("kind", ["verification", "verify-note", "redteam",
                                  "verdict-json"])
def test_every_canonical_pass_surface_is_cited(tmp_path, kind) -> None:
    """The resolver picks whichever canonical surface passed; the row
    must cite THAT record (a red-team-only pass wrote no row before)."""
    ws = _ws(tmp_path, status="PROVEN")
    surface = _pass_surface(ws, kind)
    disposition_producer.produce(ws)
    row = _rows(ws)[0]
    assert row["disposition"] == "SOLVED", (kind, row)
    assert row["evidence_refs"] == [surface]


def test_settle_mission_produces_and_settles_the_signal(tmp_path) -> None:
    """The acceptance: settle_mission writes the row and the existing
    choice-signal face settles it in the same call."""
    from rlvr import episode_settle
    ws = _ws(tmp_path, status="PROVEN")
    (ws / "runs" / "verification-C-001.md").write_text(
        "verdict: verified\n", encoding="utf-8")
    out = episode_settle.settle_mission(ws)
    assert _rows(ws), "the producer wrote no disposition row"
    assert out["disposition_signals"] == 1
