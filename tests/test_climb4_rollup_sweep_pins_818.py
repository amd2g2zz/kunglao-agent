#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_rollup_sweep_pins_818.py — #818 climb segment 4E.

Behavior pins on REAL tmp workspaces for the rollup faces the third climb
leg left unmeasured:

  scripts/rollup.py — the mechanical faces around the already-tested
  run_rollup core: the _rolled_up idempotency guard (corrupt lines
  skipped, (claim, status) pair matching), the note-existence scan
  (legacy filename + frontmatter claim_id, README excluded, bad
  frontmatter tolerated), the #628 notes-due queue (idempotent append,
  scaffold exemption + stale-entry sweep), the CONFIRMED-with-DIFF
  signal extraction (line-anchored DIFF markers, prose mentions
  ignored, clean-pass no-row, signal_id idempotency), the machine-seeded
  failure skeleton (outcome-bearing statuses only, authored files never
  overwritten), pending_terminal_claims ordering, the sweep summary
  contract (fired/skipped/errors + per-claim exception cages) over a
  stubbed leaf, and the main() CLI contract (--sweep-terminal dry run,
  flag mixing refusals, single-claim rc faces).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(mod_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPTS / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


rag = _load("rollup_climb4_under_test", "rollup.py")


# ------------------------------------------------------------ fixtures

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


def _ledger_rollup_row(ws: Path, cid: str, status: str) -> None:
    with (ws / rag.LEDGER_NAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "operator_action", "action": "rollup",
                            "claim_id": cid, "terminal_status": status}) + "\n")


def _redteam_verdict(ws: Path, name: str, text: str) -> Path:
    p = ws / "runs" / name
    p.write_text(text, encoding="utf-8")
    return p


CONFIRMED_DIFF = (
    "RED-TEAM VERDICT: CONFIRMED\n"
    "claim: C-7\n"
    "## DIFF-1\n"
    "- DIFF: oracle nonce diverged at round 3\n"
    "prose mention of DIFF absent from item start\n")


# ------------------------------------------------------- idempotency guard

class TestRolledUpGuard:
    def test_matches_only_the_operator_rollup_pair(self, tmp_path) -> None:
        ws = _ws(tmp_path, [])
        assert rag._rolled_up(ws, "C-1", "PROVEN") is False
        _ledger_rollup_row(ws, "C-1", "PROVEN")
        assert rag._rolled_up(ws, "C-1", "PROVEN") is True
        assert rag._rolled_up(ws, "C-1", "NEGATIVE") is False
        assert rag._rolled_up(ws, "C-2", "PROVEN") is False

    def test_corrupt_and_foreign_lines_are_skipped(self, tmp_path) -> None:
        ws = _ws(tmp_path, [])
        with (ws / rag.LEDGER_NAME).open("w", encoding="utf-8") as f:
            f.write("not-json\n")
            f.write(json.dumps({"type": "outcome", "action": "rollup",
                                "claim_id": "C-1",
                                "terminal_status": "PROVEN"}) + "\n")
            f.write("\n")
        assert rag._rolled_up(ws, "C-1", "PROVEN") is False
        _ledger_rollup_row(ws, "C-1", "PROVEN")
        assert rag._rolled_up(ws, "C-1", "PROVEN") is True


# ------------------------------------------------------- notes-due faces

class TestNotesFaces:
    def test_note_exists_via_legacy_name_and_frontmatter(
            self, tmp_path) -> None:
        notes = tmp_path / "notes"
        notes.mkdir()
        assert rag._note_exists_for(notes, "C-1") is False
        (notes / "C-1.md").write_text("legacy name\n", encoding="utf-8")
        assert rag._note_exists_for(notes, "C-1") is True
        (notes / "descriptive-phrase.md").write_text(
            "---\nclaim_id: C-2\n---\nbody\n", encoding="utf-8")
        assert rag._note_exists_for(notes, "C-2") is True
        (notes / "README.md").write_text("---\nclaim_id: C-9\n---\n",
                                         encoding="utf-8")
        assert rag._note_exists_for(notes, "C-9") is False
        (notes / "broken.md").write_text("---\n: :\n---\n", encoding="utf-8")
        assert rag._note_exists_for(notes, "C-3") is False  # tolerated

    def test_queue_appends_once_and_is_idempotent(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        assert rag._queue_notes_due(ws, "C-1", "PROVEN") is True
        assert rag._queue_notes_due(ws, "C-1", "PROVEN") is False
        due = yaml.safe_load(
            (ws / rag.NOTES_DUE_FILE).read_text(encoding="utf-8"))
        assert len(due["due"]) == 1
        assert due["due"][0]["claim_id"] == "C-1"

    def test_existing_note_never_queues(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        (ws / "notes").mkdir()
        (ws / "notes" / "analysis.md").write_text(
            "---\nclaim_id: C-1\n---\nreal analysis\n", encoding="utf-8")
        assert rag._queue_notes_due(ws, "C-1", "PROVEN") is False
        assert not (ws / rag.NOTES_DUE_FILE).exists()

    def test_scaffold_claims_never_queue_and_stale_entries_sweep(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "S-1", "status": "PROVEN",
                             "claim_class": "Scaffold"}])
        due = ws / rag.NOTES_DUE_FILE
        due.write_text(yaml.safe_dump(
            {"due": [{"claim_id": "S-1", "terminal": "PROVEN"}]}),
            encoding="utf-8")
        assert rag._queue_notes_due(ws, "S-1", "PROVEN") is False
        fresh = yaml.safe_load(due.read_text(encoding="utf-8"))
        assert fresh["due"] == []  # the stale scaffold entry is swept


# ---------------------------------------------- confirmed-with-diff signal

class TestConfirmedWithDiff:
    def test_confirmed_diff_lands_exactly_one_signal_row(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, [])
        _redteam_verdict(ws, "verify-redteam-c7.md", CONFIRMED_DIFF)
        landed = rag._capture_confirmed_with_diff(ws, "C-9")
        assert landed == 1
        signals = (ws / "runs" / "signals.jsonl").read_text(
            encoding="utf-8").splitlines()
        rows = [json.loads(l) for l in signals if l.strip()]
        assert len(rows) == 1
        assert rows[0]["claim"] == "C-7"  # the file's claim tag wins
        assert rows[0]["diffs"] == 2
        # the prose line never counted as a divergence
        # idempotency: a second rollup over the same verdict re-globs the
        # same file and the signal_id dedupe keeps ONE row
        assert rag._capture_confirmed_with_diff(ws, "C-9") == 1
        signals2 = (ws / "runs" / "signals.jsonl").read_text(
            encoding="utf-8").splitlines()
        assert len([l for l in signals2 if l.strip()]) == 1

    def test_clean_confirmed_and_rejected_land_nothing(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, [])
        _redteam_verdict(ws, "verify-redteam-clean.md",
                         "RED-TEAM VERDICT: CONFIRMED\nall clean\n")
        _redteam_verdict(ws, "verify-redteam-rej.md",
                         "RED-TEAM VERDICT: REFUTED\n## DIFF-1\n")
        assert rag._capture_confirmed_with_diff(ws, "C-1") == 0
        assert not (ws / "runs" / "signals.jsonl").exists()

    def test_absent_runs_dir_reads_zero(self, tmp_path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        assert rag._capture_confirmed_with_diff(bare, "C-1") == 0


# ------------------------------------------------- failure skeleton seed

class TestFailureSkeleton:
    def test_proven_seed_is_machine_known_only(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        with (ws / rag.LEDGER_NAME).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "outcome", "claim_id": "C-1",
                                "checker": "red-team",
                                "result": "CONFIRMED"}) + "\n")
        assert rag._seed_failure_analysis(ws, "C-1", "PROVEN") is True
        text = (ws / "analyses" / "failure-C-1.yaml").read_text(
            encoding="utf-8")
        entry = yaml.safe_load(text.split("---\n", 1)[-1])
        assert entry["claim"] == "C-1"
        assert entry["outcome"] == "PROVEN"
        assert entry["what_happened"] == "red-team: CONFIRMED"
        assert entry["trigger_precision"] == {}  # authored later, /reflect
        assert entry["next_method"] == ""

    def test_authored_analysis_is_never_overwritten(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
        authored = ws / "analyses" / "failure-C-1.yaml"
        authored.parent.mkdir()
        authored.write_text("claim: C-1\noutcome: AUTHORED\n",
                            encoding="utf-8")
        assert rag._seed_failure_analysis(ws, "C-1", "PROVEN") is False
        assert "AUTHORED" in authored.read_text(encoding="utf-8")

    def test_non_outcome_statuses_do_not_seed(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "DEFERRED"}])
        assert rag._seed_failure_analysis(ws, "C-1", "DEFERRED") is False
        assert not (ws / "analyses").exists()


# ------------------------------------------------------- sweep + CLI

class TestSweepAndCli:
    def test_pending_reads_register_order_and_skips_done(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, [
            {"id": "C-1", "status": "OPEN"},
            {"id": "C-2", "status": "PROVEN"},
            {"id": "C-3", "status": "NEGATIVE"},
            {"id": "C-4", "status": "REFUTED"},
        ])
        _ledger_rollup_row(ws, "C-3", "NEGATIVE")
        assert rag.pending_terminal_claims(ws) == [("C-2", "PROVEN"),
                                                   ("C-4", "REFUTED")]

    def test_pending_without_register_is_empty(self, tmp_path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        assert rag.pending_terminal_claims(bare) == []

    def test_sweep_summary_contract(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"},
                            {"id": "C-4", "status": "REFUTED"}])
        fired: list[str] = []

        def fake_rollup(workspace, claim_id, terminal_status):
            fired.append(claim_id)
            return {"fired": True, "terminal_status": terminal_status}

        with mock.patch.object(rag, "run_rollup", side_effect=fake_rollup):
            summary = rag.sweep_terminal_claims(ws)
        assert summary["ok"] is True
        assert summary["fired"] == ["C-2", "C-4"]
        assert summary["skipped"] == [] and summary["errors"] == []

    def test_sweep_skips_and_cages_errors_per_claim(self, tmp_path) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"},
                            {"id": "C-4", "status": "REFUTED"}])

        def fake_rollup(workspace, claim_id, terminal_status):
            if claim_id == "C-2":
                return {"fired": False, "reason": "already-rolled-up"}
            raise RuntimeError("ledger on fire")

        with mock.patch.object(rag, "run_rollup", side_effect=fake_rollup):
            summary = rag.sweep_terminal_claims(ws)
        assert summary["ok"] is False
        assert summary["skipped"] == [{"claim_id": "C-2",
                                       "reason": "already-rolled-up"}]
        assert summary["errors"][0]["claim_id"] == "C-4"
        assert "ledger on fire" in summary["errors"][0]["error"]

    def test_sweep_never_raises_on_an_unreadable_register(
            self, tmp_path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(": :\nbad: [", encoding="utf-8")
        summary = rag.sweep_terminal_claims(ws)
        assert summary["ok"] is False
        assert summary["errors"][0]["claim_id"] == "*"

    def test_cli_sweep_dry_run_reports_pending(self, tmp_path,
                                               capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
        rc = rag.main([str(ws), "--sweep-terminal", "--dry-run"])
        assert rc == 0
        assert "would roll up 1 pending terminal claim(s): C-2(PROVEN)" \
            in capsys.readouterr().out

    def test_cli_refuses_flag_mixing_and_incomplete_modes(
            self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
        # a positional claim id is not even a recognized sweep argument
        with pytest.raises(SystemExit) as exc:
            rag.main([str(ws), "--sweep-terminal", "C-2"])
        assert exc.value.code == 2
        assert rag.main([str(ws), "--sweep-terminal",
                         "--status", "PROVEN"]) == 2
        assert rag.main([str(ws)]) == 2  # single-claim mode needs both
        assert "needs <claim-id> and --status" in capsys.readouterr().err

    def test_cli_single_claim_dry_run_and_refusals(self, tmp_path,
                                                   capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
        assert rag.main([str(ws), "C-2", "--status", "PROVEN",
                         "--dry-run"]) == 0
        assert "would rollup C-2 (PROVEN)" in capsys.readouterr().out
        assert rag.main([str(ws), "C-2", "--status", "WIP",
                         "--dry-run"]) == 2
        bare = tmp_path / "bare"
        bare.mkdir()
        assert rag.main([str(bare), "C-2", "--status", "PROVEN"]) == 2
        assert "no claim-register.yaml" in capsys.readouterr().err

    def test_cli_sweep_reports_the_summary(self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
        with mock.patch.object(
                rag, "run_rollup",
                side_effect=lambda w, c, s: {"fired": True,
                                             "terminal_status": s}):
            rc = rag.main([str(ws), "--sweep-terminal"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "rollup sweep: fired=1" in out
