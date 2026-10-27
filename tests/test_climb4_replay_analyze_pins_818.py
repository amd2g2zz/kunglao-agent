#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_replay_analyze_pins_818.py — #818 climb segment 4A.

Behavior pins on REAL fixtures for the two #823 replay/analytics faces the
third climb leg left unmeasured:

  scripts/value_replay.py — the CLI contract (rc 0 write face, rc 64
  missing-workspace face, rc 3 replay-gate FAIL face with the stderr
  guidance, the pass face's stdout marker), the parser hardening faces
  (corrupt verify rows skipped, non-dict rows skipped, absent runs dir),
  the facts/_INDEX.md -> root _INDEX.md fallback, the REFUTED clawback in
  ws_score, and dominant_family over real ledger tool rows (token-split
  family match) with the no-log "none" face.

  scripts/bench_analyze.py — the pre-registered H1-H4 verdict table on
  synthetic two-arm runs (PASS / FAIL / UNDECIDABLE per hypothesis, the
  discordant-pair counts, per-stratum slope signs), the tie-corrected
  Wilcoxon rank arithmetic, the empty/degenerate statistics faces, the
  report formatter, and the main() CLI contract (jsonl intake, --demo,
  --out-dir artifacts, the neither-runs-nor-demo argparse error).

Pin discipline: expectations derive from what each fixture's own machinery
computed — no repo-state literalization, no pinned event counts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bench_analyze as ba  # noqa: E402
import value_replay as vr  # noqa: E402


# ------------------------------------------------------------ fixtures

def _mk_ws(root: Path, claims: list[dict], verifies: list[dict],
           ledger_actions: list[str], depth: str = "standard",
           ledger_tools: list[str] | None = None) -> Path:
    """The same synthetic-workspace shape test_value_replay.py mints, plus
    an optional tool column on the ledger rows for dominant_family."""
    ws = root
    (ws / "facts").mkdir(parents=True)
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    rows = [f"F{i + 1:03d} | {c['status']} | {c['id']} | synthetic"
            for i, c in enumerate(claims)]
    (ws / "facts" / "_INDEX.md").write_text("\n".join(rows) + "\n",
                                            encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"depth": depth, "time_budget_minutes": 60}),
        encoding="utf-8")
    for v in verifies:
        (ws / "runs" / f"verify-{v['fact_id']}-{v['seq']}.json").write_text(
            json.dumps(v["body"]), encoding="utf-8")
    with (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").open(
            "w", encoding="utf-8") as f:
        for a in ledger_actions:
            f.write(json.dumps({"actor": "hook", "action": a, "claim": None,
                                "tool": None, "artifact": None,
                                "duration_ms": None, "exit": None,
                                "detail": None}) + "\n")
        for tool in (ledger_tools or []):
            f.write(json.dumps({"actor": "agent", "action": "tool_call",
                                "claim": None, "tool": tool,
                                "artifact": None, "duration_ms": None,
                                "exit": None, "detail": None}) + "\n")
    return ws


def _claim(cid, status="PROVEN"):
    return {"id": cid, "status": status, "statement": "c2 config extract",
            "evidence_tier_attempted": 1, "promotion_attempts": 0}


def _verify(fact_id, seq, overall):
    return {"fact_id": fact_id, "seq": seq,
            "body": {"fact_id": fact_id, "overall": overall,
                     "l1": {"verdict": "PASS" if overall == "VERIFIED"
                            else "REJECTED"},
                     "l2": {"verdict": "VERIFIED" if overall == "VERIFIED"
                            else "NOT-RUN"}}}


def _run_rows(n_pairs: int = 4, *, n_zero: float = 0.1, o_zero: float = 0.4,
              n_z: int = 1, o_z: int = 0, n_pq: float = 0.8,
              o_pq: float = 0.7, n_tokens: float = 600.0,
              o_tokens: float = 1000.0) -> list[dict]:
    rows = []
    for i in range(n_pairs):
        rows.append({"sample": f"s{i}", "stratum": "S1",
                     "seq_in_stratum": i, "arm": "O", "success": True,
                     "partial_score": 1.0, "z_self": o_z, "tokens": o_tokens,
                     "wall_s": 3600, "timeout": False,
                     "zero_output_share": o_zero, "stall_s": 0,
                     "pq_score": o_pq, "contaminated": False})
        rows.append({"sample": f"s{i}", "stratum": "S1",
                     "seq_in_stratum": i, "arm": "N", "success": True,
                     "partial_score": 1.0, "z_self": n_z, "tokens": n_tokens,
                     "wall_s": 3000, "timeout": False,
                     "zero_output_share": n_zero, "stall_s": 0,
                     "pq_score": n_pq, "contaminated": False})
    return rows


# ============================================ value_replay CLI + parsers

class TestValueReplayCli:
    def test_full_cli_writes_priors_and_pairs(self, tmp_path, capsys) -> None:
        ws = _mk_ws(tmp_path / "cli", [_claim("C-001")],
                    [_verify("F001", 1, "VERIFIED")], [])
        priors_out = tmp_path / "out" / "value-priors.yaml"
        pairs_out = tmp_path / "out" / "pairs.jsonl"
        rc = vr.main([str(ws), "--priors-out", str(priors_out),
                      "--pairs-out", str(pairs_out)])
        assert rc == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["schema"] == vr.SCHEMA
        assert "standard|" in list(printed["buckets"])[0]
        on_disk = yaml.safe_load(priors_out.read_text(encoding="utf-8"))
        assert on_disk["schema"] == vr.SCHEMA
        lines = [json.loads(l) for l in
                 pairs_out.read_text(encoding="utf-8").splitlines()]
        assert [row["claim_id"] for row in lines] == ["C-001"]

    def test_missing_workspace_is_rc64(self, tmp_path, capsys) -> None:
        rc = vr.main([str(tmp_path / "nowhere")])
        assert rc == 64
        assert "workspace not found" in capsys.readouterr().err

    def test_replay_gate_failure_blocks_with_rc3(self, tmp_path, capsys) -> None:
        good = _mk_ws(tmp_path / "g", [_claim("C-001")],
                      [_verify("F001", 1, "VERIFIED")], [])
        bad = _mk_ws(tmp_path / "b", [_claim("C-001")],
                     [_verify("F001", 1, "REJECTED")], [])
        rc = vr.main([str(bad), "--validate-bad", str(good)])
        assert rc == 3
        assert "REPLAY GATE FAILED" in capsys.readouterr().err

    def test_replay_gate_pass_announces_on_stdout(self, tmp_path,
                                                  capsys) -> None:
        good = _mk_ws(tmp_path / "g", [_claim("C-001")],
                      [_verify("F001", 1, "VERIFIED")], [])
        bad = _mk_ws(tmp_path / "b", [_claim("C-001")],
                     [_verify("F001", 1, "REJECTED")], [])
        rc = vr.main([str(good), "--validate-bad", str(bad)])
        assert rc == 0
        assert "replay gate PASS" in capsys.readouterr().out


class TestValueReplayParsers:
    def test_corrupt_verify_rows_are_skipped(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "verify-a-1.json").write_text("{not json",
                                                     encoding="utf-8")
        (ws / "runs" / "verify-b-1.json").write_text(json.dumps([1, 2]),
                                                     encoding="utf-8")
        (ws / "runs" / "verify-c-1.json").write_text(
            json.dumps({"fact_id": "F3", "overall": "VERIFIED"}),
            encoding="utf-8")
        rows = vr.verify_rows(ws)
        assert [r["fact_id"] for r in rows] == ["F3"]

    def test_absent_runs_dir_reads_empty(self, tmp_path) -> None:
        assert vr.verify_rows(tmp_path / "bare") == []
        assert vr.gate_interceptions(tmp_path / "bare") == []
        assert vr.dominant_family(tmp_path / "bare") == "none"

    def test_index_rows_fall_back_to_the_workspace_root(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "_INDEX.md").write_text(
            "F009 | REFUTED | C-2 | note\nnot-a-fact-row\n",
            encoding="utf-8")
        assert vr._index_rows(ws) == [("F009", "REFUTED", "C-2")]

    def test_refuted_claws_back_in_ws_score(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path / "ref",
                    [_claim("C-1"), _claim("C-2", "REFUTED")],
                    [_verify("F001", 1, "VERIFIED")], [])
        score = vr.ws_score(ws)
        # C-1 supported proven (+10) and C-2 refuted (−10) share no claim
        # bucket — the totals must expose the clawback arithmetic.
        assert score["per_claim"]["C-1"] == pytest.approx(vr.REWARD_PROVEN)
        assert score["per_claim"]["C-2"] == pytest.approx(vr.REWARD_REFUTED)
        assert score["total"] == pytest.approx(
            vr.REWARD_PROVEN + vr.REWARD_REFUTED)

    def test_dominant_family_reads_ledger_tool_rows(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path / "fam", [_claim("C-1")],
                    [], [], ledger_tools=["mcp__ghidra__import_file",
                                          "mcp__ghidra__decompile",
                                          "rev-frida"])
        # two ghidra rows beat the one frida row: the dominant family is
        # the ghidra token family, matched by part-split (never substring)
        assert vr.dominant_family(ws) == "ghidra"

    def test_corrupt_ledger_lines_do_not_crash_the_family_scan(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path / "fam2", [_claim("C-1")], [], [])
        with (ws / "runs" / "logs" / "kunglao-broken.jsonl").open(
                "a", encoding="utf-8") as f:
            f.write("not-json\n")
        assert vr.dominant_family(ws) == "none"


# ============================================ bench_analyze verdict table

class TestBenchStatistics:
    def test_mcnemar_no_discordant_pairs_is_one(self) -> None:
        assert ba.mcnemar_exact(0, 0) == 1.0

    def test_wilcoxon_empty_input_reads_no_effect(self) -> None:
        assert ba.wilcoxon_signed_rank([], []) == (1.0, 0.0)

    def test_wilcoxon_all_ties_degenerate_sigma_reads_one(self) -> None:
        # identical lists drop every diff -> n=0 face, not the sigma face
        p, w = ba.wilcoxon_signed_rank([4, 4], [4, 4])
        assert (p, w) == (1.0, 0.0)

    def test_wilcoxon_tie_ranks_split_the_rank_credit(self) -> None:
        # diffs +1, +1, -2 -> abs ranks 1.5, 1.5, 3.0; W+ = 3.0
        p, w = ba.wilcoxon_signed_rank([2, 3, 1], [1, 2, 3])
        assert w == pytest.approx(3.0)
        assert 0.0 < p <= 1.0

    def test_summarize_empty_arm_rows_degrade_to_zero(self) -> None:
        stats = ba.summarize([])
        assert stats["pairs"] == 0
        for arm in ba.ARMS:
            assert stats["arms"][arm]["n"] == 0
            assert stats["arms"][arm]["success_rate"] == 0.0
            assert stats["arms"][arm]["token_median"] == 0.0

    def test_summarize_counts_contaminated_rows(self) -> None:
        rows = _run_rows()
        rows[1]["contaminated"] = True
        stats = ba.summarize(rows)
        assert stats["arms"]["N"]["contaminated"] == 1
        # contamination flags, never removes: the row stays in the counts
        assert stats["arms"]["N"]["n"] == 4

    def test_paired_missing_field_defaults_to_zero(self) -> None:
        rows = _run_rows()
        for r in rows:
            r.pop("pq_score")
        o, n = ba._paired(rows, "pq_score")
        assert o == [0.0] * 4 and n == [0.0] * 4


class TestBenchHypotheses:
    def test_h1_pass_when_n_halves_o(self) -> None:
        v = ba.hypotheses(_run_rows())["H1"]
        assert v["verdict"] == "PASS"
        assert v["test"] == "wilcoxon"
        assert v["mean_N"] < v["mean_O"] * ba.H1_RATIO

    def test_h1_fail_when_n_stays_high(self) -> None:
        v = ba.hypotheses(_run_rows(n_zero=0.5, o_zero=0.6))["H1"]
        assert v["verdict"] == "FAIL"
        assert v["mean_N"] >= v["mean_O"] * ba.H1_RATIO

    def test_h1_undecidable_without_pairs(self) -> None:
        rows = [r for r in _run_rows() if r["arm"] == "O"]
        assert ba.hypotheses(rows)["H1"] == {
            "verdict": "UNDECIDABLE", "p": None}

    def test_h2_pass_only_when_every_n_slope_is_negative(self) -> None:
        # N tokens decay across the stratum sequence; O tokens grow
        rows = []
        for i in range(4):
            rows.append({"sample": f"s{i}", "stratum": "S1",
                         "seq_in_stratum": i, "arm": "O", "success": True,
                         "tokens": 1000 + 100 * i, "timeout": False,
                         "z_self": 0, "zero_output_share": 0.4,
                         "pq_score": 0.7, "contaminated": False})
            rows.append({"sample": f"s{i}", "stratum": "S1",
                         "seq_in_stratum": i, "arm": "N", "success": True,
                         "tokens": 900 - 100 * i, "timeout": False,
                         "z_self": 1, "zero_output_share": 0.1,
                         "pq_score": 0.8, "contaminated": False})
        v = ba.hypotheses(rows)["H2"]
        assert v["verdict"] == "PASS"
        assert v["slopes"]["S1/N"] < 0 < v["slopes"]["S1/O"]

    def test_h2_fail_on_a_flat_n_arm(self) -> None:
        rows = _run_rows()
        assert ba.hypotheses(rows)["H2"]["verdict"] == "FAIL"

    def test_h3_follows_the_z_rate_direction(self) -> None:
        better = ba.hypotheses(_run_rows(n_z=1, o_z=0))["H3"]
        assert better["verdict"] == "PASS"
        assert better["rate_N"] > better["rate_O"]
        assert better["discordant"]["O_fail_N_pass"] == 4

        worse = ba.hypotheses(_run_rows(n_z=0, o_z=1))["H3"]
        assert worse["verdict"] == "FAIL"
        assert worse["discordant"]["O_pass_N_fail"] == 4

    def test_h3_undecidable_without_pairs(self) -> None:
        rows = [r for r in _run_rows() if r["arm"] == "N"]
        assert ba.hypotheses(rows)["H3"] == {
            "verdict": "UNDECIDABLE", "p": None}

    def test_h4_margin_decision(self) -> None:
        within = ba.hypotheses(_run_rows(n_pq=0.7, o_pq=0.72))["H4"]
        assert within["verdict"] == "PASS"
        beyond = ba.hypotheses(_run_rows(n_pq=0.5, o_pq=0.8))["H4"]
        assert beyond["verdict"] == "FAIL"
        assert beyond["margin"] == ba.H4_MARGIN

    def test_h4_undecidable_without_pairs(self) -> None:
        rows = [r for r in _run_rows() if r["arm"] == "O"]
        assert ba.hypotheses(rows)["H4"] == {
            "verdict": "UNDECIDABLE", "p": None}


class TestBenchReportAndCli:
    def test_report_renders_both_lenses_and_all_verdicts(self) -> None:
        stats = ba.summarize(_run_rows())
        verdicts = ba.hypotheses(_run_rows())
        report = ba.format_report(stats, verdicts)
        assert "pairs: 4" in report
        for arm in ba.ARMS:
            assert f"- {arm}: n=4" in report
            assert "done-only" in report
        for h in ("H1", "H2", "H3", "H4"):
            assert f"- {h}: " in report
        assert "never buried" in report

    def test_cli_demo_writes_the_artifact_pair(self, tmp_path, capsys) -> None:
        out_dir = tmp_path / "analysis"
        rc = ba.main(["--demo", "--seed", "11",
                      "--out-dir", str(out_dir)])
        assert rc == 0
        assert "AB-VALUE run analysis" in capsys.readouterr().out
        report = (out_dir / "report.md").read_text(encoding="utf-8")
        summary = json.loads(
            (out_dir / "runs-summary.json").read_text(encoding="utf-8"))
        assert "H1" in report and "never buried" in report
        assert set(summary["verdicts"]) == {"H1", "H2", "H3", "H4"}
        assert summary["stats"]["pairs"] > 0

    def test_cli_jsonl_intake_matches_the_inprocess_result(
            self, tmp_path) -> None:
        rows = _run_rows()
        runs_file = tmp_path / "runs.jsonl"
        runs_file.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        out_dir = tmp_path / "out"
        rc = ba.main([str(runs_file), "--out-dir", str(out_dir)])
        assert rc == 0
        summary = json.loads(
            (out_dir / "runs-summary.json").read_text(encoding="utf-8"))
        assert summary["stats"] == ba.summarize(rows)
        assert summary["verdicts"] == ba.hypotheses(rows)

    def test_cli_blank_lines_in_runs_jsonl_are_skipped(self, tmp_path) -> None:
        runs_file = tmp_path / "runs.jsonl"
        rows = _run_rows(n_pairs=1)
        runs_file.write_text(
            json.dumps(rows[0]) + "\n\n" + json.dumps(rows[1]) + "\n",
            encoding="utf-8")
        rc = ba.main([str(runs_file)])
        assert rc == 0

    def test_cli_without_runs_or_demo_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            ba.main([])
        assert exc.value.code == 2
