# -*- coding: utf-8 -*-
"""Tests for the replay-equivalence oracle (see scripts/replay_equivalence.py
for the artifact schema and the enforced faces)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import replay_equivalence as req  # noqa: E402


# ------------------------------------------------------------- fixtures

def _pair(pid: str, inputs: dict, ref: str, repro: str | None = None,
          equal: bool = True, **extra) -> dict:
    p = {"input_id": pid, "inputs": inputs, "ref_output": ref,
         "repro_output": repro if repro is not None else ref,
         "byte_equal": equal}
    p.update(extra)
    return p


def _artifact(**over) -> dict:
    """A VALID artifact: 3 declared variables, 4 pairs — the classic 2^3
    pairwise covering array (4 rows, NOT the 8 exhaustive rows). Proves the
    check is coverage-driven, not count-driven."""
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": ["cap-01", "cap-02", "cap-03", "cap-04",
                            "cap-07"],
        "variables": {"timestamp": ["t0", "t1"],
                      "nonce": [0, 1],
                      "param": ["x", "y"]},
        "pairs": [
            _pair("cap-01", {"timestamp": "t0", "nonce": 0, "param": "x"},
                  "out-000"),
            _pair("cap-02", {"timestamp": "t0", "nonce": 1, "param": "y"},
                  "out-001"),
            _pair("cap-03", {"timestamp": "t1", "nonce": 0, "param": "y"},
                  "out-101"),
            _pair("cap-04", {"timestamp": "t1", "nonce": 1, "param": "x"},
                  "out-110"),
        ],
    }
    doc.update(over)
    return doc


def _write_artifact(ws: Path, doc: dict | None = None,
                    name: str = "replay-C-1.json") -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    p = ws / name
    p.write_text(json.dumps(doc or _artifact(), ensure_ascii=False,
                            indent=2) + "\n", encoding="utf-8")
    return p


# ======================== controlled variables ==========================

class TestArtifactSchemaAndCoverage:
    def test_valid_pairwise_artifact_has_no_errors(self):
        # 4 rows cover all 2-way combos of 2^3 — but not the 8 exhaustive
        # combos: a row-count or exhaustiveness rule would refuse real
        # covering arrays (NIST ACTS class output).
        assert req.artifact_errors(_artifact()) == []

    def test_dropped_row_names_missing_combos(self):
        doc = _artifact()
        doc["pairs"] = doc["pairs"][:3]  # drop (t1, nonce=1, param=x)
        errors = req.artifact_errors(doc)
        assert errors, "a coverage hole must be refused"
        joined = " ".join(errors)
        assert "timestamp" in joined and "nonce" in joined

    def test_strength_defaults_to_two(self):
        doc = _artifact()
        doc.pop("strength", None)
        assert req.artifact_errors(doc) == [], "t defaults to 2"

    def test_pair_value_outside_declared_domain_refused(self):
        doc = _artifact()
        doc["pairs"][0]["inputs"]["timestamp"] = "t9"  # not in [t0, t1]
        errors = req.artifact_errors(doc)
        assert any("t9" in e for e in errors)

    def test_pair_invented_variable_refused(self):
        doc = _artifact()
        doc["pairs"][0]["inputs"]["weather"] = "sunny"  # undeclared variable
        assert req.artifact_errors(doc), "undeclared variables are refused"

    def test_duplicate_input_id_refused(self):
        doc = _artifact()
        doc["pairs"][1]["input_id"] = "cap-01"
        assert any("cap-01" in e for e in req.artifact_errors(doc))

    def test_input_id_must_be_a_captured_input(self):
        """inputs are the CAPTURED reference-side inputs, never invented —
        every pair's input_id must be declared in captured_inputs."""
        doc = _artifact()
        doc["pairs"][0]["input_id"] = "cap-99"
        errors = req.artifact_errors(doc)
        assert any("cap-99" in e and "captured" in e for e in errors), errors

    def test_recorded_byte_equal_flag_is_not_trusted(self):
        """byte_equal: true with actually-differing outputs is a fabricated
        flag — the oracle recomputes the byte compare and refuses."""
        doc = _artifact()
        doc["pairs"][0]["repro_output"] = "out-000-PERTURBED"
        errors = req.artifact_errors(doc)
        assert any("byte_equal" in e for e in errors), errors

    def test_corrupt_artifact_raises_loud(self, tmp_path):
        p = tmp_path / "replay-C-1.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(req.ReplayEquivalenceError):
            req.load_artifacts(tmp_path)


class TestDivergenceEscalation:
    def test_prior_divergence_requires_strength_three(self):
        doc = _artifact(prior_divergence=True)
        errors = req.artifact_errors(doc)
        assert any("strength" in e for e in errors), errors
        # t=3 over 2^3 = exhaustive 8 rows
        domains = {"timestamp": ["t0", "t1"], "nonce": [0, 1],
                   "param": ["x", "y"]}
        rows = [{"timestamp": t, "nonce": n, "param": p}
                for t in ("t0", "t1") for n in (0, 1) for p in ("x", "y")]
        doc["strength"] = 3
        doc["captured_inputs"] = [f"cap-{i:02d}" for i in range(1, 9)]
        doc["pairs"] = [_pair(f"cap-{i + 1:02d}", r, f"out-{i}")
                        for i, r in enumerate(rows)]
        assert req.artifact_errors(doc) == []


class TestWithheldInputs:
    def test_withheld_combo_exempt_from_coverage(self):
        doc = _artifact()
        doc["pairs"] = doc["pairs"][:3]  # hole: (t1, nonce=1, param=x)
        doc["withheld_inputs"] = [{"input_id": "cap-07",
                                   "combos": [{"timestamp": "t1",
                                               "nonce": 1, "param": "x"}]}]
        assert req.artifact_errors(doc) == [], req.artifact_errors(doc)

    def test_withheld_input_must_not_appear_in_pairs(self):
        doc = _artifact()
        doc["withheld_inputs"] = [{"input_id": "cap-07", "combos": []}]
        doc["pairs"][0]["input_id"] = "cap-07"
        errors = req.artifact_errors(doc)
        assert any("cap-07" in e for e in errors)

    def test_withholding_cannot_erase_everything(self):
        """A zero-pair artifact is refused even when withholding is declared."""
        doc = _artifact(pairs=[])
        doc["withheld_inputs"] = [{"input_id": "cap-07",
                                   "combos": [{"timestamp": "t0"}]}]
        errors = req.artifact_errors(doc)
        assert any("pair" in e.lower() for e in errors)


class TestLoadAndMatchedFace:
    def test_load_artifacts_filters_by_claim(self, tmp_path):
        _write_artifact(tmp_path, _artifact(), "replay-C-1.json")
        _write_artifact(tmp_path, _artifact(claim_id="C-2"),
                        "replay-C-2.json")
        docs = req.load_artifacts(tmp_path, claim_id="C-2")
        assert [d["claim_id"] for _, d in docs] == ["C-2"]

    def test_matched_pairs_face(self):
        doc = _artifact()
        assert req.matched_pairs(doc) == 4
        doc["pairs"][0]["repro_output"] = "different"
        assert req.matched_pairs(doc) == 3  # recomputed, flag not trusted


# ============================ mutation gate ==============================

class TestMutationMustRed:
    def test_evaluate_green_only_when_all_bytes_match(self):
        assert req.evaluate_pairs(_artifact()["pairs"]) == "green"
        pairs = _artifact()["pairs"]
        pairs[2]["repro_output"] = "out-101-PERTURBED"
        assert req.evaluate_pairs(pairs) == "red"

    def test_perturb_output_flips_one_byte(self):
        out = "out-000"
        assert req.perturb_output(out) != out
        assert len(req.perturb_output(out)) != 0

    def test_mutation_must_red_holds_for_byte_oracle(self):
        pairs = _artifact()["pairs"]
        assert req.mutation_must_red(pairs) is True

    def test_silent_green_oracle_refused(self):
        with pytest.raises(req.ReplayEquivalenceError, match="silent-green"):
            req.mutation_face(_artifact()["pairs"],
                              evaluate=lambda _p: "green")

    def test_healthy_oracle_passes_mutation_face(self):
        req.mutation_face(_artifact()["pairs"])  # default evaluator: no raise


# ==================== claim admission (the REJECT gate) ==================

import kunglao_record  # noqa: E402
import yaml  # noqa: E402
from _factories import seed_difficulty, seed_verifier_dispatch  # noqa: E402

REPRO_SPEC = {
    "primary_questions": [
        {"id": "q1", "q": "does the rewrite reproduce the device output?",
         "need": "yes_no_with_evidence",
         "reproduction": True},  # the DECLARED bit — never keyword-inferred
    ],
}


def _signoff_fact(ws: Path, claim_id: str = "C-1") -> None:
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / f"{claim_id}.md").write_text(
        f"---\nclaim: {claim_id}\n---\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: kunglao-redteam-w2\n"
        "  refute_attempt: 'tried to refute; held'\n"
        "  sign_off_at: 2026-08-10T14:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n", encoding="utf-8")


def _register_status(ws: Path, claim_id: str = "C-1") -> str:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text("utf-8"))
    return next(c["status"] for c in reg["claims"] if c["id"] == claim_id)


def _promotable_ws(ws_factory, *, claim_extra: dict | None = None,
                   spec: dict | None = REPRO_SPEC) -> Path:
    extra = {"answers_question": "q1"}
    extra.update(claim_extra or {})
    ws = ws_factory(claims=[])
    # defaults mode emits only the canonical five fields — the declared
    # replay/answers fields must reach the file, so write it sparse.
    from _factories import write_claims_register
    write_claims_register(ws, [dict(id="C-1", status="OPEN", **extra)],
                          defaults=False)
    _signoff_fact(ws)
    seed_difficulty(ws, "easy")
    seed_verifier_dispatch(ws, "C-1")
    if spec is not None:
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    return ws


class TestClaimAdmissionGate:
    def test_reproduction_claim_without_artifact_rejected(self,
                                                          ws_factory):
        ws = _promotable_ws(ws_factory)
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert not ok, f"unevidenced reproduction claim must REJECT: {msg}"
        assert "REPLAY EQUIVALENCE" in msg.upper()
        assert "ran without error" in msg.lower() or "controlled" in \
            msg.lower(), msg
        assert _register_status(ws) == "OPEN", "register not modified"

    def test_claim_declared_replay_field_arms_gate(self, ws_factory):
        """The claim's declared carrier field arms the gate by itself."""
        ws = _promotable_ws(ws_factory, claim_extra={
            "replay_evidence": "evidence/replay-C-1.json"}, spec=None)
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert not ok and "REPLAY EQUIVALENCE" in msg.upper(), msg

    def test_claim_with_valid_artifact_promotes(self, ws_factory):
        ws = _promotable_ws(ws_factory)
        _write_artifact(ws / "evidence")
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert ok, msg
        assert _register_status(ws) == "PROVEN"

    def test_artifact_for_another_claim_does_not_count(self, ws_factory):
        ws = _promotable_ws(ws_factory)
        _write_artifact(ws / "evidence", _artifact(claim_id="C-9"))
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert not ok, "C-9's evidence cannot witness C-1"
        assert "C-9" in msg or "C-1" in msg

    def test_unmatched_artifact_does_not_count(self, ws_factory):
        """A reproduction that MISSES on every captured input is honest red
        evidence — it can never witness equivalence."""
        ws = _promotable_ws(ws_factory)
        doc = _artifact()
        for p in doc["pairs"]:
            p["repro_output"] = p["ref_output"] + "-MISSED"
            p["byte_equal"] = False  # honestly recorded miss
        _write_artifact(ws / "evidence", doc)
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert not ok and "match" in msg.lower(), msg
        assert _register_status(ws) == "OPEN"

    def test_legacy_claim_without_declarations_unaffected(self, ws_factory):
        """No task_spec, no declared replay field — the gate is silent
        (declared-face discipline: nothing inferred from task text)."""
        ws = _promotable_ws(ws_factory, spec=None)
        ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN",
                                                "orchestrator")
        assert ok, f"legacy promotion must be untouched: {msg}"
        assert _register_status(ws) == "PROVEN"


# ============== verdict face (reproduction PQ cannot converge) ===========

from convergence_check import _unverified_primary_questions  # noqa: E402


def _ws_with_claim(tmp_path: Path, status: str = "PROVEN",
                   claim_extra: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    claim = {"id": "C-1", "status": status, "answers_question": "q1"}
    claim.update(claim_extra or {})
    from _factories import write_claims_register
    write_claims_register(ws, [claim], defaults=False)
    return ws


class TestVerdictFace:
    def test_reproduction_question_unverified_without_artifact(self,
                                                               tmp_path):
        ws = _ws_with_claim(tmp_path)
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            REPRO_SPEC, workspace=ws)
        assert [u["question"] for u in out] == ["q1"]
        assert "ran without error" in out[0]["reason"].lower()
        assert "not evidence" in out[0]["reason"].lower()

    def test_reproduction_question_verified_with_matched_artifact(
            self, tmp_path):
        ws = _ws_with_claim(tmp_path)
        _write_artifact(ws / "evidence")
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            REPRO_SPEC, workspace=ws)
        assert out == []

    def test_unmatched_artifact_keeps_question_unverified(self, tmp_path):
        ws = _ws_with_claim(tmp_path)
        doc = _artifact()
        for p in doc["pairs"]:
            p["repro_output"] = p["ref_output"] + "-MISSED"
            p["byte_equal"] = False
        _write_artifact(ws / "evidence", doc)
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            REPRO_SPEC, workspace=ws)
        assert [u["question"] for u in out] == ["q1"]
        assert "match" in out[0]["reason"].lower()

    def test_coverage_hole_keeps_question_unverified(self, tmp_path):
        ws = _ws_with_claim(tmp_path)
        doc = _artifact()
        doc["pairs"] = doc["pairs"][:3]  # coverage hole
        _write_artifact(ws / "evidence", doc)
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            REPRO_SPEC, workspace=ws)
        assert [u["question"] for u in out] == ["q1"]
        assert "coverage" in out[0]["reason"].lower()

    def test_missing_workspace_face_fails_closed(self, tmp_path):
        ws = _ws_with_claim(tmp_path)  # workspace exists but is not passed
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            REPRO_SPEC, workspace=None)
        assert [u["question"] for u in out] == ["q1"]
        assert "fail" in out[0]["reason"].lower()

    def test_plain_question_regression_untouched(self, tmp_path):
        plain = {"primary_questions": [
            {"id": "q1", "q": "family?", "need": "yes_no_with_evidence"}]}
        ws = _ws_with_claim(tmp_path)
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            plain, workspace=None)
        assert out == []
        out = _unverified_primary_questions(
            {"claims": [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q1"}]},
            plain, workspace=ws)
        assert out == []


# ============= verifier execution (compare, don't read) =================

import re  # noqa: E402

from replay_equivalence import ReplayEquivalenceError  # noqa: E402

CLIENT_BODY = (
    "# oracle client\n"
    "def compute(params):\n"
    "    return {'echo': params['nonce']}\n")

WRONG_CLIENT_BODY = (
    "# a WRONG reproduction: the oracle must execute it red\n"
    "def compute(params):\n"
    "    return {'echo': params['nonce'] + 100}\n")


def _exec_artifact(*, honest_repro: bool = True,
                   lie_about_repro: bool = False) -> dict:
    """A minimal valid artifact over 2 declared variables; ref_output is
    the canonical serialization of the honest client's output."""
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": ["cap-0x", "cap-0y", "cap-1x", "cap-1y"],
        "variables": {"nonce": [0, 1], "param": ["x", "y"]},
        "pairs": [],
    }
    for nonce in (0, 1):
        for param in ("x", "y"):
            pid = f"cap-{nonce}{param}"
            ref = req.canonical_output({"echo": nonce})
            if honest_repro:
                repro, equal = ref, True
            else:  # the worker honestly recorded its own misses
                repro, equal = req.canonical_output({"echo": nonce + 100}), \
                    False
            doc["pairs"].append(_pair(pid, {"nonce": nonce, "param": param},
                                      ref, repro, equal=equal))
    if lie_about_repro:
        doc["pairs"][0]["repro_output"] = "out-fabricated"
        doc["pairs"][0]["byte_equal"] = False
    return doc


class TestVerifierExecution:
    def _client(self, ws: Path, body: str = CLIENT_BODY) -> Path:
        p = ws / "oracle" / "client.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_honest_reproduction_executes_green(self, tmp_path):
        art = _write_artifact(tmp_path, _exec_artifact())
        report = req.execute_comparison(self._client(tmp_path), art)
        assert report["verdict"] == "green"
        assert all(r["byte_equal"] for r in report["rows"])
        assert report["mutation_red"] is True

    def test_wrong_reproduction_executes_red_with_divergence(self, tmp_path):
        art = _write_artifact(tmp_path, _exec_artifact(honest_repro=False))
        report = req.execute_comparison(self._client(tmp_path,
                                                    WRONG_CLIENT_BODY), art)
        assert report["verdict"] == "red"
        bad = [r for r in report["rows"] if not r["byte_equal"]]
        assert bad, "the wrong reproduction must produce red rows"
        assert all(isinstance(r["divergence_offset"], int) and
                   r["divergence_offset"] >= 0 for r in bad)

    def test_fabricated_recorded_repro_is_flagged(self, tmp_path):
        art = _write_artifact(tmp_path, _exec_artifact(lie_about_repro=True))
        report = req.execute_comparison(self._client(tmp_path), art)
        assert report["verdict"] == "green"
        assert any(not r["matches_recorded"] for r in report["rows"]), \
            "a fabricated recorded repro_output must be flagged"

    def test_invalid_artifact_refused_not_executed(self, tmp_path):
        doc = _exec_artifact()
        doc["pairs"][0]["inputs"]["nonce"] = 7  # outside declared domain
        art = _write_artifact(tmp_path, doc)
        with pytest.raises(ReplayEquivalenceError):
            req.execute_comparison(self._client(tmp_path), art)

    def test_missing_client_refused_loud(self, tmp_path):
        art = _write_artifact(tmp_path, _exec_artifact())
        with pytest.raises(ReplayEquivalenceError, match="client"):
            req.execute_comparison(tmp_path / "nope.py", art)

    def test_cli_execute_and_check(self, tmp_path):
        art = _write_artifact(tmp_path, _exec_artifact())
        client = self._client(tmp_path)
        assert req.main(["--execute", str(client),
                         "--artifact", str(art)]) == 0
        bad = _write_artifact(tmp_path, _exec_artifact(honest_repro=False),
                              "replay-bad.json")
        wrong = self._client(tmp_path, WRONG_CLIENT_BODY)
        assert req.main(["--execute", str(wrong),
                         "--artifact", str(bad)]) == 1
        # a dir holding an INVALID artifact must not pass --check-evidence
        invalid = _exec_artifact()
        invalid["pairs"][0]["inputs"]["nonce"] = 7  # outside declared domain
        _write_artifact(tmp_path, invalid, "replay-invalid.json")
        assert req.main(["--check-evidence", str(tmp_path)]) == 1
        assert req.main(["--check-evidence", str(client.parent)]) == 1  # none


class TestAgentContractFaces:
    """The agent-contract faces of teeth 2 and 5 (pinned the same way as
    test_verdict_scorer_contract.py pins the scorer's schema)."""

    def test_redteam_must_execute_not_merely_read(self):
        text = (ROOT / "agents" / "kunglao-redteam.md").read_text("utf-8")
        assert "replay_equivalence" in text, \
            "the redteam agent must be pointed at the execution oracle"
        assert "--execute" in text, "the execution command must be named"
        assert re.search(r"not\s+verification", text, re.IGNORECASE), \
            "reading the worker's artifact must be named as NOT verification"
        assert "captured" in text.lower()

    def test_verdict_scorer_names_the_refusal_reason(self):
        text = (ROOT / "agents" / "verdict-scorer.md").read_text("utf-8")
        assert "reproduction" in text.lower()
        assert "ran without error" in text.lower()
        assert "not evidence" in text.lower()
        assert "replay" in text.lower()
