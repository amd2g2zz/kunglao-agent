"""Deliverable references do not prove that a fact contributed to an answer."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rlvr import scalar  # noqa: E402

EXCERPT = "The loader resolves the imported function by hashing its name."


def _fixture(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir()
    (ws / "runs" / "deliverable-use").mkdir(parents=True)
    fact = ws / "facts" / "F001.md"
    fact.write_text("---\nid: F001-test\nstatus: PROVEN\ncreator: maker\n---\n" + EXCERPT + "\n")
    deliverable = ws / "notes" / "answer.md"
    return ws, fact, deliverable


def _attest(ws, fact, deliverable, verifier="checker"):
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    record = {"schema": "deliverable-use/1", "fact_id": "F001-test",
              "fact_sha256": digest(fact), "deliverable": deliverable.relative_to(ws).as_posix(),
              "deliverable_sha256": digest(deliverable), "excerpt": EXCERPT,
              "verifier_id": verifier, "verdict": "used",
              "reason": "The answer includes this finding as its conclusion."}
    (ws / "runs" / "deliverable-use" / "1.json").write_text(json.dumps(record))


def test_mention_alone_does_not_award_credit_and_attested_use_does(tmp_path):
    ws, fact, deliverable = _fixture(tmp_path)
    dispatch = [{"dispatch_id": "maker", "round": 1}]
    def credit():
        return scalar.round_credit(dispatch, scalar.fact_artifacts(ws), [])['rows'][0]['r']
    baseline = credit()
    deliverable.write_text("F001 was listed but not used. F001\n")
    mentioned = credit()
    deliverable = ws / "runs" / "deliverables" / "answer.md"
    deliverable.parent.mkdir(exist_ok=True)
    deliverable.write_text(EXCERPT + "\n")
    _attest(ws, fact, deliverable)
    used = credit()
    assert (baseline, mentioned, used) == (0.01, 0.01, 1.0)


def test_attestation_rejects_self_certification_and_stale_deliverable(tmp_path):
    ws, fact, deliverable = _fixture(tmp_path)
    deliverable.write_text(EXCERPT)
    _attest(ws, fact, deliverable, verifier="maker")
    self_signed = scalar.fact_artifacts(ws)[0]
    _attest(ws, fact, deliverable)
    deliverable.write_text(EXCERPT + " changed")
    stale = scalar.fact_artifacts(ws)[0]
    assert not self_signed.get("verified_deliverable_use")
    assert not stale.get("verified_deliverable_use")


def test_late_use_amends_original_producer_mass_and_replay_is_idempotent(tmp_path):
    from _dispatch_fixture import mint_one
    from rlvr import q_cells, ledger

    ws, fact, deliverable = _fixture(tmp_path)
    claim = {"id": "C-1", "status": "PROVEN", "answers_question": None}
    did = mint_one(ws, claim, agent="maker")
    fact.write_text(f"---\nid: F001-test\nstatus: PROVEN\ncreator: {did}\ncreated_by_dispatch: {did}\nclaim_id: C-1\n---\n{EXCERPT}\n")
    dispatch = [{"dispatch_id": did, "round": 1}]
    def settle():
        return scalar.settle_round_credit(ws, dispatch, scalar.fact_artifacts(ws), [], now="2026-01-01T00:00:00Z")
    settle()
    initial = q_cells.banked_mass(ws, did)
    dispatch_row = next(row for row in q_cells.JSONLQStore(ws).observations() if row.get("source") == "dispatch")
    def posterior():
        view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
        return q_cells.cell_posterior(view, dispatch_row["signature_hash"], "static_recovery", arm_key=dispatch_row["arm_key"])
    initial_posterior = posterior()
    deliverable.write_text("F001 was listed but not used. F001\n")
    settle()
    mentioned = q_cells.banked_mass(ws, did)
    mentioned_posterior = posterior()
    deliverable = ws / "runs" / "deliverables" / "answer.md"
    deliverable.parent.mkdir(exist_ok=True)
    deliverable.write_text(EXCERPT + "\n")
    _attest(ws, fact, deliverable)
    settle()
    used = q_cells.banked_mass(ws, did)
    used_posterior = posterior()
    settle()
    replayed = q_cells.banked_mass(ws, did)
    settlement = ledger.fold(ws, "round_credit/" + did)["settlement"]
    assert initial[:2] == mentioned[:2] == (0.0, 0.0)
    assert used[:2] == replayed[:2] == (1.0, 0.0)
    assert settlement["credited"] == ["F001-test"]
    assert settlement["late_cited"] == ["F001-test"]
    assert initial_posterior == mentioned_posterior == (1.0, 1.0)
    assert used_posterior == (2.0, 1.0)


def test_mentioned_fact_records_unknown_use_without_changing_credit(tmp_path):
    from rlvr import ledger

    ws, fact, deliverable = _fixture(tmp_path)
    dispatch = [{"dispatch_id": "maker", "round": 1}]
    deliverable.write_text("F001 was mentioned but not used.\n")
    scalar.settle_round_credit(ws, dispatch, scalar.fact_artifacts(ws), [], now="2026-01-01T00:00:00Z")
    settlement = ledger.fold(ws, "round_credit/maker")["settlement"]
    assert settlement["deliverable_references"] == [{"id": "F001-test", "use": "unknown",
        "sources": [{"path": "notes/answer.md", "sha256": hashlib.sha256(deliverable.read_bytes()).hexdigest()}]}]
    assert settlement["reward"] == 0.01


def test_production_settlement_records_incidental_mention_without_mass(tmp_path):
    from _dispatch_fixture import mint_one
    import claims_store
    import settle_round_credit
    from rlvr import ledger, q_cells

    ws, fact, deliverable = _fixture(tmp_path)
    claim = {"id": "C-1", "status": "PROVEN", "answers_question": None}
    did = mint_one(ws, claim, agent="maker")
    assert claims_store.confirm_dispatch(ws, "C-1")
    fact.write_text(f"---\nid: F001-test\nstatus: PROVEN\ncreator: C-1\ncreated_by_dispatch: {did}\nclaim_id: C-1\n---\n{EXCERPT}\n")
    before = settle_round_credit.run(ws)
    initial = q_cells.banked_mass(ws, did)
    deliverable.write_text("F001 was mentioned but not used.\n")
    after = settle_round_credit.run(ws)
    mentioned = q_cells.banked_mass(ws, did)
    settlement = ledger.fold(ws, "round_credit/C-1")["settlement"]

    assert before.get("rounds") == after.get("rounds") == 1
    assert initial[:2] == mentioned[:2] == (0.0, 0.0)
    assert settlement["deliverable_references"] == [{"id": "F001-test", "use": "unknown",
        "sources": [{"path": "notes/answer.md", "sha256": hashlib.sha256(deliverable.read_bytes()).hexdigest()}]}]
    output = ws / "runs" / "deliverables" / "answer.md"
    output.parent.mkdir(exist_ok=True)
    output.write_text(EXCERPT + "\n")
    _attest(ws, fact, output)
    settle_round_credit.run(ws)
    used = q_cells.banked_mass(ws, did)
    settle_round_credit.run(ws)
    replayed = q_cells.banked_mass(ws, did)
    final = ledger.fold(ws, "round_credit/C-1")["settlement"]
    assert used[:2] == replayed[:2] == (1.0, 0.0)
    assert final["late_cited"] == ["F001-test"]


def test_abandoned_matching_draft_cannot_credit_duplicate_facts(tmp_path):
    ws, fact, _ = _fixture(tmp_path)
    other = ws / "facts" / "F002.md"
    other.write_text("---\nid: F002-test\nstatus: PROVEN\ncreator: maker\n---\n" + EXCERPT + "\n")
    output = ws / "runs" / "deliverables"
    output.mkdir()
    (output / "draft.md").write_text(EXCERPT)
    (output / "answer.md").write_text("The draft is incorrect and was not used.")
    rows = scalar.fact_artifacts(ws)
    credit = scalar.round_credit([{"dispatch_id": "maker", "round": 1}], rows, [])

    assert credit["rows"][0]["r"] == 0.01
    assert not any(row["verified_deliverable_use"] for row in rows)


def test_use_evidence_receipt_binds_record_and_files_even_without_id_in_answer(tmp_path):
    from rlvr import ledger

    ws, fact, _ = _fixture(tmp_path)
    output = ws / "runs" / "deliverables" / "answer.md"
    output.parent.mkdir()
    output.write_text(EXCERPT)
    _attest(ws, fact, output)
    scalar.settle_round_credit(ws, [{"dispatch_id": "maker", "round": 1}],
                               scalar.fact_artifacts(ws), [], now="2026-01-01T00:00:00Z")

    entry, = ledger.fold(ws, "round_credit/maker")["settlement"]["deliverable_use_evidence"]
    assert entry["id"] == "F001-test"
    assert entry["deliverable"] == "runs/deliverables/answer.md"
    assert entry["record_sha256"] == hashlib.sha256((ws / entry["record"]).read_bytes()).hexdigest()
    assert entry["fact_sha256"] == hashlib.sha256(fact.read_bytes()).hexdigest()


def test_external_fact_and_cyclic_attestation_directory_are_ignored(tmp_path):
    ws, fact, _ = _fixture(tmp_path)
    external = tmp_path / "outside.md"
    external.write_bytes(fact.read_bytes())
    fact.unlink()
    fact.symlink_to(external)
    rows = scalar.fact_artifacts(ws)
    assert rows == []
    fact.unlink()
    fact.write_text("---\nid: F001-test\nstatus: PROVEN\ncreator: maker\n---\n" + EXCERPT)
    records = ws / "runs" / "deliverable-use"
    records.rmdir()
    records.symlink_to(records)
    assert scalar.fact_artifacts(ws)[0]["verified_deliverable_use"] is False


def test_deployed_delivery_skill_provides_schema_and_executable_settlement(tmp_path):
    import os
    import subprocess
    import hook_activation

    ws = tmp_path / "deployed"
    ws.mkdir()
    hook_activation.deploy_workspace_copy(ws)
    skill = ws / ".claude" / "skills" / "kunglao-agent" / "skills" / "kunglao-agent" / "SKILL.md"
    script = ws / ".claude" / "scripts" / "settle_round_credit.py"

    text = skill.read_text(encoding="utf-8")
    process = subprocess.run([sys.executable, str(script), "--help"],
                             cwd=ws, env=dict(os.environ), capture_output=True,
                             text=True, timeout=30)

    assert all(field in text for field in ("deliverable-use/1", "fact_sha256",
                                           "deliverable_sha256", "verifier_id"))
    assert process.returncode == 0, process.stderr
