# -*- coding: utf-8 -*-
"""Contract tests for the structural oracle-anchor intake.

The init script itself asks for the three oracle anchors through the
pending-decision channel: a fresh init on a workspace without answers
exits 8 with a pending document naming goal_verbatim /
success_criterion / verification_method (same schema, same ids, same
--resolve re-entry as the upgrade interview). The re-entry writes the
anchors into task_spec.yaml and pre-fills the completion oracle's
task_text from the verbatim goal.

Contract: init never reports success with blank anchors. Every exit-0
path implies a complete anchor set, and every blank-anchor run exits 8
with a pending document — pinned in both directions by the matrix below
(fresh, resume, repair, and legacy type-upgrade paths).

The upgrade runner verifies the three anchors BEFORE any migration work:
on a workspace with stripped anchors the interview fires first on the
migration path — no migration item applied, no stamp refresh — on every
success path (the already-current and dry-run faces keep their pinned
contracts).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_anchors as oa  # noqa: E402
import template_version  # noqa: E402
from _factories import seed_bins  # noqa: E402

ANCHOR_IDS = ("goal_verbatim", "success_criterion", "verification_method")

ANSWERS = {
    "goal_verbatim": "recover the config decryption routine",
    "success_criterion": "a standalone client replays every captured "
                         "(input -> plaintext) pair byte-exact",
    "verification_method": "reproduction",
}


def _run_init(ws: Path, extra: list[str]) -> "subprocess.CompletedProcess":
    """Hermetic init run: toolchain skipped, the host-exec ask answered
    explicitly (non-interactive), profile writes pinned to a temp root."""
    import subprocess
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--skip-toolchain", *extra,
            "--host-exec-protection", "enabled",
            "--profile-root", str(ws.parent / "profile-root")]
    env = dict(os.environ)
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True,
                          env=env, timeout=300, cwd=str(ROOT))


def _pending_doc(stdout: str) -> dict:
    """The pending-decision JSON document (the trailing stdout object)."""
    lines = stdout.strip().splitlines()
    parsed: dict | None = None
    for start in range(len(lines)):
        stripped = "\n".join(lines[start:]).strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except ValueError:
                continue
    assert parsed is not None, \
        f"no pending-decision JSON in stdout:\n{stdout}"
    return parsed


def _fresh_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    seed_bins(ws)
    (ws / "runs").mkdir()
    return ws


def _complete_spec(**over) -> dict:
    doc = dict(ANSWERS)
    doc.update(over)
    return doc


def _write_spec(ws: Path, doc: dict | None) -> None:
    if doc is None:
        (ws / "task_spec.yaml").unlink(missing_ok=True)
        return
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(doc),
                                       encoding="utf-8")


# ------------------------------------------- init: structural asking (RED)

class TestInitStructuralAsking:
    def test_fresh_init_without_answers_pends_with_three_decisions(
            self, tmp_path):
        ws = _fresh_ws(tmp_path)
        r = _run_init(ws, ["--type", "windows"])
        assert r.returncode == 8, f"expected the pending exit, got " \
                                  f"{r.returncode}\n{r.stdout}\n{r.stderr}"
        doc = _pending_doc(r.stdout)
        assert doc["flow"] == "kunglao-init"
        ids = [d["decision_id"] for d in doc["decisions"]]
        assert ids == list(ANCHOR_IDS)
        kinds = {d["decision_id"]: d["kind"] for d in doc["decisions"]}
        assert kinds["goal_verbatim"] == "value"
        assert kinds["success_criterion"] == "value"
        assert kinds["verification_method"] == "choice"
        method = next(d for d in doc["decisions"]
                      if d["decision_id"] == "verification_method")
        assert tuple(method["options"]) == oa.METHOD_OPTIONS

    def test_pending_exit_writes_zero_scaffold(self, tmp_path):
        """A pended init writes zero ANALYSIS scaffold. Owner priority
        update (issue 212): the statusline registration deliberately runs
        FIRST — before the interview concludes — so a pended run still
        leaves the operator's visible success/failure signal. Sanctioned
        residue on a pended run is therefore exactly one carrier:
        .claude/settings.json holding ONLY the statusLine key (no hooks
        wiring, no scaffold carriers, no analysis state)."""
        ws = _fresh_ws(tmp_path)
        r = _run_init(ws, ["--type", "windows"])
        assert r.returncode == 8
        assert not (ws / "claim-register.yaml").exists()
        assert not (ws / "CLAUDE.md").exists()
        assert not (ws / "task-oracle.yaml").exists()
        settings = ws / ".claude" / "settings.json"
        doc = (json.loads(settings.read_text(encoding="utf-8"))
               if settings.exists() else {})
        assert set(doc) <= {"statusLine"}, \
            f"pended init may write only the statusline carrier: {sorted(doc)}"
        assert "statusLine" in doc, \
            "the statusline registration is the FIRST step — it must survive" \
            " a pended run (owner priority update)"

    def test_resolve_round_trip_writes_anchors_and_prefills_oracle(
            self, tmp_path):
        ws = _fresh_ws(tmp_path)
        r1 = _run_init(ws, ["--type", "windows"])
        assert r1.returncode == 8, r1.stderr
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
        r2 = _run_init(ws, ["--type", "windows", "--resolve", str(answers)])
        assert r2.returncode == 0, r2.stderr
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        for field in ANCHOR_IDS:
            assert doc[field] == ANSWERS[field]
        oracle = yaml.safe_load((ws / "task-oracle.yaml").read_text(
            encoding="utf-8"))
        assert oracle["task_text"] == ANSWERS["goal_verbatim"]
        assert "task_text pre-filled from the intake goal" in r2.stdout

    def test_partial_answers_apply_then_pend_remaining(self, tmp_path):
        ws = _fresh_ws(tmp_path)
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps(
            {"verification_method": "static"}), encoding="utf-8")
        r1 = _run_init(ws, ["--type", "windows", "--resolve", str(answers)])
        assert r1.returncode == 8, r1.stderr
        doc = _pending_doc(r1.stdout)
        assert [d["decision_id"] for d in doc["decisions"]] == \
            ["goal_verbatim", "success_criterion"]
        # the supplied answer landed even though the run pended
        spec = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert spec["verification_method"] == "static"
        rest = tmp_path / "rest.json"
        rest.write_text(json.dumps(
            {k: ANSWERS[k] for k in
             ("goal_verbatim", "success_criterion")}), encoding="utf-8")
        r2 = _run_init(ws, ["--type", "windows", "--resolve", str(rest)])
        assert r2.returncode == 0, r2.stderr
        ok, gaps, _state = oa.inspect(ws)
        assert ok and gaps == []

    def test_out_of_enum_answer_fails_closed_before_scaffold(
            self, tmp_path):
        ws = _fresh_ws(tmp_path)
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps(
            {**ANSWERS, "verification_method": "vibes"}), encoding="utf-8")
        r = _run_init(ws, ["--type", "windows", "--resolve", str(answers)])
        assert r.returncode != 0
        assert "refused" in r.stderr
        assert not (ws / "claim-register.yaml").exists()

    def test_corrupt_contract_fails_loud_on_fresh_path(self, tmp_path):
        """An unreadable contract is never interviewed (the re-entry would
        deadlock) and never silently passed: the render defect path fails
        the run."""
        ws = _fresh_ws(tmp_path)
        (ws / "task_spec.yaml").write_text(
            "primary_questions: [ unclosed\n", encoding="utf-8")
        r = _run_init(ws, ["--type", "windows"])
        assert r.returncode != 0
        assert "task_spec.yaml" in (r.stderr + r.stdout)


# --------------------------------------- no-silent-success contract matrix

class TestNoSilentSuccessContract:
    """init exit 0 with blank anchors is impossible: every scenario either
    exits 0 with a complete anchor set or exits 8 with the pending
    document."""

    def _scenario_ws(self, tmp_path: Path, name: str) -> Path:
        """Scenario staging:
        fresh_*  — no claim register yet (first init);
        resume_* — initialized workspace re-running init;
        legacy_* — marker present but project_type missing (pre-type
                   workspace upgraded by the init re-run)."""
        ws = _fresh_ws(tmp_path)
        if name.startswith(("resume_", "legacy_")):
            r = _run_init(ws, ["--type", "windows", "--resolve",
                               str(self._answers_file(tmp_path))])
            assert r.returncode == 0, r.stderr
        if name.startswith("legacy_"):
            # the dedicated state file is the PRIMARY completeness truth —
            # remove it (the register's marker comment survives) and strip
            # the analysis_state.txt declaration, so the re-run takes the
            # legacy type-upgrade branch
            (ws / ".kunglao-init.json").unlink(missing_ok=True)
            state = ws / "analysis_state.txt"
            lines = [ln for ln in state.read_text(encoding="utf-8")
                     .splitlines()
                     if not ln.startswith("project_type=")]
            state.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ws

    def _answers_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "staging-answers.json"
        p.write_text(json.dumps(ANSWERS), encoding="utf-8")
        return p

    @pytest.mark.parametrize(
        "name,spec,answers,expect_rc",
        [
            ("fresh_blank", None, None, 8),
            ("fresh_complete", _complete_spec(), None, 0),
            ("resume_blank", None, None, 8),
            ("resume_complete", _complete_spec(), None, 0),
            ("resume_partial_no_answers",
             _complete_spec(success_criterion="", verification_method=""),
             None, 8),
            ("resume_partial_partial_answers",
             _complete_spec(success_criterion="", verification_method=""),
             {"verification_method": "manual"}, 8),
            ("legacy_blank", None, None, 8),
            ("legacy_complete", _complete_spec(), None, 0),
        ])
    def test_exit_zero_implies_complete_anchors(
            self, tmp_path, name, spec, answers, expect_rc):
        ws = self._scenario_ws(tmp_path, name)
        _write_spec(ws, spec)
        extra = ["--type", "windows"]
        if answers is not None:
            p = tmp_path / "answers.json"
            p.write_text(json.dumps(answers), encoding="utf-8")
            extra += ["--resolve", str(p)]
        r = _run_init(ws, extra)
        assert r.returncode == expect_rc, \
            f"{name}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
        ok, gaps, _state = oa.inspect(ws)
        if expect_rc == 0:
            assert ok, f"{name}: exit 0 with missing {gaps}"
        else:
            assert not ok, f"{name}: blank anchors must not exit 0"
            doc = _pending_doc(r.stdout)
            pend_ids = {d["decision_id"] for d in doc["decisions"]}
            assert pend_ids == set(gaps), \
                f"{name}: pending ids {pend_ids} != gaps {gaps}"


# --------------------------------- upgrade: the interview fires first (RED)

def _legacy_ws(tmp_path: Path, spec: dict | None = None,
               version: str = "0.1.2") -> Path:
    import kunglao_upgrade as up
    ws = tmp_path / "ws"
    (ws / ".claude" / "hooks").mkdir(parents=True)
    (ws / "CLAUDE.md").write_text(
        template_version.stamp_line(version) + "\n", encoding="utf-8")
    if spec is not None:
        _write_spec(ws, spec)
    assert up._vkey(template_version.read_workspace_version(ws)) < \
        up._vkey(template_version.read_skill_version())
    return ws


class TestUpgradeInterviewFirst:
    def test_migration_path_pends_before_any_migration_work(
            self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = _legacy_ws(tmp_path, spec=None)
        items: list = []
        rc = up.upgrade(ws, dry_run=False, items_out=items)
        out = capsys.readouterr().out
        assert rc == up.RC_ANCHORS_PENDING == 8
        doc = _pending_doc(out)
        assert doc["flow"] == "kunglao-upgrade"
        assert {d["decision_id"] for d in doc["decisions"]} == set(ANCHOR_IDS)
        # the interview preceded the work: nothing applied, no stamp refresh
        assert [i for i in items if i["action"] == "applied"] == []
        assert template_version.read_workspace_version(ws) == "0.1.2"
        assert not (ws / "task_spec.yaml").exists()

    def test_migration_path_resolve_round_trip_completes(
            self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = _legacy_ws(tmp_path, spec=None)
        items1: list = []
        rc1 = up.upgrade(ws, dry_run=False, items_out=items1)
        capsys.readouterr()
        assert rc1 == 8
        items2: list = []
        rc2 = up.upgrade(ws, dry_run=False, items_out=items2, resolve=ANSWERS)
        capsys.readouterr()
        assert rc2 == 0
        ok, gaps, _state = oa.inspect(ws)
        assert ok and gaps == []
        # the migration work the first run deferred happens on the re-entry
        assert [i for i in items2 if i["action"] == "applied"]
        doc = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        for field in ANCHOR_IDS:
            assert doc[field] == ANSWERS[field]

    def test_migration_path_dry_run_plans_and_never_pends(
            self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = _legacy_ws(tmp_path, spec=None)
        rc = up.upgrade(ws, dry_run=True, items_out=[])
        out = capsys.readouterr().out
        assert rc == 0  # a dry run plans, never pends
        assert "anchor" in out
        assert '"decisions"' not in out
        assert not (ws / "task_spec.yaml").exists()

    def test_complete_anchors_pass_silently_on_migration_path(
            self, tmp_path, capsys):
        import kunglao_upgrade as up
        ws = _legacy_ws(tmp_path, spec=_complete_spec(
            verification_method="manual"))
        rc = up.upgrade(ws, dry_run=False, items_out=[])
        out = capsys.readouterr().out
        assert rc == 0
        assert '"decisions"' not in out
        assert "anchors: complete" in out
