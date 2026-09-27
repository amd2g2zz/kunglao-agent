# -*- coding: utf-8 -*-
"""tests/test_reward_settlement_366.py — the ONE settlement engine (U2/U3).

Acceptance checkboxes covered here:
  - every reward band constructible from synthetic signal sets;
  - single-signal rows pinned NEUTRAL;
  - rule_id + evidence_refs present on every settled row (audit trail);
  - no model opinion ever settles a reward (import-surface test);
  - reward-rules.yaml validity + version pin.
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"


def _sig(type_: str, source: str, value, ts="2026-09-24T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


def _seed(ws: Path, kind: str, anchor: str, signals: list[dict]) -> str:
    rl.record(ws, kind=kind, anchor=anchor, signals=signals)
    return f"{kind}/{anchor}"


# ---------- rules file validity ----------

class TestRulesFile:
    def test_rules_file_exists_and_versions(self):
        doc = rs.load_rules(RULES_PATH)
        assert doc["schema"] == "reward-rules/1"
        assert isinstance(doc["version"], int) and doc["version"] >= 1

    def test_every_rule_declares_band_reward_and_evidence(self):
        doc = rs.load_rules(RULES_PATH)
        for rule in doc["rules"]:
            assert rule["rule_id"]
            assert rule["band"] in rs.BANDS
            assert "reward" in rule
            assert rule.get("requires"), f"{rule['rule_id']} needs requires"
            assert len(rule["requires"]) >= 2, (
                f"{rule['rule_id']}: no single-signal rules "
                f"(multi-signal anti-pollution)")

    def test_task_green_never_demoted(self):
        doc = rs.load_rules(RULES_PATH)
        green = next(r for r in doc["rules"]
                     if r["rule_id"] == "task/oracle-green")
        assert green.get("never_demoted") is True

    def test_all_declared_kinds_registered_in_ledger(self):
        doc = rs.load_rules(RULES_PATH)
        for rule in doc["rules"]:
            kinds = rule["kind"] if isinstance(rule["kind"], list) \
                else [rule["kind"]]
            for k in kinds:
                assert k in rl.ROLLOUT_KINDS, (
                    f"{rule['rule_id']}: kind {k!r} not registered")


# ---------- band construction from synthetic signal sets ----------

class TestBandConstruction:
    def test_task_green_band(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "task", "C-1",
                    [_sig("oracle_verdict", "oracle_runner", "pass"),
                     _sig("claim_terminal", "convergence_check", "PROVEN")])
        res = rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert res["settled"] == 1
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "SETTLED_GREEN"
        assert row["settlement"]["reward"] == 1.0
        assert row["settlement"]["rule_id"] == "task/oracle-green"
        assert row["reward"] == 1.0

    def test_task_red_band(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "task", "C-2",
                    [_sig("oracle_verdict", "oracle_runner", "fail"),
                     _sig("claim_terminal", "convergence_check", "NEGATIVE")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "SETTLED_RED"
        assert row["settlement"]["reward"] == 0.0

    def test_distill_adverse_band_needs_all_three_legs(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        # two of three adverse legs -> NOT adverse, still NEUTRAL
        rid = _seed(ws, "self_distill", "lesson-a",
                    [_sig("misleading_declaration", "red-team", True),
                     _sig("zero_recall", "recall_metrics", True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert rl.fold(ws, rid)["settlement"]["band"] == "NEUTRAL"
        # the third leg lands -> ADVERSE
        rl.record(ws, kind="self_distill", anchor="lesson-a",
                  signals=[_sig("misleading_declaration", "red-team", True),
                           _sig("zero_recall", "recall_metrics", True),
                           _sig("no_citation", "lessons_telemetry", True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "ADVERSE"
        assert row["settlement"]["reward"] == 0.0

    def test_distill_helped_band_base(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "self_distill", "lesson-b",
                    [_sig("distill_consumption", "distill_engine", 1),
                     _sig("downstream_positive_reference",
                          "convergence_check", True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "HELPED"
        assert row["settlement"]["reward"] == 0.5

    def test_distill_helped_full_corroboration_reaches_1(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "hybrid_distill", "card-1",
                    [_sig("distill_consumption", "distill_engine", 2),
                     _sig("downstream_positive_reference",
                          "convergence_check", True),
                     _sig("distill_reuse", "distill_engine", 2)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "HELPED"
        assert row["settlement"]["reward"] == 1.0

    def test_adverse_beats_helped_on_contradictory_rows(self, tmp_path):
        """Conservative tie-break: adverse requires the strongest evidence
        and wins when a row somehow carries both spectra (declared order)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "self_distill", "lesson-c",
                    [_sig("misleading_declaration", "red-team", True),
                     _sig("zero_recall", "recall_metrics", True),
                     _sig("no_citation", "lessons_telemetry", True),
                     _sig("distill_consumption", "distill_engine", 1),
                     _sig("downstream_positive_reference",
                          "convergence_check", True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert rl.fold(ws, rid)["settlement"]["band"] == "ADVERSE"


# ---------- single-signal anti-pollution pin ----------

class TestSingleSignalNeutralPin:
    def test_single_signal_row_settles_neutral(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "task", "C-7",
                    [_sig("oracle_verdict", "oracle_runner", "pass")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "NEUTRAL"
        assert row["settlement"]["reward"] == 0.0

    def test_every_single_machine_signal_alone_is_neutral(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        singles = [
            ("task", "C-10", _sig("claim_terminal", "convergence_check", "PROVEN")),
            ("task", "C-11", _sig("redteam_confirmed", "verify", True)),
            ("self_distill", "lesson-d", _sig("lesson_written", "rollup", "sig")),
            ("self_distill", "lesson-e", _sig("distill_consumption", "distill_engine", 3)),
            ("self_distill", "lesson-f", _sig("no_citation", "lessons_telemetry", True)),
        ]
        for kind, anchor, sig in singles:
            _seed(ws, kind, anchor, [sig])
        res = rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert res["settled"] == len(singles)
        for kind, anchor, _ in singles:
            row = rl.fold(ws, f"{kind}/{anchor}")
            assert row["settlement"]["band"] == "NEUTRAL", anchor
            assert row["settlement"]["rule_id"].endswith("/pending"), anchor

    def test_model_advisory_signal_never_settles_anything(self, tmp_path):
        """U3: a model-judged score enters only as an advisory INPUT signal;
        advisory signals are excluded from rule matching by construction."""
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "self_distill", "lesson-g",
                    [_sig("quality_score", "model", 0.97, advisory=True),
                     _sig("quality_score", "model", 0.93, advisory=True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "NEUTRAL"

    def test_advisory_plus_one_machine_signal_still_neutral(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "task", "C-12",
                    [_sig("quality_score", "model", 1.0, advisory=True),
                     _sig("claim_terminal", "convergence_check", "PROVEN")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert rl.fold(ws, rid)["settlement"]["band"] == "NEUTRAL"

    def test_no_rule_grants_a_band_via_advisory_signal(self, tmp_path):
        """The rules table itself must not name any advisory-capable model
        source as a required signal producer (whitelisted positions only)."""
        doc = rs.load_rules(RULES_PATH)
        for rule in doc["rules"]:
            for pred in (rule.get("requires") or []) + \
                        (rule.get("optional") or []):
                assert "model" not in str(pred.get("source", "")).lower()


# ---------- audit trail ----------

class TestAuditTrail:
    def test_every_settled_row_carries_rule_id_and_evidence_refs(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-20",
              [_sig("oracle_verdict", "oracle_runner", "pass"),
               _sig("claim_terminal", "convergence_check", "PROVEN")])
        _seed(ws, "self_distill", "lesson-h",
              [_sig("lesson_written", "rollup", "sig-h")])
        _seed(ws, "self_distill", "lesson-i",
              [_sig("misleading_declaration", "red-team", True),
               _sig("zero_recall", "recall_metrics", True),
               _sig("no_citation", "lessons_telemetry", True)])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        for row in rl.settled(ws):
            assert row["settlement"]["rule_id"], row["rollout_id"]
            refs = row["settlement"]["evidence_refs"]
            assert isinstance(refs, list) and refs, row["rollout_id"]

    def test_neutral_rows_cite_their_observed_signals(self, tmp_path):
        """The NEUTRAL audit answers 'why neutral': the signals that were
        present but insufficient."""
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = _seed(ws, "task", "C-21",
                    [_sig("oracle_verdict", "oracle_runner", "pass")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        refs = rl.fold(ws, rid)["settlement"]["evidence_refs"]
        assert any("oracle_verdict" in r for r in refs)

    def test_settlement_is_idempotent(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-22",
              [_sig("oracle_verdict", "oracle_runner", "pass"),
               _sig("claim_terminal", "convergence_check", "PROVEN")])
        a = rs.settle_workspace(ws, rules_path=RULES_PATH)
        b = rs.settle_workspace(ws, rules_path=RULES_PATH)
        assert a["settled"] == 1 and b["settled"] == 0
        assert len(rl.read(ws)) == 2  # identity + one amendment only


# ---------- U3: settlement engine has NO model-call path ----------

class TestNoModelCallPath:
    IMPORT_ALLOWLIST = {
        "__future__", "json", "sys", "os", "re", "time",
        "datetime", "pathlib", "typing", "yaml",
        "rollout_ledger", "harness_common", "kunglao_log",
        "outcome_capture", "failure_analysis_gate",
    }
    FORBIDDEN_FRAGMENTS = (
        "llm", "model", "judge", "score_", "anthropic", "openai",
        "claude", "gpt", "completion", "subprocess", "socket",
        "urllib", "http", "requests", "popen", "eval_loop",
        "eval_targets", "verdict_layer",
    )

    def _imports(self) -> list[str]:
        tree = ast.parse(
            (SCRIPTS / "reward_settlement.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        return imported

    def test_import_surface_is_allowlisted(self):
        imported = self._imports()
        outside = [m for m in imported
                   if m.split(".")[0] not in self.IMPORT_ALLOWLIST]
        assert not outside, f"settlement engine imports outside allowlist: {outside}"

    def test_import_surface_has_no_model_call_fragments(self):
        bad = [m for m in self._imports()
               for frag in self.FORBIDDEN_FRAGMENTS
               if frag in m.lower()]
        assert not bad, f"model-call surface inside settlement engine: {bad}"

    def test_engine_source_has_no_exec_escape_hatches(self):
        text = (SCRIPTS / "reward_settlement.py").read_text(encoding="utf-8")
        for needle in ("subprocess", "os.system", "popen", "eval(",
                       "exec(", "__import__", "importlib"):
            assert needle not in text, needle


# ---------- determinism ----------

class TestDeterminism:
    def test_same_signals_same_settlement(self, tmp_path):
        sigs = [_sig("oracle_verdict", "oracle_runner", "pass"),
                _sig("claim_terminal", "convergence_check", "PROVEN")]
        out = []
        for name in ("ws1", "ws2"):
            ws = tmp_path / name
            ws.mkdir()
            rl.record(ws, kind="task", anchor="C-1", signals=sigs)
            rs.settle_workspace(ws, rules_path=RULES_PATH)
            out.append(rl.fold(ws, "task/C-1")["settlement"])
        assert out[0] == out[1]
