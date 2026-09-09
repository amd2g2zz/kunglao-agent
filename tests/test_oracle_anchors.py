# -*- coding: utf-8 -*-
"""Contract tests for the oracle-anchor intake fields in task_spec.yaml.

The init interview must collect three REQUIRED answers — the verbatim goal,
the success criterion, and the verification method — and land them as
first-class task_spec.yaml fields. Enforced faces:

- validation is fail-closed: a blank field or an out-of-enum method is a
  missing answer, never a guessed default;
- the verification-method answer arms the replay-equivalence oracle's
  declared-question set (the controlled-comparison admission/verdict face);
- analysis entry refuses while any answer is missing;
- a collected verbatim goal pre-fills the completion oracle's task_text.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_anchors as oa  # noqa: E402
import replay_equivalence as req  # noqa: E402
import template_version  # noqa: E402
from _hooks_path import load_module_by_path  # noqa: E402
from _factories import seed_bins  # noqa: E402

kunglao_init = load_module_by_path("kunglao_init_oracle_anchors",
                                   SCRIPTS / "kunglao-init.py")


def _spec(**over) -> dict:
    """A complete three-answer task_spec (primary_questions included so the
    arming tests exercise real question ids)."""
    doc = {
        "primary_questions": [
            {"id": "q1", "q": "does the sample decrypt the config?",
             "need": "yes_no_with_evidence"},
            {"id": "q2", "q": "which routine computes the checksum?",
             "need": "yes_no_with_evidence"},
        ],
        "goal_verbatim": "recover the config decryption routine",
        "success_criterion": "a standalone client replays every captured "
                             "(input -> plaintext) pair byte-exact",
        "verification_method": "reproduction",
    }
    doc.update(over)
    return doc


# ------------------------------------------------ required-field validation

class TestRequiredValidation:
    def test_empty_spec_reports_all_three(self):
        assert oa.missing({}) == ["goal_verbatim", "success_criterion",
                                  "verification_method"]

    def test_blank_values_are_missing(self):
        spec = _spec(goal_verbatim="   ", success_criterion="",
                     verification_method="")
        assert oa.missing(spec) == ["goal_verbatim", "success_criterion",
                                    "verification_method"]

    def test_non_string_values_are_missing(self):
        spec = _spec(goal_verbatim=42, verification_method=["reproduction"])
        assert oa.missing(spec) == ["goal_verbatim", "verification_method"]

    def test_out_of_enum_method_is_missing(self):
        """An unknown method is not an answer — the entry gate refuses rather
        than adopting a silent default."""
        assert oa.missing(_spec(verification_method="vibes")) == \
            ["verification_method"]

    def test_complete_spec_reports_nothing(self):
        assert oa.missing(_spec()) == []

    def test_method_options_are_the_four_declared_values(self):
        assert oa.METHOD_OPTIONS == ("reproduction", "replay-evidence",
                                     "static", "manual")
        assert oa.FIELDS == ("goal_verbatim", "success_criterion",
                             "verification_method")


# --------------------------------------------------------- spec round-trip

class TestTaskSpecRoundTrip:
    def test_apply_writes_the_three_fields(self, tmp_path):
        ws = tmp_path
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        oa.apply(ws, _spec())
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        for field in oa.FIELDS:
            assert doc[field] == _spec()[field]

    def test_apply_preserves_existing_user_keys(self, tmp_path):
        ws = tmp_path
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        oa.apply(ws, _spec())
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert [q["id"] for q in doc["primary_questions"]] == ["q1", "q2"]

    def test_apply_creates_task_spec_when_absent(self, tmp_path):
        ws = tmp_path
        path = oa.apply(ws, _spec())
        assert path == ws / "task_spec.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["verification_method"] == "reproduction"

    def test_apply_never_clobbers_existing_answers(self, tmp_path):
        ws = tmp_path
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        oa.apply(ws, _spec(goal_verbatim="a DIFFERENT goal"))
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert doc["goal_verbatim"] == "recover the config decryption routine"

    def test_load_view_tolerates_absent_and_corrupt_spec(self, tmp_path):
        assert oa.load(tmp_path) == {}
        (tmp_path / "task_spec.yaml").write_text(
            "primary_questions: [ unclosed\n", encoding="utf-8")
        assert oa.load(tmp_path) == {}
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        assert oa.load(tmp_path)["goal_verbatim"] == \
            "recover the config decryption routine"

    def test_check_ws_reflects_the_workspace(self, tmp_path):
        ok, missing = oa.check_ws(tmp_path)
        assert not ok
        assert missing == list(oa.FIELDS)
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        ok, missing = oa.check_ws(tmp_path)
        assert ok and missing == []


# --------------------------------------------- declared-bit oracle arming

class TestDeclaredBitArming:
    def test_reproduction_method_arms_every_question(self):
        qids = req.declared_reproduction_qids(_spec())
        assert qids == {"q1", "q2"}

    def test_replay_evidence_method_arms_every_question(self):
        qids = req.declared_reproduction_qids(
            _spec(verification_method="replay-evidence"))
        assert qids == {"q1", "q2"}

    def test_static_and_manual_arms_nothing(self):
        for method in ("static", "manual"):
            assert req.declared_reproduction_qids(
                _spec(verification_method=method)) == set()

    def test_absent_method_keeps_per_question_bits_only(self):
        """A spec without the method answer behaves exactly as before: only
        explicitly flagged questions carry the bit."""
        spec = {"primary_questions": [{"id": "q1", "reproduction": True},
                                      {"id": "q2"}]}
        assert req.declared_reproduction_qids(spec) == {"q1"}

    def test_armed_verdict_refuses_unevidenced_claim(self, tmp_path):
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec(verification_method="reproduction")),
            encoding="utf-8")
        claim = {"id": "C-1", "answers_question": "q1"}
        ok, reason = req.equivalence_verdict(tmp_path, claim)
        assert not ok
        assert reason.strip()

    def test_armed_verdict_passes_with_valid_artifact(self, tmp_path):
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec(verification_method="replay-evidence")),
            encoding="utf-8")
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        artifact = {
            "schema": req.SCHEMA_ID,
            "claim_id": "C-1",
            "captured_inputs": ["cap-01", "cap-02", "cap-03", "cap-04"],
            "variables": {"nonce": [0, 1], "param": ["x", "y"]},
            "pairs": [
                {"input_id": "cap-01", "inputs": {"nonce": 0, "param": "x"},
                 "ref_output": "out-0", "repro_output": "out-0",
                 "byte_equal": True},
                {"input_id": "cap-02", "inputs": {"nonce": 0, "param": "y"},
                 "ref_output": "out-1", "repro_output": "out-1",
                 "byte_equal": True},
                {"input_id": "cap-03", "inputs": {"nonce": 1, "param": "x"},
                 "ref_output": "out-2", "repro_output": "out-2",
                 "byte_equal": True},
                {"input_id": "cap-04", "inputs": {"nonce": 1, "param": "y"},
                 "ref_output": "out-3", "repro_output": "out-3",
                 "byte_equal": True},
            ],
        }
        (evidence / "replay-C-1.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        claim = {"id": "C-1", "answers_question": "q1"}
        ok, reason = req.equivalence_verdict(tmp_path, claim)
        assert ok, reason

    def test_unarmed_method_leaves_plain_claims_untouched(self, tmp_path):
        (tmp_path / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec(verification_method="manual")),
            encoding="utf-8")
        claim = {"id": "C-1", "answers_question": "q1"}
        ok, reason = req.equivalence_verdict(tmp_path, claim)
        assert ok and reason == ""


# ------------------------------------------------------ analysis-entry gate

def _entry_ws(tmp_path: Path) -> Path:
    """A workspace whose template stamp is current, so the stale gate passes
    and the anchor gate is what decides."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    stamp = template_version.stamp_line(
        template_version.read_skill_version())
    (ws / "CLAUDE.md").write_text(f"{stamp}\n", encoding="utf-8")
    return ws


class TestAnalysisEntryGate:
    def test_rc_constant_is_seven(self):
        import kunglao
        assert kunglao.RC_ORACLE_ANCHORS_MISSING == 7

    def test_entry_refuses_while_answers_missing(self, tmp_path, capsys):
        ws = _entry_ws(tmp_path)
        import kunglao
        rc = kunglao.cmd_analysis(argparse.Namespace(workspace=str(ws)))
        out = capsys.readouterr()
        assert rc == 7
        for field in oa.FIELDS:
            assert field in out.err

    def test_entry_proceeds_past_anchor_gate_when_answered(
            self, tmp_path, capsys):
        ws = _entry_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        import kunglao
        rc = kunglao.cmd_analysis(argparse.Namespace(workspace=str(ws)))
        capsys.readouterr()
        # The anchor gate passed; the heartbeat verify gate now decides.
        assert rc == kunglao.RC_HEARTBEAT_VERIFY_FAIL


# ------------------------------------------- completion-oracle consumption

class TestOraclePrefill:
    def test_skeleton_prefills_task_text_from_goal(self, tmp_path):
        assert kunglao_init.write_task_oracle_skeleton(
            tmp_path, task_text="recover the config decryption routine")
        doc = yaml.safe_load((tmp_path / "task-oracle.yaml").read_text(
            encoding="utf-8"))
        assert doc["task_text"] == "recover the config decryption routine"

    def test_skeleton_keeps_marker_without_goal(self, tmp_path):
        kunglao_init.write_task_oracle_skeleton(tmp_path)
        doc = yaml.safe_load((tmp_path / "task-oracle.yaml").read_text(
            encoding="utf-8"))
        assert doc["task_text"] == kunglao_init.ORACLE_BACKFILL_MARKER

    def test_existing_oracle_is_never_clobbered(self, tmp_path):
        target = tmp_path / "task-oracle.yaml"
        target.write_text("task_text: keep me\n", encoding="utf-8")
        assert not kunglao_init.write_task_oracle_skeleton(
            tmp_path, task_text="a fresh goal")
        assert "keep me" in target.read_text(encoding="utf-8")


# ------------------------------------------ boundary validations (owner scope)

def _spec_without(*fields: str) -> dict:
    doc = _spec()
    for field in fields:
        doc.pop(field)
    return doc


class TestBoundaryValidations:
    @pytest.fixture
    def entry_ws(self, tmp_path) -> Path:
        return _entry_ws(tmp_path)

    def _write_spec(self, ws: Path, doc: dict | None) -> None:
        if doc is None:
            (ws / "task_spec.yaml").unlink(missing_ok=True)
            return
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(doc), encoding="utf-8")

    def test_entry_rejects_each_missing_anchor(self, entry_ws, capsys):
        import kunglao
        for field in oa.FIELDS:
            self._write_spec(entry_ws, _spec_without(field))
            rc = kunglao.cmd_analysis(argparse.Namespace(
                workspace=str(entry_ws)))
            err = capsys.readouterr().err
            assert rc == 7, f"{field}: expected refusal, got rc={rc}"
            assert field in err, f"{field} not named in refusal: {err}"
            capsys.readouterr()

    def test_resume_rejects_missing_anchors(self, entry_ws, capsys):
        import kunglao
        self._write_spec(entry_ws, _spec_without("success_criterion"))
        rc = kunglao.cmd_resume(argparse.Namespace(
            workspace=str(entry_ws), json=False))
        err = capsys.readouterr().err
        assert rc == 7
        assert "success_criterion" in err

    def test_resume_proceeds_when_complete(self, entry_ws, capsys):
        import kunglao
        self._write_spec(entry_ws, _spec())
        rc = kunglao.cmd_resume(argparse.Namespace(
            workspace=str(entry_ws), json=False))
        capsys.readouterr()
        assert rc != 7

    def test_entry_names_the_repair_path(self, entry_ws, capsys):
        """A task_spec with fields missing is repairable in place: the
        refusal names the re-entry command that fills only the gaps."""
        import kunglao
        self._write_spec(entry_ws, _spec_without("goal_verbatim"))
        rc = kunglao.cmd_analysis(argparse.Namespace(
            workspace=str(entry_ws)))
        err = capsys.readouterr().err
        assert rc == 7
        assert "--resolve" in err and "--force" not in err

    def test_corrupt_spec_asks_for_full_reinit(self, entry_ws, capsys):
        """An unreadable contract is not repairable in place: the refusal
        directs to the full re-init path instead."""
        import kunglao
        (entry_ws / "task_spec.yaml").write_text(
            "primary_questions: [ unclosed\n", encoding="utf-8")
        rc = kunglao.cmd_analysis(argparse.Namespace(
            workspace=str(entry_ws)))
        err = capsys.readouterr().err
        assert rc == 7
        assert "--force" in err, err

def _run_init(ws: Path, extra: list[str]) -> subprocess.CompletedProcess:
    """Hermetic init run: toolchain skipped, the host-exec ask answered
    explicitly (non-interactive), profile writes pinned to a temp root."""
    import os
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--skip-toolchain", *extra,
            "--host-exec-protection", "enabled",
            "--profile-root", str(ws.parent / "profile-root")]
    env = dict(os.environ)
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True,
                          env=env, timeout=300, cwd=str(ROOT))


# ------------------------------------------------ upgrade backfill (legacy)

class TestUpgradeBackfill:
    """A legacy workspace (initialized before the anchors existed) must not
    deadlock: upgrade backfills the missing answers through the same
    structured interview channel — analysis entry and resume then pass."""

    def _current_ws(self, tmp_path: Path, spec: dict | None) -> Path:
        import kunglao_upgrade as up
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        (ws / "CLAUDE.md").write_text(
            template_version.stamp_line(
                template_version.read_skill_version()) + "\n",
            encoding="utf-8")
        if spec is not None:
            (ws / "task_spec.yaml").write_text(
                yaml.safe_dump(spec), encoding="utf-8")
        assert up._vkey(template_version.read_workspace_version(ws)) >= \
            up._vkey(template_version.read_skill_version())
        return ws

    def test_upgrade_pends_and_elicits_for_legacy_spec(self, tmp_path,
                                                       capsys):
        import kunglao_upgrade as up
        ws = self._current_ws(tmp_path, _spec_without(*oa.FIELDS))
        items: list = []
        rc = up.upgrade(ws, dry_run=False, items_out=items)
        out = capsys.readouterr().out
        assert rc == up.RC_ANCHORS_PENDING == 8
        doc = json.loads(out.strip().splitlines()[-1])
        ids = {d["decision_id"] for d in doc["decisions"]}
        assert ids == set(oa.FIELDS)
        assert any(i["name"] == "oracle_anchor_backfill" for i in items)

    def test_upgrade_backfills_from_answers_then_gates_pass(self, tmp_path,
                                                            capsys):
        import kunglao_upgrade as up
        ws = self._current_ws(tmp_path, _spec_without(*oa.FIELDS))
        answers = {"goal_verbatim": "recover the license check",
                   "success_criterion": "key matches the captured blob",
                   "verification_method": "reproduction"}
        rc = up.upgrade(ws, dry_run=False,
                        items_out=[], resolve=answers)
        out = capsys.readouterr().out
        assert rc == 0
        assert "backfilled via interview" in out
        ok, gaps, _state = oa.inspect(ws)
        assert ok and gaps == []

    def test_upgrade_reports_complete_without_reask(self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = self._current_ws(tmp_path, _spec())
        rc = up.upgrade(ws, dry_run=False, items_out=[])
        out = capsys.readouterr().out
        assert rc == 0
        assert "anchors: complete" in out
        assert '"decisions"' not in out

    def test_upgrade_backfills_only_missing_fields(self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = self._current_ws(
            tmp_path, _spec_without("success_criterion",
                                    "verification_method"))
        answers = {"goal_verbatim": "IGNORED existing goal",
                   "verification_method": "static"}
        rc = up.upgrade(ws, dry_run=False, items_out=[], resolve=answers)
        capsys.readouterr()
        assert rc == up.RC_ANCHORS_PENDING  # success_criterion still missing
        import yaml as _yaml
        doc = _yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert doc["goal_verbatim"] == \
            "recover the config decryption routine"  # never clobbered
        assert doc["verification_method"] == "static"

    def test_dry_run_reports_without_writing(self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = self._current_ws(tmp_path, _spec_without(*oa.FIELDS))
        before = (ws / "task_spec.yaml").read_bytes()
        rc = up.upgrade(ws, dry_run=True, items_out=[])
        out = capsys.readouterr().out
        assert rc == 0  # a dry run plans, never pends
        assert "anchor" in out
        assert (ws / "task_spec.yaml").read_bytes() == before

    def test_json_status_names_anchor_pending(self):
        import kunglao_upgrade as up
        assert up.RC_ANCHORS_PENDING == 8

# -------------------------------------------------- repair re-entry (init)

class TestRepairReEntry:
    def test_validate_values_rejects_bad_method(self):
        with pytest.raises(ValueError):
            oa.validate_values({"verification_method": "vibes"})
        oa.validate_values({"verification_method": "static"})  # no raise

    def test_repair_fills_only_missing_and_preserves_state(self, tmp_path):
        """The re-entry fills ONLY the missing answers: an existing answer
        survives a conflicting repair value, and the analysis state (the
        claim register) is byte-identical across the repair run."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec_without("success_criterion",
                                         "verification_method")),
            encoding="utf-8")
        r1 = _run_init(ws, ["--type", "windows"])
        assert r1.returncode == 0, r1.stderr
        register_before = (ws / "claim-register.yaml").read_bytes()
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps({
            "goal_verbatim": "a CONFLICTING goal that must be ignored",
            "success_criterion": "plaintext matches the app render",
            "verification_method": "static",
        }), encoding="utf-8")
        r2 = _run_init(ws, ["--resolve", str(answers)])
        assert r2.returncode == 0, r2.stderr
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert doc["goal_verbatim"] == \
            "recover the config decryption routine"  # never clobbered
        assert doc["success_criterion"] == \
            "plaintext matches the app render"
        assert doc["verification_method"] == "static"
        assert (ws / "claim-register.yaml").read_bytes() == \
            register_before
        assert "anchor repair complete" in r2.stdout

    def test_repair_refuses_bad_method_value(self, tmp_path):
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        r1 = _run_init(ws, ["--type", "windows"])
        assert r1.returncode == 0, r1.stderr
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps({
            "verification_method": "vibes"}), encoding="utf-8")
        r2 = _run_init(ws, ["--resolve", str(answers)])
        assert r2.returncode != 0
        assert "anchor repair refused" in r2.stderr

    def test_repair_refused_on_corrupt_contract(self, tmp_path):
        """An unreadable contract is not repairable in place: the re-entry
        refuses without writing, the corrupt bytes survive untouched, and
        the remediation names the full re-init path (in-place repair on a
        corrupt file would silently replace the whole intake record with
        just the three anchors)."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        r1 = _run_init(ws, ["--type", "windows"])
        assert r1.returncode == 0, r1.stderr
        corrupt = "primary_questions: [ unclosed\n"
        (ws / "task_spec.yaml").write_text(corrupt, encoding="utf-8")
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps({
            "goal_verbatim": "g",
            "success_criterion": "s",
            "verification_method": "manual",
        }), encoding="utf-8")
        r2 = _run_init(ws, ["--resolve", str(answers)])
        assert r2.returncode != 0
        assert "--force" in r2.stderr, r2.stderr
        assert (ws / "task_spec.yaml").read_text(encoding="utf-8") == corrupt

    def test_repair_reports_still_missing(self, tmp_path):
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        r1 = _run_init(ws, ["--type", "windows"])
        assert r1.returncode == 0, r1.stderr
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps({
            "verification_method": "manual"}), encoding="utf-8")
        r2 = _run_init(ws, ["--resolve", str(answers)])
        assert r2.returncode == 0, r2.stderr
        assert "still missing" in r2.stderr


class TestInitEndToEnd:
    @pytest.fixture
    def fresh_ws(self, tmp_path) -> Path:
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        return ws

    def test_init_prints_reminder_while_answers_missing(self, fresh_ws):
        r = _run_init(fresh_ws, ["--type", "windows"])
        assert r.returncode == 0, r.stderr
        assert "anchors incomplete" in r.stdout, r.stdout

    def test_init_prefills_oracle_and_skips_reminder_when_answered(
            self, fresh_ws):
        (fresh_ws / "task_spec.yaml").write_text(
            yaml.safe_dump(_spec()), encoding="utf-8")
        r = _run_init(fresh_ws, ["--type", "windows"])
        assert r.returncode == 0, r.stderr
        assert "anchors incomplete" not in r.stdout
        doc = yaml.safe_load((fresh_ws / "task-oracle.yaml").read_text(
            encoding="utf-8"))
        assert doc["task_text"] == "recover the config decryption routine"
