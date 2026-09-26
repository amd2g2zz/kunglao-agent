# -*- coding: utf-8 -*-
"""tests/test_gap_notes_391.py — settlement-event retry gap-notes (issue 391).

Acceptance checkboxes covered here (write face + anti-pollution):
  - FAIL settlement (task kind, negative band or tier RED) -> one structured
    gap-note XML file derived ONLY from machine-recorded signals (oracle
    verdict + checker sub-scores, decoy/misleading-declaration markers,
    evidence_class, cost vs the unit-class reference);
  - PASS settlements emit nothing (only failures reflect);
  - NEUTRAL-pending and non-task kinds emit nothing;
  - idempotent per settlement (signals-digest-named file, re-run skips);
  - a retry attempt (grown signals -> re-settled) adds a SECOND note;
  - citation granularity: the note cites concrete artifacts (refuted fact
    file paths, per-face probe sub-scores, cost ratio) — not round summaries;
  - ANTI-POLLUTION (hard invariant): the settlement rule matcher provably
    ignores advisory gap-note carriers (classify + classify_tier unchanged);
    gap-note emission never writes ledger rows (byte-prefix invariant).
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402
import scalar_settlement as ss  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"
RULES_DOC = rs.load_rules(RULES_PATH)
COST_REF = RULES_DOC.get("cost_reference") or {}


def _sig(type_: str, source: str, value, ts="2026-09-26T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


def _seed(ws: Path, kind: str, anchor: str, signals: list[dict]) -> str:
    rl.record(ws, kind=kind, anchor=anchor, signals=signals)
    return f"{kind}/{anchor}"


def _fail_signals(cost=45.0) -> list[dict]:
    """A machine-shaped FAILED attempt: oracle fail + checker sub-scores +
    decoy wall + asserted-only evidence + expensive cost."""
    return [
        _sig("claim_terminal", "convergence_check", "NEGATIVE"),
        _sig("oracle_verdict", "oracle_runner", "fail"),
        _sig("static_probes", "eval_checker", {"passed": 1, "total": 3}),
        _sig("replay_probes", "eval_checker", {"passed": 0, "total": 2}),
        _sig("dense_layers", "eval_chain_grader",
             {"completed": 2, "total": 5}),
        _sig("evidence_class", "rerun_discipline", "asserted"),
        _sig("misleading_declaration", "oracle_runner", True),
        _sig("session_cost", "cost_telemetry", cost),
        _sig("unit_class", "strategy_arm", "loop"),
    ]


def _pass_signals() -> list[dict]:
    return [
        _sig("claim_terminal", "convergence_check", "PROVEN"),
        _sig("oracle_verdict", "oracle_runner", "pass"),
    ]


def _settle_fail(ws: Path, anchor: str = "C-391") -> str:
    rid = _seed(ws, "task", anchor, _fail_signals())
    rs.settle_workspace(ws, rules_path=RULES_PATH)
    return rid


def _note_files(ws: Path) -> list[Path]:
    base = ws / "runs" / "gap-notes"
    return sorted(base.rglob("*.xml")) if base.is_dir() else []


# ---------- write face: FAIL -> one structured gap-note ----------

class TestWriteFace:
    def test_fail_settlement_writes_gap_note(self, tmp_path):
        """FAIL settlement -> exactly one gap-note XML, advisory-marked,
        derived from the machine signals of that rollout."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        res = gn.emit_gap_notes(ws)
        assert res["emitted"] == 1
        files = _note_files(ws)
        assert len(files) == 1
        root = ET.fromstring(files[0].read_text(encoding="utf-8"))
        assert root.tag == "gap-note"
        assert root.get("schema") == "gap-note/1"
        assert root.get("advisory") == "true"
        assert root.get("unit") == "C-391"
        assert root.get("rollout_id") == "task/C-391"
        assert root.get("kind") == "task"
        oracle = root.find("oracle")
        assert oracle is not None
        assert oracle.get("verdict") == "fail"
        assert oracle.get("band") == "SETTLED_RED"
        assert oracle.get("rule_id") == "task/oracle-red"

    def test_note_carries_checker_sub_scores(self, tmp_path):
        """Checker sub-scores land per-face: static X/Y, replay N/M, dense
        layers — the mechanical progress the next attempt must beat."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        root = ET.fromstring(
            _note_files(ws)[0].read_text(encoding="utf-8"))
        probes = root.find("probes")
        assert probes is not None
        assert probes.get("static") == "1/3"
        assert probes.get("replay") == "0/2"
        assert probes.get("dense_layers") == "2/5"

    def test_note_carries_decoy_markers_and_evidence_class(self, tmp_path):
        """Decoy / misleading-declaration markers and the artifacts'
        evidence_class are cited verbatim from the recorded signals."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        root = ET.fromstring(
            _note_files(ws)[0].read_text(encoding="utf-8"))
        markers = [(m.get("type"), m.get("value"))
                   for m in root.findall("./decoys/marker")]
        assert ("misleading_declaration", "True") in markers
        ev = [(s.get("type"), s.get("value"))
              for s in root.findall("./evidence/signal")]
        assert ("evidence_class", "asserted") in ev

    def test_note_cites_cost_against_unit_class_reference(self, tmp_path):
        """Cost dim cites session spend vs the unit-class reference
        (loop median 10.0, k=3): 45.0 -> ratio 4.5, expensive true."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        root = ET.fromstring(
            _note_files(ws)[0].read_text(encoding="utf-8"))
        cost = root.find("cost")
        assert cost is not None
        assert cost.get("session_cost") == "45.0"
        assert cost.get("class_median") == "10.0"
        assert float(cost.get("ratio")) == pytest.approx(4.5)
        assert cost.get("expensive") == "true"

    def test_note_cites_concrete_refuted_artifacts(self, tmp_path):
        """Citation granularity: refuted fact files are cited by concrete
        path — actionable tool-call-level evidence, not a round summary."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        facts = ws / "facts"
        facts.mkdir()
        (facts / "F391-a.md").write_text(
            "---\nid: F391-a\nstatus: REFUTED\n---\n\nsynthetic body\n",
            encoding="utf-8")
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        root = ET.fromstring(
            _note_files(ws)[0].read_text(encoding="utf-8"))
        paths = [a.get("path") for a in root.findall("./artifacts/artifact")]
        assert "facts/F391-a.md" in paths
        refs_text = "\n".join(r.text or ""
                              for r in root.findall("./refs/ref"))
        # the settlement's own per-signal citations are carried too
        assert "oracle_verdict" in refs_text

    def test_note_carries_settlement_evidence_refs(self, tmp_path):
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        root = ET.fromstring(
            _note_files(ws)[0].read_text(encoding="utf-8"))
        refs = [r.text for r in root.findall("./refs/ref")]
        assert refs, "the settlement audit trail must be carried"


# ---------- only failures reflect ----------

class TestOnlyFailuresReflect:
    def test_pass_settlement_emits_nothing(self, tmp_path):
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-404", _pass_signals())
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        res = gn.emit_gap_notes(ws)
        assert res["emitted"] == 0
        assert _note_files(ws) == []

    def test_neutral_pending_emits_nothing(self, tmp_path):
        """A single-signal row lands NEUTRAL (pending) — pending is not a
        FAIL settlement, it reflects nothing."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-405",
              [_sig("oracle_verdict", "oracle_runner", "fail")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        gn.emit_gap_notes(ws)
        assert _note_files(ws) == []

    def test_non_task_kinds_emit_nothing(self, tmp_path):
        """Only task-kind rollouts reflect; an ADVERSE self_distill row is
        not a task-kind FAIL settlement."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "self_distill", "lesson-x", [
            _sig("misleading_declaration", "recall_telemetry", True),
            _sig("zero_recall", "recall_telemetry", True),
            _sig("no_citation", "lessons_telemetry", True),
        ])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        gn.emit_gap_notes(ws)
        assert _note_files(ws) == []

    def test_emit_is_idempotent(self, tmp_path):
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        first = gn.emit_gap_notes(ws)
        assert first["emitted"] == 1
        again = gn.emit_gap_notes(ws)
        assert again["emitted"] == 0
        assert again["skipped_existing"] == 1
        assert len(_note_files(ws)) == 1

    def test_retry_attempt_grows_a_second_note(self, tmp_path):
        """Attempt N sees attempts 1..N-1: grown signals re-settle the
        rollout (new signals digest) and the emit face writes a SECOND
        note; the read face returns both in stable file order."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        gn.emit_gap_notes(ws)
        grown = _fail_signals() + [
            _sig("redteam_confirmed", "outcome_capture", True,
                 ts="2026-09-26T06:00:00Z")]
        rl.record(ws, kind="task", anchor="C-391", signals=grown)
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        res = gn.emit_gap_notes(ws)
        assert res["emitted"] == 1
        notes = gn.read_notes(ws, "C-391")
        assert len(notes) == 2
        labels = [label for label, _ in notes]
        assert labels == sorted(labels), "stable ascending file order"


# ---------- anti-pollution (hard invariant) ----------

class TestAntiPollution:
    def test_rule_matcher_ignores_advisory_gap_note_carrier(self):
        """THE pin: an advisory gap-note carrier in the signal set can
        change nothing in the settlement matcher — classify and
        classify_tier are byte-identical with and without it."""
        base = [_sig("claim_terminal", "convergence_check", "NEGATIVE"),
                _sig("oracle_verdict", "oracle_runner", "fail")]
        carried = base + [_sig("gap_note", "gap_notes",
                               "<gap-note advisory='true'/>",
                               advisory=True)]
        a = rs.classify("task", base, RULES_DOC)
        b = rs.classify("task", carried, RULES_DOC)
        assert a["band"] == b["band"] == "SETTLED_RED"
        assert a["reward"] == b["reward"] == 0.0
        assert a["rule_id"] == b["rule_id"] == "task/oracle-red"
        # the tier engine needs corroborated dims for RED — use a
        # zero-progress fail set; the advisory carrier changes nothing
        tier_base = [_sig("claim_terminal", "convergence_check", "NEGATIVE"),
                     _sig("oracle_verdict", "oracle_runner", "fail"),
                     _sig("evidence_class", "rerun_discipline", "asserted"),
                     _sig("session_cost", "cost_telemetry", 45.0),
                     _sig("unit_class", "strategy_arm", "loop")]
        carrier = carried[-1]
        ta = ss.classify_tier(tier_base, RULES_DOC.get("tier_table")
                              or {}, COST_REF)
        tb = ss.classify_tier(tier_base + [carrier],
                              RULES_DOC.get("tier_table") or {}, COST_REF)
        assert ta["tier"] == tb["tier"] == "RED"
        assert ta["tier_reward"] == tb["tier_reward"]
        assert ta["tier_rule_id"] == tb["tier_rule_id"]

    def test_advisory_carrier_cannot_settle_green_alone(self):
        """Not even a forged advisory PASS note moves a verdict-less row
        out of NEUTRAL — advisory is excluded before rule matching."""
        rules = RULES_DOC
        carried = [_sig("gap_note", "gap_notes",
                        "<gap-note>oracle pass</gap-note>",
                        advisory=True),
                   _sig("claim_terminal", "convergence_check", "PROVEN")]
        out = rs.classify("task", carried, rules)
        assert out["band"] == "NEUTRAL"
        assert out["rule_id"] == "task/pending"

    def test_emit_never_writes_ledger_rows(self, tmp_path):
        """Gap-notes live OUTSIDE the ledger: emission leaves the ledger
        byte-prefix invariant and adds no rows to any read face."""
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        _settle_fail(ws)
        ledger = ws / "runs" / "rollout-ledger.jsonl"
        before = ledger.read_bytes()
        rows_before = rl.read(ws)
        gn.emit_gap_notes(ws)
        assert ledger.read_bytes() == before
        assert rl.read(ws) == rows_before

    def test_gap_note_module_import_surface_has_no_model_call_path(self):
        """U3 posture for the write face: the import surface is
        allowlisted, no escape hatches — notes are ledger-derived only."""
        ALLOW = {"__future__", "json", "sys", "re", "pathlib",
                 "xml", "rollout_ledger", "reward_settlement",
                 "scalar_settlement", "harness_common", "kunglao_log"}
        tree = ast.parse(
            (SCRIPTS / "gap_notes.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        outside = [m for m in imported if m.split(".")[0] not in ALLOW]
        assert not outside, \
            f"gap_notes imports outside allowlist: {outside}"
        text = (SCRIPTS / "gap_notes.py").read_text(encoding="utf-8")
        for needle in ("subprocess", "os." + "system", "__import__",
                       "importlib", "urllib", "socket"):
            assert needle not in text, needle


# ---------- read face (ledger-side helpers) ----------

class TestReadFaceHelpers:
    def test_read_notes_unknown_unit_empty(self, tmp_path):
        import gap_notes as gn
        ws = tmp_path / "ws"
        ws.mkdir()
        assert gn.read_notes(ws, "C-000") == []

    def test_sanitize_unit_rejects_traversal(self):
        import gap_notes as gn
        assert "/" not in gn.sanitize_unit("../../etc")
        assert gn.sanitize_unit("..") not in ("", ".", "..")
