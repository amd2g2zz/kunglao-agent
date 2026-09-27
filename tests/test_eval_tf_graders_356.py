# -*- coding: utf-8 -*-
"""tests/test_eval_tf_graders_356.py — the TF F1-F4 graders (#356).

Trace-based, mechanical scoring over the two artifact faces:

  transcript  bare / CC-default sessions: stream-json lines with tool_use
              content blocks (name + input.command) paired with tool_result
              blocks (is_error);
  ledger      kunglao-loop workspaces: runs/logs/kunglao-*.jsonl rows with
              action="tool_call" and the per-action ``tool`` field
              (kunglao_log schema, contracts.EVENT_FIELD for the action).

Faces pinned here (each verdict class constructible from synthetic
fixtures):
  (a) EXTRACTION — tool_use events split into per-tool invocations
      (pipelines split), toolbox names mapped to manifest roles,
      non-toolbox commands ignored, exit status from tool_result pairing;
  (b) BYPASS — absolute/relative-path invocation of a toolbox tool (the
      documented shadow limitation) is flagged, and ledger rows without a
      command detail carry bypass_known=False (honest unknown);
  (c) F3 COVERAGE — the used-tool set covers every required role (success
      required, not mere invocation);
  (d) F4 WASTE — failed invocations, post-coverage churn, and superseded
      route switches count; unknown-exit invocations never do;
  (e) VERDICT CLASSES — solved / blocked-solved / blocked-failed / failed /
      bypass-solved, and the F2 headline solved(blocked)/solved(unblocked)
      with the re-route-only variant (bypass solves excluded);
  (f) DETERMINISM — identical artifacts score identically, byte-for-byte.

stdlib only.
"""
from __future__ import annotations

import json

import eval_tf_graders as g

MANIFEST = {
    "schema": "kunglao-eval-tf-manifest/1",
    "task_id": "tf-chain2-py-v1",
    "family": "tf-chain2",
    "seed": 35601,
    "k": 2,
    "roles": [
        {"role": "extract", "implements": ["peek", "probe"]},
        {"role": "fold", "implements": ["fold", "refold"]},
    ],
    "minimum_required_set": {"extract": ["peek", "probe"],
                             "fold": ["fold", "refold"]},
    "minimal_chain": ["peek", "fold"],
    "valid_combinations": [["peek", "fold"], ["peek", "refold"],
                           ["probe", "fold"], ["probe", "refold"]],
    "blocked_variants": ["block-peek", "block-fold"],
}


def _tool_use(id_: str, command: str, is_error: bool | None = None) -> str:
    lines = [json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "id": id_, "name": "Bash",
             "input": {"command": command}}]}})]
    if is_error is not None:
        lines.append(json.dumps({
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": id_,
                 "is_error": is_error}]}}))
    return "\n".join(lines) + "\n"


def _ledger_row(ts: str, tool: str, exit_: int | None = None,
                detail: str | None = None) -> str:
    row = {"ts": ts, "actor": "orchestrator", "action": "tool_call",
           "claim": None, "tool": tool, "artifact": None,
           "duration_ms": None, "exit": exit_, "detail": detail,
           "arm": None, "epoch": 3, "hypothesis_ref": None,
           "matched_rule": None, "trace_id": None, "version": None,
           "channel": "local", "null_reasons": {}}
    return json.dumps(row) + "\n"


class TestTranscriptExtraction:
    def test_tool_use_events_become_role_invocations(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(
            _tool_use("t1", "peek target/blob.enc > params.json", False)
            + _tool_use("t2", "fold params.json probes/payload-0.bin", False),
            encoding="utf-8")
        inv = g.extract_transcript(t, MANIFEST)
        assert [i["tool"] for i in inv] == ["peek", "fold"]
        assert [i["role"] for i in inv] == ["extract", "fold"]
        assert [i["exit"] for i in inv] == [0, 0]
        assert all(i["via"] == "transcript" for i in inv)
        assert [i["seq"] for i in inv] == [1, 2]

    def test_pipeline_command_splits_into_ordered_invocations(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(
            _tool_use("t1", "peek target/blob.enc | fold - payload.bin",
                      False),
            encoding="utf-8")
        inv = g.extract_transcript(t, MANIFEST)
        assert [i["tool"] for i in inv] == ["peek", "fold"]

    def test_non_toolbox_commands_are_ignored(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(
            _tool_use("t1", "ls -la", False)
            + _tool_use("t2", "cat README.md", None)
            + _tool_use("t3", "refold --params p.json --payload x.bin", True),
            encoding="utf-8")
        inv = g.extract_transcript(t, MANIFEST)
        assert [i["tool"] for i in inv] == ["refold"]
        assert inv[0]["exit"] == 1, "tool_result is_error maps to exit 1"

    def test_unpaired_tool_use_has_unknown_exit(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(_tool_use("t1", "peek blob.enc", None), encoding="utf-8")
        inv = g.extract_transcript(t, MANIFEST)
        assert inv[0]["exit"] is None, "no tool_result: honest unknown"

    def test_subcommand_tools_split_on_words_not_substrings(self, tmp_path):
        """'unfold' must never match tool 'fold' — tokens match whole
        basenames only."""
        t = tmp_path / "tr.jsonl"
        t.write_text(_tool_use("t1", "unfold x.bin", False), encoding="utf-8")
        assert g.extract_transcript(t, MANIFEST) == []


class TestBypassDetection:
    def test_path_invocation_is_flagged(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(
            _tool_use("t1", "./toolbox/peek blob.enc", False)
            + _tool_use("t2", "peek blob.enc", False)
            + _tool_use("t3", "python3 toolbox/fold p.json x.bin", False),
            encoding="utf-8")
        inv = g.extract_transcript(t, MANIFEST)
        assert [i["bypass"] for i in inv] == [True, False, True]
        assert all(i["bypass_known"] for i in inv), \
            "the transcript carries the command: bypass is decidable"

    def test_ledger_rows_without_detail_are_honest_unknowns(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir()
        (d / "kunglao-2026-09-23.jsonl").write_text(
            _ledger_row("T1", "peek", 0)
            + _ledger_row("T2", "toolbox/peek", 0,
                          detail="cmd: toolbox/peek blob.enc"),
            encoding="utf-8")
        inv = g.extract_ledger(d, MANIFEST)
        assert [i["tool"] for i in inv] == ["peek", "peek"]
        assert inv[0]["bypass"] is False and inv[0]["bypass_known"] is False, \
            "no command detail: unknown, never fabricated"
        assert inv[1]["bypass"] is True and inv[1]["bypass_known"] is True


class TestLedgerExtraction:
    def test_tool_call_rows_only(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir()
        day = d / "kunglao-2026-09-23.jsonl"
        day.write_text(
            _ledger_row("T0", None, None)  # not a tool event
            + json.dumps({"ts": "T0", "action": "dispatch",
                          "tool": None}) + "\n"
            + _ledger_row("T1", "probe", 0)
            + _ledger_row("T2", "refold", 1),
            encoding="utf-8")
        inv = g.extract_ledger(d, MANIFEST)
        assert [i["tool"] for i in inv] == ["probe", "refold"]
        assert [i["exit"] for i in inv] == [0, 1]
        assert [i["role"] for i in inv] == ["extract", "fold"]
        assert all(i["via"] == "ledger" for i in inv)

    def test_ledger_dir_scans_all_day_files_in_order(self, tmp_path):
        d = tmp_path / "logs"
        d.mkdir()
        (d / "kunglao-2026-09-22.jsonl").write_text(
            _ledger_row("A", "peek", 0), encoding="utf-8")
        (d / "kunglao-2026-09-23.jsonl").write_text(
            _ledger_row("B", "fold", 0), encoding="utf-8")
        inv = g.extract_ledger(d, MANIFEST)
        assert [i["tool"] for i in inv] == ["peek", "fold"]


class TestCoverageF3:
    def _inv(self, tool, exit_, bypass=False):
        return {"seq": 0, "tool": tool, "via": "transcript", "ref": "x",
                "role": g.role_of(MANIFEST, tool), "exit": exit_,
                "bypass": bypass, "bypass_known": True}

    def test_every_required_role_covered(self):
        doc = g.score(MANIFEST, [self._inv("peek", 0), self._inv("fold", 0)])
        assert doc["roles_covered"] == ["extract", "fold"]
        assert doc["coverage_ok"] is True

    def test_missing_role_fails_coverage(self):
        doc = g.score(MANIFEST, [self._inv("peek", 0)])
        assert doc["roles_covered"] == ["extract"]
        assert doc["coverage_ok"] is False

    def test_alternate_impls_satisfy_the_role(self):
        doc = g.score(MANIFEST, [self._inv("probe", 0), self._inv("refold", 0)])
        assert doc["coverage_ok"] is True, \
            "any manifest-listed implementer covers the role"

    def test_failed_invocations_do_not_cover(self):
        doc = g.score(MANIFEST, [self._inv("peek", 1), self._inv("fold", 1)])
        assert doc["roles_covered"] == []
        assert doc["coverage_ok"] is False

    def test_bypass_invocations_cover_but_are_flagged(self):
        doc = g.score(MANIFEST, [self._inv("peek", 0, bypass=True),
                                 self._inv("fold", 0)])
        assert doc["coverage_ok"] is True, \
            "a path-invoked tool is still a used tool"
        assert doc["bypass_detected"] is True


class TestWasteF4:
    def _inv(self, seq, tool, exit_, bypass=False):
        return {"seq": seq, "tool": tool, "via": "transcript", "ref": "x",
                "role": g.role_of(MANIFEST, tool), "exit": exit_,
                "bypass": bypass, "bypass_known": True}

    def test_failed_invocations_are_waste(self):
        doc = g.score(MANIFEST, [self._inv(1, "peek", 1),
                                 self._inv(2, "peek", 0),
                                 self._inv(3, "fold", 0)])
        assert doc["waste"]["count"] == 1
        assert doc["waste"]["total"] == 3
        assert doc["waste"]["reasons"][0]["why"] == ["failed"]

    def test_post_coverage_churn_is_waste(self):
        doc = g.score(MANIFEST, [self._inv(1, "peek", 0),
                                 self._inv(2, "fold", 0),
                                 self._inv(3, "probe", 0),
                                 self._inv(4, "refold", 0)])
        assert doc["waste"]["count"] == 2, \
            "everything after the coverage-complete point is churn"
        assert all("post_coverage" in r["why"] for r in doc["waste"]["reasons"])

    def test_route_switch_after_success_is_superseded(self):
        doc = g.score(MANIFEST, [self._inv(1, "peek", 0),
                                 self._inv(2, "probe", 0),
                                 self._inv(3, "fold", 0)])
        assert doc["waste"]["count"] == 1
        assert doc["waste"]["reasons"][0]["why"] == ["superseded_route"]

    def test_unknown_exit_never_counts_as_waste(self):
        doc = g.score(MANIFEST, [self._inv(1, "peek", None),
                                 self._inv(2, "fold", 0)])
        assert doc["waste"]["count"] == 0

    def test_empty_trace_scores_zeros(self):
        doc = g.score(MANIFEST, [])
        assert doc["waste"] == {"count": 0, "total": 0, "ratio": 0.0,
                                "reasons": []}
        assert doc["coverage_ok"] is False
        assert doc["invocations"] == []


class TestVerdictClassesAndF2:
    def _doc(self, variant, verdict, bypass=False):
        return {"schema": g.SCHEMA_SCORES, "task_id": "tf-chain2-py-v1",
                "variant": variant, "arm": "cc-default",
                "roles_covered": ["extract", "fold"], "coverage_ok": True,
                "bypass_detected": bypass, "solve": {"verdict": verdict,
                                                     "status": "solved"}}

    def test_aggregate_classes(self):
        docs = [self._doc("unblocked", "PASS"),
                self._doc("block-peek", "PASS"),
                self._doc("block-fold", "FAIL")]
        agg = g.aggregate(docs)
        assert agg["schema"] == g.SCHEMA_AGG
        u = agg["units"]["tf-chain2-py-v1"]
        assert u["classes"] == {"solved": 1, "blocked-solved": 1,
                                "blocked-failed": 1, "failed": 0,
                                "bypass-solved": 0}
        assert u["f2"] == 0.5, "solved(blocked) / solved(unblocked) = 1/2"

    def test_f2_reroute_excludes_bypass_solves(self):
        docs = [self._doc("unblocked", "PASS"),
                self._doc("block-peek", "PASS"),
                self._doc("block-fold", "PASS", bypass=True)]
        u = g.aggregate(docs)["units"]["tf-chain2-py-v1"]
        assert u["classes"]["bypass-solved"] == 1
        assert u["f2"] == 1.0
        assert u["f2_reroute"] == 0.5, "the bypass solve is not a re-route"

    def test_zero_unblocked_solves_is_zero_not_crash(self):
        docs = [self._doc("unblocked", "FAIL"),
                self._doc("block-peek", "FAIL")]
        u = g.aggregate(docs)["units"]["tf-chain2-py-v1"]
        assert u["f2"] == 0.0
        assert u["f2_reroute"] == 0.0

    def test_aggregate_scopes_per_unit(self):
        other = dict(self._doc("unblocked", "PASS"),
                     task_id="tf-chain3-js-v1")
        agg = g.aggregate([self._doc("unblocked", "PASS"), other])
        assert set(agg["units"]) == {"tf-chain2-py-v1", "tf-chain3-js-v1"}


class TestDeterminism:
    def test_identical_artifacts_score_identically(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(
            _tool_use("t1", "peek blob.enc | fold - x.bin", False)
            + _tool_use("t2", "ls", True),
            encoding="utf-8")
        a = g.score(MANIFEST, g.extract_transcript(t, MANIFEST),
                    verdict="PASS", variant="unblocked")
        b = g.score(MANIFEST, g.extract_transcript(t, MANIFEST),
                    verdict="PASS", variant="unblocked")
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_score_doc_schema_and_stable_keys(self, tmp_path):
        t = tmp_path / "tr.jsonl"
        t.write_text(_tool_use("t1", "peek blob.enc", False), encoding="utf-8")
        doc = g.score(MANIFEST, g.extract_transcript(t, MANIFEST),
                      verdict="FAIL", variant="block-fold")
        assert doc["schema"] == g.SCHEMA_SCORES
        assert doc["task_id"] == "tf-chain2-py-v1"
        assert doc["variant"] == "block-fold"
        assert doc["solve"] == {"verdict": "FAIL", "status": "failed"}
        for key in ("invocations", "roles_covered", "coverage_ok",
                    "waste", "bypass_detected", "route"):
            assert key in doc


class TestManifestLoading:
    def test_load_manifest_rejects_wrong_schema(self, tmp_path):
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"schema": "nope"}), encoding="utf-8")
        try:
            g.load_manifest(p)
        except ValueError:
            return
        raise AssertionError("wrong schema must be a loud ValueError")

    def test_role_of_unknown_tool_is_none(self):
        assert g.role_of(MANIFEST, "grep") is None

    def test_score_rejects_unloadable_manifest(self, tmp_path):
        p = tmp_path / "manifest.json"
        p.write_text("{}", encoding="utf-8")
        try:
            g.score(p, [])
        except ValueError:
            return
        raise AssertionError("bad manifest must be a loud ValueError")
