# -*- coding: utf-8 -*-
"""tests for the online distillation engine (scripts/online_distill.py).

The engine's five organs, unit-pinned per the online-distillation spec:
  - trigger scan: the two (and only two) mechanical miss signals;
  - budget ledger: per-run act cap, per-run hop budget, engine-minted
    run identity, never-loosen clamp, fail-closed corruption;
  - report validation: methodology-first sources, hard expansion caps;
  - sample-as-oracle: anchored-sample resolution, engine-run bytes;
  - tier-1 landing: tools-local + provenance manifest, no global face.

The engine module is stdlib-only and workspace-relative; every test
builds a throwaway workspace under tmp_path.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import online_distill as od  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def write_marker(ws: Path, name: str, token: str, sample: str | None = None,
                 mtime: float | None = None) -> Path:
    p = ws / "runs" / name
    line = f"shelf-miss: {token}"
    if sample:
        line += f" sample={sample}"
    p.write_text("# worker status (fixture)\nstatus: DONE\n"
                 f"{line}\n", encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# ---------------------------------------------------------------------------
# trigger scan
# ---------------------------------------------------------------------------


class TestTriggerScan:
    def test_marker_parses_token_and_sample_hint(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_marker(ws, "worker-status-C-004.md", "crypto:decode",
                     sample="target/blob.bin")
        triggers = od.scan_triggers(ws)
        assert len(triggers) == 1
        t = triggers[0]
        assert t.kind == "shelf-miss"
        assert t.token == "crypto:decode"
        assert t.sample_hint == "target/blob.bin"
        assert t.source_file == "runs/worker-status-C-004.md"

    def test_marker_without_sample_hint(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_marker(ws, "worker-status-C-004.md", "static:disasm")
        (t,) = od.scan_triggers(ws)
        assert t.sample_hint is None

    def test_no_marker_no_trigger(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "worker-status-C-004.md").write_text(
            "# worker status\nstatus: DONE\n", encoding="utf-8")
        assert od.scan_triggers(ws) == []

    def test_malformed_marker_ignored(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "worker-status-C-004.md").write_text(
            "shelf-miss:\nshelf-miss:   \nshelfmiss: x\n", encoding="utf-8")
        assert od.scan_triggers(ws) == []

    def test_marker_must_be_own_line_token_shape(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "worker-status-C-004.md").write_text(
            "discussed a shelf-miss: but this is prose with spaces\n",
            encoding="utf-8")
        assert od.scan_triggers(ws) == []

    def test_stale_mtime_marker_skipped(self, tmp_path):
        ws = mk_ws(tmp_path)
        old = time.time() - 10_000
        write_marker(ws, "worker-status-old.md", "crypto:decode", mtime=old)
        recent = time.time()
        triggers = od.scan_triggers(ws, mtime_floor=recent - 60)
        assert triggers == []

    def test_consumed_marker_file_skipped(self, tmp_path):
        ws = mk_ws(tmp_path)
        marker = write_marker(ws, "worker-status-C-004.md", "crypto:decode")
        assert od.reserve_act(ws, "crypto:decode",
                              source_file="runs/worker-status-C-004.md")
        assert marker.is_file()
        triggers = od.scan_triggers(ws)
        assert all(t.token != "crypto:decode" for t in triggers)

    def test_die_json_unknown_language_triggers(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "_meta": {"source": "die", "tool": "DIE diec.exe (5-call merge)"},
            "detects": [{"type": "unknown", "name": "unknown"}],
            "derived": {"language": None, "detected_packer": None},
            "call_errors": {},
        }), encoding="utf-8")
        (t,) = od.scan_triggers(ws)
        assert t.kind == "format-unknown"
        assert t.token == "format:unknown:evidence/die.json"

    def test_die_json_known_language_no_trigger(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "_meta": {"source": "die", "tool": "DIE diec.exe (5-call merge)"},
            "detects": [{"type": "compiler", "name": "Go"}],
            "derived": {"language": "Go", "detected_packer": None},
            "call_errors": {},
        }), encoding="utf-8")
        assert od.scan_triggers(ws) == []

    def test_die_json_all_calls_failed_is_no_signal(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "_meta": {"source": "die"},
            "detects": [],
            "derived": {"language": None, "detected_packer": None},
            "call_errors": {"c1": "timeout", "c2": "timeout", "c3": "x",
                            "c4": "x", "c5": "x"},
        }), encoding="utf-8")
        assert od.scan_triggers(ws) == []

    def test_apkid_ok_empty_findings_triggers(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "status": "ok", "findings": [], "summary": ""}),
            encoding="utf-8")
        (t,) = od.scan_triggers(ws)
        assert t.token == "format:unknown:evidence/apkid.json"

    def test_apkid_error_is_no_signal(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "status": "error", "findings": [], "summary": "boom"}),
            encoding="utf-8")
        assert od.scan_triggers(ws) == []


# ---------------------------------------------------------------------------
# budget ledger
# ---------------------------------------------------------------------------


class TestBudgetLedger:
    def test_fresh_ledger_defaults(self, tmp_path):
        ws = mk_ws(tmp_path)
        state = od.ledger_state(ws)
        assert state["per_run_budget"] == od.DISTILL_ACTS_PER_RUN == 2
        assert state["per_run_used"] == 0
        assert state["hops_budget"] == od.DISTILL_HOPS_BUDGET == 12
        assert state["hops_used"] == 0
        assert state["global"] == {"acts": 0, "hops": 0, "landed": 0}
        assert state["run_id"]

    def test_reserve_act_debits_and_returns_receipt(self, tmp_path):
        ws = mk_ws(tmp_path)
        receipt = od.reserve_act(ws, "crypto:decode")
        assert receipt is not None
        assert receipt["attempt"].startswith("attempt-")
        state = od.ledger_state(ws)
        assert state["per_run_used"] == 1
        assert state["global"]["acts"] == 1
        assert state["triggers"]["crypto:decode"] == receipt["attempt"]

    def test_per_run_cap_halts(self, tmp_path):
        ws = mk_ws(tmp_path)
        assert od.reserve_act(ws, "a:x")
        assert od.reserve_act(ws, "b:y")
        assert od.reserve_act(ws, "c:z") is None
        assert od.ledger_state(ws)["per_run_used"] == 2

    def test_duplicate_token_refused_even_with_budget(self, tmp_path):
        ws = mk_ws(tmp_path)
        assert od.reserve_act(ws, "crypto:decode")
        assert od.reserve_act(ws, "crypto:decode") is None
        assert od.ledger_state(ws)["per_run_used"] == 1

    def test_corrupt_ledger_fails_closed(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text("{corrupt",
                                                          encoding="utf-8")
        assert od.ledger_state(ws)["corrupt"] is True
        assert od.reserve_act(ws, "crypto:decode") is None

    def test_type_garbage_counters_fail_closed(self, tmp_path):
        """A schema-valid ledger with non-integer counter fields is
        type-garbage: it reads as exhausted (fail-closed), never a
        crash and never a reset."""
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text(json.dumps({
            "schema": od.BUDGET_SCHEMA, "run_id": "r1",
            "run_started_ts": "2026-09-30T00:00:00Z",
            "per_run_budget": None, "per_run_used": 0,
            "hops_budget": 12, "hops_used": 0,
            "triggers": {}, "consumed_markers": [],
            "global": {"acts": 0, "hops": 0, "landed": 0}}),
            encoding="utf-8")
        state = od.ledger_state(ws)
        assert state["corrupt"] is True
        assert od.reserve_act(ws, "crypto:decode") is None
        assert not od.spend_hops(ws, 1)

    def test_stored_budget_above_default_clamps(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text(json.dumps({
            "schema": od.BUDGET_SCHEMA, "run_id": "r1",
            "run_started_ts": "2026-09-30T00:00:00Z",
            "per_run_budget": 99, "per_run_used": 0,
            "hops_budget": 99, "hops_used": 0,
            "triggers": {}, "consumed_markers": [],
            "global": {"acts": 0, "hops": 0, "landed": 0}}),
            encoding="utf-8")
        state = od.ledger_state(ws)
        assert state["per_run_budget"] == od.DISTILL_ACTS_PER_RUN
        assert state["hops_budget"] == od.DISTILL_HOPS_BUDGET

    def test_stored_smaller_budget_honored(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text(json.dumps({
            "schema": od.BUDGET_SCHEMA, "run_id": "r1",
            "run_started_ts": "2026-09-30T00:00:00Z",
            "per_run_budget": 1, "per_run_used": 0,
            "hops_budget": 3, "hops_used": 0,
            "triggers": {}, "consumed_markers": [],
            "global": {"acts": 0, "hops": 0, "landed": 0}}),
            encoding="utf-8")
        state = od.ledger_state(ws)
        assert state["per_run_budget"] == 1
        assert state["hops_budget"] == 3
        assert od.reserve_act(ws, "a:x")
        assert od.reserve_act(ws, "b:y") is None

    def test_spend_hops_debits_per_run_and_global(self, tmp_path):
        ws = mk_ws(tmp_path)
        assert od.spend_hops(ws, 4)
        state = od.ledger_state(ws)
        assert state["hops_used"] == 4
        assert state["global"]["hops"] == 4
        assert not od.spend_hops(ws, 9)  # exceeds remaining 8
        assert od.ledger_state(ws)["hops_used"] == 4

    def test_reinit_resets_per_run_not_global(self, tmp_path):
        ws = mk_ws(tmp_path)
        od.reserve_act(ws, "a:x")
        od.spend_hops(ws, 3)
        old_run = od.ledger_state(ws)["run_id"]
        od.reinit_run(ws)
        state = od.ledger_state(ws)
        assert state["run_id"] != old_run
        assert state["per_run_used"] == 0
        assert state["hops_used"] == 0
        assert state["global"]["acts"] == 1
        assert state["global"]["hops"] == 3

    def test_caller_supplied_run_identity_resets_nothing(self, tmp_path):
        ws = mk_ws(tmp_path)
        od.reserve_act(ws, "a:x")
        # a caller reading a DIFFERENT run id from anywhere must not
        # reset counters: the ledger read ignores any external identity
        before = od.ledger_state(ws)["per_run_used"]
        (ws / "runs" / "some-run-id.txt").write_text("other-run",
                                                     encoding="utf-8")
        assert od.ledger_state(ws)["per_run_used"] == before


# ---------------------------------------------------------------------------
# report validation
# ---------------------------------------------------------------------------


def base_report(**over) -> dict:
    report = {
        "schema": od.REPORT_SCHEMA,
        "trigger": {"kind": "shelf-miss", "token": "crypto:decode"},
        "sources": [
            {"kind": "relibrary",
             "ref": "references/re-library/patterns/decode/patterns-decode.md"},
        ],
        "hops": [],
        "methods": ["anchor-differential key recovery over structural "
                    "headers, then period detection, then bounded search"],
        "candidates": [
            {"name": "transform-recover",
             "file": "transform-recover.py",
             "capability": "crypto:decode",
             "oracle": {"expect_rc": 0,
                        "expect_stdout_contains": "KLG1"}},
        ],
    }
    report.update(over)
    return report


class TestReportValidation:
    def _repo(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_valid_report_passes(self, tmp_path):
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            base_report())
        assert ok, violations
        assert violations == []

    def test_fabricated_local_citation_rejects(self, tmp_path):
        report = base_report(sources=[
            {"kind": "relibrary",
             "ref": "references/re-library/patterns/decode/does-not-exist.md"},
        ])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert not ok
        assert any("does-not-exist.md" in v for v in violations)

    def test_web_source_needs_url_and_date(self, tmp_path):
        report = base_report(sources=[
            {"kind": "relibrary",
             "ref": "references/re-library/patterns/decode/patterns-decode.md"},
            {"kind": "web", "ref": "https://example.com/writeup"},
        ])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert not ok
        assert any("date" in v for v in violations)
        report["sources"][1]["date"] = "2026-09-30"
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert ok, violations

    def test_zero_methods_rejects(self, tmp_path):
        report = base_report(methods=[])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert not ok
        assert any("method" in v for v in violations)

    def test_depth_one_cap_rejects_chains(self, tmp_path):
        report = base_report(sources=[
            {"kind": "relibrary", "ref": "references/re-library/patterns/"
                                        "decode/patterns-decode.md"},
            {"kind": "relibrary", "ref": "references/re-library/method/"
                                        "case-distilled/case-dispatch-"
                                        "budget-partition.md"},
            {"kind": "web", "ref": "https://example.com/b",
             "date": "2026-09-30"},
        ], hops=[
            {"root": 0, "branch": 1, "verified_against": "sample"},
            {"root": 1, "branch": 2, "verified_against": "sample"},
        ])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert not ok
        assert any("depth" in v for v in violations)

    def test_breadth_three_cap_rejects_fourth_branch(self, tmp_path):
        refs = [
            "references/re-library/patterns/decode/patterns-decode.md",
            "references/re-library/method/case-distilled/case-dispatch-"
            "budget-partition.md",
            "references/re-library/method/formats/wire-format-recognition.md",
            "references/re-library/tools/crypto/tools-crypto.md",
            "references/re-library/patterns/simulation/patterns-"
            "simulation.md",
        ]
        report = base_report(
            sources=[{"kind": "relibrary", "ref": r} for r in refs],
            hops=[{"root": 0, "branch": i, "verified_against": "sample"}
                  for i in (1, 2, 3, 4)])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert not ok
        assert any("breadth" in v for v in violations)

    def test_three_branches_under_one_root_pass(self, tmp_path):
        refs = [
            "references/re-library/patterns/decode/patterns-decode.md",
            "references/re-library/method/case-distilled/case-dispatch-"
            "budget-partition.md",
            "references/re-library/method/formats/wire-format-recognition.md",
            "references/re-library/tools/crypto/tools-crypto.md",
        ]
        report = base_report(
            sources=[{"kind": "relibrary", "ref": r} for r in refs],
            hops=[{"root": 0, "branch": i, "verified_against": "sample"}
                  for i in (1, 2, 3)])
        ok, violations = od.validate_report(self._repo(), mk_ws(tmp_path),
                                            report)
        assert ok, violations

    def test_hop_budget_is_the_binding_total(self, tmp_path):
        ws = mk_ws(tmp_path)
        od.spend_hops(ws, 10)  # 2 remain
        refs = [
            "references/re-library/patterns/decode/patterns-decode.md",
            "references/re-library/method/case-distilled/case-dispatch-"
            "budget-partition.md",
            "references/re-library/method/formats/wire-format-recognition.md",
            "references/re-library/tools/crypto/tools-crypto.md",
            "references/re-library/patterns/simulation/patterns-"
            "simulation.md",
            "references/re-library/method/process/falsifier-library.md",
            "references/re-library/research/osint/multi-search-engine.md",
            "references/re-library/web/external-distilled/_GAP-REPORT.md",
        ]
        # caps-legal: two independent roots x 3 branches = 6 hops,
        # but only 2 remain in the per-run budget
        report = base_report(
            sources=[{"kind": "relibrary", "ref": r} for r in refs],
            hops=[{"root": 0, "branch": i, "verified_against": "sample"}
                  for i in (1, 2, 3)]
                 + [{"root": 4, "branch": i, "verified_against": "sample"}
                    for i in (5, 6, 7)])
        ok, violations = od.validate_report(self._repo(), ws, report)
        assert not ok
        assert any("budget" in v for v in violations), violations
        # nothing debited on rejection
        assert od.ledger_state(ws)["hops_used"] == 10

    def test_bad_schema_rejects(self, tmp_path):
        report = base_report(schema="not-a-schema")
        ok, _ = od.validate_report(self._repo(), mk_ws(tmp_path), report)
        assert not ok


# ---------------------------------------------------------------------------
# sample resolution + oracle
# ---------------------------------------------------------------------------


class TestSampleOracle:
    def test_bins_single_file_is_anchored(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "bins").mkdir()
        (ws / "bins" / "abc.bin").write_bytes(b"\x00\x01")
        t = od.Trigger("shelf-miss", "crypto:decode", "bins/abc.bin",
                       "runs/worker-status-x.md")
        path, source = od.resolve_sample(ws, t)
        assert path == ws / "bins" / "abc.bin"
        assert source == "anchored"

    def test_marker_hint_mismatch_against_anchor_records_no_sample(
            self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "bins").mkdir()
        (ws / "bins" / "abc.bin").write_bytes(b"\x00\x01")
        t = od.Trigger("shelf-miss", "crypto:decode", "target/other.bin",
                       "runs/worker-status-x.md")
        path, source = od.resolve_sample(ws, t)
        assert path is None
        assert source == "hint-mismatch"

    def test_anchorless_falls_back_to_guarded_marker_hint(self, tmp_path):
        ws = mk_ws(tmp_path)
        (ws / "target").mkdir()
        (ws / "target" / "blob.bin").write_bytes(b"\x02\x03")
        t = od.Trigger("shelf-miss", "crypto:decode", "target/blob.bin",
                       "runs/worker-status-x.md")
        path, source = od.resolve_sample(ws, t)
        assert path == ws / "target" / "blob.bin"
        assert source == "marker-fallback"

    def test_escape_hint_never_resolves_outside_ws(self, tmp_path):
        ws = mk_ws(tmp_path)
        t = od.Trigger("shelf-miss", "crypto:decode",
                       "../../etc/passwd", "runs/worker-status-x.md")
        path, source = od.resolve_sample(ws, t)
        assert path is None
        assert source in ("none", "hint-mismatch")

    def test_run_candidate_records_outcome(self, tmp_path):
        cand = tmp_path / "cand.py"
        cand.write_text(
            "import sys\nprint('KLG1 magic seen')\n", encoding="utf-8")
        sample = tmp_path / "s.bin"
        sample.write_bytes(b"\x00")
        out = od.run_candidate(cand, sample, expect_rc=0,
                               expect_stdout_contains="KLG1")
        assert out["satisfied"] is True
        assert out["rc"] == 0
        assert out["stdout_sha256"]

    def test_run_candidate_unsatisfied_on_bad_rc(self, tmp_path):
        cand = tmp_path / "cand.py"
        cand.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        sample = tmp_path / "s.bin"
        sample.write_bytes(b"\x00")
        out = od.run_candidate(cand, sample, expect_rc=0,
                               expect_stdout_contains="x")
        assert out["satisfied"] is False
        assert out["rc"] != 0

    def test_run_candidate_timeout_is_failure(self, tmp_path):
        cand = tmp_path / "cand.py"
        cand.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        sample = tmp_path / "s.bin"
        sample.write_bytes(b"\x00")
        out = od.run_candidate(cand, sample, expect_rc=0,
                               expect_stdout_contains="x", timeout_s=1)
        assert out["satisfied"] is False
        assert out["timed_out"] is True

    def test_run_candidate_missing_script_is_failure(self, tmp_path):
        out = od.run_candidate(tmp_path / "nope.py", tmp_path / "s.bin",
                               expect_rc=0, expect_stdout_contains="x")
        assert out["satisfied"] is False


# ---------------------------------------------------------------------------
# landing
# ---------------------------------------------------------------------------


class TestLanding:
    def _land(self, tmp_path, satisfied=True):
        ws = mk_ws(tmp_path)
        attempt_dir = ws / od.REPORTS_DIRNAME / "attempt-1"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "transform-recover.py").write_text(
            "print('tool')\n", encoding="utf-8")
        report = base_report()
        oracle = {"satisfied": satisfied, "rc": 0, "stdout_sha256": "h",
                  "stdout_tail": "KLG1", "timed_out": False,
                  "expect_rc": 0, "expect_stdout_contains": "KLG1",
                  "sample_sha256": "a" * 64}
        return ws, od.land_candidate(ws, attempt_dir, report, "transform-recover",
                                     oracle)

    def test_satisfied_candidate_lands_with_manifest(self, tmp_path):
        ws, landed = self._land(tmp_path)
        assert landed is not None
        tool, manifest = landed
        assert tool == ws / "tools-local" / "transform-recover.py"
        assert tool.is_file()
        m = json.loads(manifest.read_text(encoding="utf-8"))
        assert m["name"] == "transform-recover"
        assert m["capability"] == "crypto:decode"
        assert m["attempt"] == "attempt-1"
        assert m["methods"]
        assert m["sources"]
        assert m["oracle"]["satisfied"] is True
        assert m["oracle"]["sample_sha256"] == "a" * 64
        assert m["oracle"]["oracle_self_declared"] is True
        assert m["landed_ts"]

    def test_unsatisfied_candidate_never_lands(self, tmp_path):
        ws, landed = self._land(tmp_path, satisfied=False)
        assert landed is None
        assert not (ws / "tools-local").exists() or \
            not list((ws / "tools-local").glob("*.py"))

    def test_escaping_candidate_name_refused(self, tmp_path):
        ws = mk_ws(tmp_path)
        attempt_dir = ws / od.REPORTS_DIRNAME / "attempt-1"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "ok.py").write_text("print('tool')\n", encoding="utf-8")
        report = base_report()
        report["candidates"][0]["name"] = "../escape"
        oracle = {"satisfied": True, "rc": 0, "stdout_sha256": "h",
                  "stdout_tail": "KLG1", "timed_out": False,
                  "expect_rc": 0, "expect_stdout_contains": "KLG1",
                  "sample_sha256": "a" * 64}
        landed = od.land_candidate(ws, attempt_dir, report,
                                   "../escape", oracle)
        assert landed is None
        assert not (ws / "escape.py").exists()

    def test_engine_workspace_dirs_are_the_only_write_targets(self):
        """Static pin: every directory constant the engine writes under is
        a workspace-relative name — no repo-tree or absolute target."""
        for name in dir(od):
            if name.isupper() and isinstance(getattr(od, name), str):
                value = getattr(od, name)
                assert not value.startswith("/"), (name, value)
                assert ".." not in value, (name, value)
