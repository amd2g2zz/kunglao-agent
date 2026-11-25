# -*- coding: utf-8 -*-
"""tests/test_capability_report_1005.py — one capability report per eval
sample, with every face naming its organ (issue 1005, C1 ③).

The eval row answers "what happened"; the capability question needs six
numbers joined: facts counted by status, the ground-truth accuracy in the
control arm's own terms, orchestrator and worker tokens apart, wall clock,
dispatch count, and human interventions. Each face must also say WHERE its
number came from and, when there is no number, why — the failure mode this
report exists to prevent is a zero that is really an unread organ.

Faces pinned here:
  (a) facts counted by status — the sanctioned ``facts/_INDEX.md`` organ
      first, the fact files' frontmatter when no index was written, the index
      file itself never counted as a fact, and an index/file disagreement
      shown instead of smoothed over;
  (b) accuracy on the control arm's definitions — PASS with evidence counts,
      SKIP/REFUSED are not answers, an absent verdict is absent (never a
      silent FAIL), and a candidate that was never regraded is never accused
      of false PROVEN or premature closure;
  (c) the ground-truth face names the unit and never copies a value out of
      ``ground_truth.json`` (owner rule: the corpus does not travel);
  (d) the token split: orchestrator rows vs worker rows, the run-time harvest
      preferred over a second fold, no transcript meaning an absent account
      rather than zero, and no dollar figure ever priced from tokens;
  (e) wall clock, dispatch count (an absent organ stays absent) and the
      human-intervention count on ``bench_tokens``'s genuine-user-turn rule;
  (f) the batch rates come out of ``eval_control_arm.arm_metrics`` — a
      per-sample face and a campaign readout cannot drift apart;
  (g) the CLI: one file per sample plus a summary, and a refusal (exit 2)
      when asked to report on nothing.

No model call and no toolchain run: the fixtures are synthetic transcripts and
workspace trees under a redirected HOME (the transcript lookup resolves
``~/.claude/projects``, so a real session must never be touched). In-process
throughout — FAST tier."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bench_tokens as bt  # noqa: E402
import capability_report as cr  # noqa: E402
import eval_control_arm as ca  # noqa: E402
import eval_loop_runner as lr  # noqa: E402

FIRST = "2026-11-25T00:00:00.000Z"
LATER = "2026-11-25T00:10:00.000Z"
GT_SECRET = "DO-NOT-LEAK-7d2f1a"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# ------------------------------------------------------------------ fixtures
def _usage_row(*, sidechain: bool, inp: int = 0, out: int, cache: int = 0,
               cwd: str | None = None, ts: str = FIRST) -> str:
    row = {"type": "assistant", "timestamp": ts, "isSidechain": sidechain,
           "message": {"role": "assistant", "model": "test-model",
                       "usage": {"input_tokens": inp,
                                 "output_tokens": out,
                                 "cache_read_input_tokens": cache,
                                 "cache_creation_input_tokens": 0}}}
    if cwd is not None:
        row["cwd"] = cwd
    return json.dumps(row)


def _user_row(text, *, cwd: str | None = None, tool_result: bool = False,
              ts: str = FIRST) -> str:
    content = ([{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]
               if tool_result else text)
    row = {"type": "user", "timestamp": ts, "isSidechain": False,
           "message": {"role": "user", "content": content}}
    if cwd is not None:
        row["cwd"] = cwd
    return json.dumps(row)


def _workspace(tmp_path: Path, *, facts: dict[str, str] | None = None,
               index: str | None = None, junk_fact: bool = False,
               mission_ledger: str | None = None, dispatch_rows: int = 0,
               cockpit: dict | None = None) -> Path:
    ws = tmp_path / "ws-sample"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    for name, status in (facts or {}).items():
        body = f"---\nid: {name}\ntype: fact\n"
        if status:
            body += f"status: {status}\n"
        (ws / "facts" / f"{name}.md").write_text(body + "---\nbody\n",
                                                 encoding="utf-8")
    if junk_fact:
        (ws / "facts" / "no-frontmatter.md").write_text("# just prose\n",
                                                        encoding="utf-8")
    if index is not None:
        (ws / "facts" / "_INDEX.md").write_text(index, encoding="utf-8")
    if mission_ledger is not None:
        (ws / "runs" / "mission_ledger.yaml").write_text(mission_ledger,
                                                         encoding="utf-8")
    if dispatch_rows:
        with (ws / "runs" / "dispatch-ledger.jsonl").open(
                "w", encoding="utf-8") as f:
            for i in range(dispatch_rows):
                f.write(json.dumps({"schema": "dispatch-ledger/1",
                                    "dispatch_id": f"d{i}",
                                    "state": "dispatched"}) + "\n")
    if cockpit is not None:
        (ws / "runs" / ".cockpit-ratio.json").write_text(
            json.dumps(cockpit), encoding="utf-8")
    return ws


def _session(ws: Path, main_rows: list[str],
             workers: dict[str, list[str]] | None = None) -> Path:
    """The real layout: ``<projects>/<mangled ws>/<session>.jsonl`` plus
    ``<session>/subagents/agent-*.jsonl`` beside it."""
    proj = Path.home() / ".claude" / "projects" / lr.claude_projects_dir(
        ws).name
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "sess-1.jsonl").write_text("\n".join(main_rows) + "\n",
                                       encoding="utf-8")
    if workers:
        side = proj / "sess-1" / "subagents"
        side.mkdir(parents=True, exist_ok=True)
        for name, rows in workers.items():
            (side / name).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return ws


def _transcript_of(ws: Path) -> Path:
    tx = lr.session_transcript(ws, 0.0)
    assert tx is not None, "the fixture must land where the gauge looks"
    return tx


def _unit(tmp_path: Path, *, with_gt: bool = True) -> Path:
    tdir = tmp_path / "corpus" / "unit-x"
    tdir.mkdir(parents=True)
    (tdir / "task.yaml").write_text("family: test-family\ntier: release\n",
                                    encoding="utf-8")
    if with_gt:
        (tdir / "ground_truth.json").write_text(
            json.dumps({"constants": {"answer": GT_SECRET},
                        "published_pairs": [["a", "b"]]}), encoding="utf-8")
    return tdir


def _row(**over) -> dict:
    row = {"task_id": "unit-x", "arm": "loop", "family": "test-family",
           "checker_kind": "pair-match", "verdict": "PASS",
           "evidence_ref": "/tmp/evidence.json",
           "metrics": {"ttc_seconds": 1.0, "dispatch_count": 2,
                       "pass_at_k_contribution": 1, "converged": 1},
           "loop": {"status": "completed", "metrics": {"dispatch_count": 3},
                    "session": {"wall_s": 42.0, "returncode": 0,
                                "timed_out": False, "session_cost": None},
                    "deliverable": None, "workspace": None}}
    for key, val in over.items():
        if isinstance(row.get(key), dict) and isinstance(val, dict):
            row[key] = {**row[key], **val}
        else:
            row[key] = val
    return row


def _harvested(**over) -> dict:
    """A session_cost face as the run-time harvest writes it."""
    usage = {"input_tokens": 1, "output_tokens": 7,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "usage_rows": 1, "worker_input_tokens": 0,
             "worker_output_tokens": 0, "worker_cache_read_input_tokens": 0,
             "worker_cache_creation_input_tokens": 0, "worker_usage_rows": 0,
             "worker_transcripts": 0, "worker_unread": 0,
             "cost_state_rows": 1}
    usage.update(over.pop("usage", {}))
    face = {"transcript_usage": usage}
    face.update(over)
    return face


# ---------------------------------------------------------------------- (a)
def _index(rows: list[tuple[str, str, str]]) -> str:
    """A `facts/_INDEX.md` body in the ONE sanctioned shape: a `#` comment
    header plus `F<id> | <status> | <claim_id> | <conclusion>` rows
    (tools/_lib/index_schema.py owns the parse; a 4-column row carrying a
    non-canonical status rejects, which is exactly what the fixtures must
    avoid unless they mean to test the fallback)."""
    body = "# kunglao_template_version: 0.1.6-rc2\n# _INDEX\n\n"
    return body + "".join(f"{fid} | {st} | {cid} | conclusion {fid}\n"
                          for fid, st, cid in rows)


def test_facts_counted_from_the_index_organ_when_it_exists(tmp_path):
    index = _index([("F-001", "PROVEN", "C-001"),
                    ("F-002", "PROVEN", "C-001"),
                    ("F-003", "OPEN", "C-002")])
    ws = _workspace(tmp_path, facts={"F-001": "PROVEN", "F-002": "PROVEN",
                                     "F-003": "OPEN"}, index=index)

    face = cr.facts_by_status(ws)

    assert face["counts"] == {"PROVEN": 2, "OPEN": 1}
    assert face["total"] == 3
    assert "_INDEX.md" in face["source"]
    assert face["files_seen"] == 3, "the index file is an organ, not a fact"


def test_facts_without_an_index_fall_back_to_frontmatter(tmp_path):
    ws = _workspace(tmp_path, facts={"F001": "PROVEN", "F002": ""},
                    junk_fact=True)

    face = cr.facts_by_status(ws)

    assert face["counts"]["PROVEN"] == 1
    assert face["counts"]["UNKNOWN"] == 2, "a blank status and a file without " \
                                           "frontmatter are blind spots, not " \
                                           "facts"
    assert "frontmatter" in face["source"]
    assert "no facts/_INDEX.md" in face["reason"]


def test_facts_a_rejected_index_row_falls_back_and_says_so(tmp_path):
    # PARTIAL is not in the canonical status set: the parser rejects the row,
    # the count falls back to frontmatter, and the rejection stays visible.
    index = _index([("F-001", "PARTIAL", "C-001")])
    ws = _workspace(tmp_path, facts={"F-001": "PROVEN"}, index=index)

    face = cr.facts_by_status(ws)

    assert "index_error" in face
    assert "frontmatter" in face["source"]
    assert face["counts"]["PROVEN"] == 1


def test_facts_index_disagreeing_with_files_is_shown(tmp_path):
    index = _index([("F-001", "PROVEN", "C-001")])
    ws = _workspace(tmp_path, facts={"F-001": "PROVEN", "F-002": "PROVEN",
                                     "F-003": "PROVEN"}, index=index)

    face = cr.facts_by_status(ws)

    assert face["total"] == 1
    assert face["files_seen"] == 3
    assert face["index_vs_files_delta"] == 2, "a stale index must be visible"


def test_facts_missing_directory_is_absent_not_zero(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()

    face = cr.facts_by_status(bare)

    assert face["total"] == 0
    assert face["source"] is None
    assert "no facts/" in face["reason"]


# ---------------------------------------------------------------------- (b)
def test_pass_with_evidence_is_answered_and_correct(tmp_path):
    gt = {"present": True, "task_dir": str(_unit(tmp_path))}

    face = cr.accuracy_faces(_row(), gt, regrade=False, outdir=None)

    assert face["verdict"] == "PASS"
    assert face["correct"] is True
    assert face["answered"] is True
    assert face["proven_with_evidence"] is True


@pytest.mark.parametrize("verdict", ["SKIP", "REFUSED"])
def test_skip_and_refused_are_not_answers(verdict, tmp_path):
    gt = {"present": True, "task_dir": str(_unit(tmp_path))}

    face = cr.accuracy_faces(_row(verdict=verdict, evidence_ref=None), gt,
                             regrade=False, outdir=None)

    assert face["answered"] is False
    assert face["correct"] is False
    assert face["proven_with_evidence"] is False


def test_a_row_without_a_verdict_reports_absent_not_fail(tmp_path):
    gt = {"present": True, "task_dir": str(_unit(tmp_path))}

    face = cr.accuracy_faces(_row(verdict=None, evidence_ref=None), gt,
                             regrade=False, outdir=None)

    assert face["verdict"] is None
    assert face["correct"] is None, "no grade must never read as a FAIL"
    assert "never graded" in face["reason"]


def test_an_unregraded_candidate_is_never_accused(tmp_path):
    # A claimed closure with evidence, but no --regrade: neither falsification
    # leg ran, so nothing may be accused (the control arm's posture). The
    # ground-truth face is built by the real function so its own wording is
    # what gets pinned.
    gt = cr.ground_truth_face(str(_unit(tmp_path)), None, regrade=False)

    face = cr.accuracy_faces(_row(), gt, regrade=False, outdir=None)

    assert face["claimed_converged"] is True
    assert face["regraded"] is False
    assert face["false_proven"] is False
    assert face["premature_closure"] is False
    assert "not requested" in gt["reason"]


def test_converged_bit_comes_from_the_checker_metrics(tmp_path):
    # loop.metrics.converged (the loop's own bool) must not drive the arm's
    # claimed-closure count: arm_metrics reads the checker's 0/1 bit.
    gt = {"present": True, "task_dir": str(_unit(tmp_path))}
    row = _row(metrics={"ttc_seconds": 1.0, "dispatch_count": 2,
                        "pass_at_k_contribution": 1, "converged": 0},
               loop={"metrics": {"converged": True, "dispatch_count": 1}})

    face = cr.accuracy_faces(row, gt, regrade=False, outdir=None)

    assert face["claimed_converged"] is False


def test_regrade_without_a_candidate_says_so(tmp_path):
    gt = {"present": True, "task_dir": str(_unit(tmp_path))}

    face = cr.accuracy_faces(_row(), gt, regrade=True, outdir=None)

    assert face["regraded"] is False
    assert "no candidate" in face["reason_regrade"]
    # never accused without a grade — the arm's own predicate
    assert face["false_proven"] is False


# ---------------------------------------------------------------------- (c)
def test_ground_truth_face_names_the_unit_and_leaks_nothing(tmp_path):
    tdir = _unit(tmp_path)

    face = cr.ground_truth_face(str(tdir), None, regrade=False)

    assert face["present"] is True
    assert face["task_dir"] == str(tdir)
    assert GT_SECRET not in json.dumps(face), "corpus content never travels"


def test_ground_truth_unknown_unit_is_reported_not_invented(tmp_path):
    face = cr.ground_truth_face("no-such-unit-xyz", None, regrade=False)

    assert face["present"] is False
    assert "not resolvable" in face["reason"]


def test_ground_truth_unit_without_a_file_says_so(tmp_path):
    tdir = _unit(tmp_path, with_gt=False)

    face = cr.ground_truth_face(str(tdir), None, regrade=False)

    assert face["present"] is False
    assert "no ground_truth.json" in face["reason"]


def test_ground_truth_without_a_unit_says_so(tmp_path):
    face = cr.ground_truth_face(None, None, regrade=False)

    assert face["present"] is False
    assert "no task id" in face["reason"]


# ---------------------------------------------------------------------- (d)
def test_token_face_splits_orchestrator_and_worker(tmp_path):
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("go", cwd=cwd),
                  _usage_row(sidechain=False, inp=1000, out=90, cache=7000,
                             cwd=cwd)],
             {"agent-a.jsonl": [_usage_row(sidechain=True, inp=40, out=777),
                                _usage_row(sidechain=True, inp=10, out=23)],
              "agent-b.jsonl": [_usage_row(sidechain=True, out=500)]})

    usage, source = cr.transcript_usage(None, _transcript_of(ws))
    face = cr.token_faces(usage, source, None)

    assert face["orchestrator"] == {"input_tokens": 1000,
                                    "output_tokens": 90,
                                    "cache_read_input_tokens": 7000,
                                    "cache_creation_input_tokens": 0,
                                    "usage_rows": 1}
    assert face["worker"]["output_tokens"] == 1300
    assert face["worker"]["transcripts"] == 2
    assert "fresh fold" in face["source"]


def test_run_time_harvest_beats_a_second_fold(tmp_path):
    # The harvested face says 7 output tokens; the transcript on disk says 90.
    # The recorded face wins: re-folding would silently disagree with what the
    # run itself reported.
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_usage_row(sidechain=False, inp=1, out=90, cwd=cwd)])
    harvested = _harvested(total_cost_usd=3.5, cost_source="cli-result")

    usage, source = cr.transcript_usage(harvested, _transcript_of(ws))
    face = cr.token_faces(usage, source, harvested)

    assert face["orchestrator"]["output_tokens"] == 7
    assert "harvested at run" in face["source"]
    assert face["total_cost_usd"] == 3.5
    assert face["cost_source"] == "cli-result"


def test_no_transcript_leaves_the_token_account_absent(tmp_path):
    ws = _workspace(tmp_path)

    usage, source = cr.transcript_usage(None, None)
    face = cr.token_faces(usage, source, None)

    assert face["orchestrator"] is None
    assert face["worker"] is None
    assert "absent" in face["reason"]
    assert ws  # the workspace exists; there is simply no transcript


def test_dollars_are_never_priced_from_tokens(tmp_path):
    # The killed-session shape: usage rows exist, no cost-state row ever was
    # written, and no stdout report arrived. Tokens are booked, dollars absent.
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("go", cwd=cwd),
                  _usage_row(sidechain=False, inp=10, out=3, cwd=cwd)],
             {"agent-a.jsonl": [_usage_row(sidechain=True, out=44)]})

    usage, source = cr.transcript_usage(None, _transcript_of(ws))
    face = cr.token_faces(usage, source, None)

    assert face["total_cost_usd"] is None, "a token account is not a dollar " \
                                           "account: nothing is priced"
    assert face["cost_state_rows"] == 0
    assert face["worker"]["output_tokens"] == 44


def test_pre_provenance_row_is_labelled_as_such(tmp_path):
    # Rows written before the cost_source face existed carry a dollar
    # figure with no provenance key.
    face = cr.token_faces(None, None, {"total_cost_usd": 1.25})

    assert face["total_cost_usd"] == 1.25
    assert "pre-provenance" in face["cost_source"]


# ------------------------------------------------- cost unit (owner ruling)
def test_grand_total_is_the_declared_unit_summed_per_population(tmp_path):
    # input+output+cache_read+cache_creation (bench_tokens.py:10, :94-95), once
    # per population then added: a session's denominator is NOT the main file
    # alone, which is all bench_tokens.collect() on one path can see.
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_usage_row(sidechain=False, inp=1000, out=90, cache=7000,
                             cwd=cwd)],
             {"agent-a.jsonl": [_usage_row(sidechain=True, inp=400, out=77,
                                           cache=50)]})

    usage, source = cr.transcript_usage(None, _transcript_of(ws))
    face = cr.token_faces(usage, source, None)

    gt = face["grand_total"]
    assert gt["orchestrator"] == 1000 + 90 + 7000
    assert gt["worker"] == 400 + 77 + 50
    assert gt["session"] == gt["orchestrator"] + gt["worker"]
    assert "bench_tokens.grand_total" in face["cost_unit"]


def test_grand_total_matches_the_bench_meter_without_workers(tmp_path):
    # Proven against the module that owns the unit, not a restated constant:
    # with no worker transcripts the session total equals bench_tokens.collect().
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("go", cwd=cwd),
                  _usage_row(sidechain=False, inp=1234, out=56, cache=789,
                             cwd=cwd)])
    tx = _transcript_of(ws)

    usage, source = cr.transcript_usage(None, tx)
    face = cr.token_faces(usage, source, None)

    assert face["grand_total"]["session"] == bt.collect(tx)["grand_total"]
    assert face["grand_total"]["session"] == 1234 + 56 + 789


def test_dollars_stay_secondary_with_their_coverage(tmp_path):
    # One sample with a real dollar face, one with tokens only, one with
    # nothing: the token mean is taken over covered solutions, the dollar face
    # reports its subset and share, and the gap is never filled.
    solved_covered = {"accuracy": {"correct": True},
                      "tokens": {"grand_total": {"session": 9000},
                                 "total_cost_usd": 5.04}}
    solved_naked = {"accuracy": {"correct": True},
                    "tokens": {"grand_total": None, "total_cost_usd": None}}
    killed_tokens = {"accuracy": {"correct": False},
                     "tokens": {"grand_total": {"session": 3000},
                                "total_cost_usd": None}}

    cost = cr.cost_faces([solved_covered, solved_naked, killed_tokens])

    assert cost["unit"] == "bench_tokens.grand_total"
    assert cost["samples"] == 3
    assert cost["tokens_covered_samples"] == 2
    assert cost["tokens_total"] == 12000
    assert cost["correct_solutions"] == 2
    assert cost["correct_solutions_with_tokens"] == 1
    assert cost["cost_per_correct_solution_tokens"] == pytest.approx(9000)
    assert cost["tokens_coverage"] == pytest.approx(2 / 3)
    dollars = cost["dollars_secondary"]
    assert dollars["samples_with_dollars"] == 1
    assert dollars["coverage"] == pytest.approx(1 / 3)
    assert dollars["cost_per_correct_solution_usd"] == pytest.approx(5.04)
    assert "never filled by" in dollars["note"]


def test_cost_faces_empty_batch_is_absent_not_zero(tmp_path):
    cost = cr.cost_faces([])

    assert cost["cost_per_correct_solution_tokens"] is None
    assert cost["tokens_total"] == 0
    assert cost["tokens_coverage"] is None
    assert cost["dollars_secondary"]["coverage"] is None


def test_aggregate_carries_the_cost_face(tmp_path):
    reports = [{"accuracy": {"correct": True, "answered": True},
                "tokens": {"grand_total": {"session": 100}},
                "facts": {"source": "x"}, "dispatch": {"dispatch_count": 1},
                "human": {"user_turn_count": 1}}]

    agg = cr.aggregate(reports)

    assert agg["cost"]["cost_per_correct_solution_tokens"] == 100
    assert agg["cost"]["dollars_secondary"]["cost_per_correct_solution_usd"]         is None


# ---------------------------------------------------------------------- (e)
def test_wall_clock_prefers_the_session_record(tmp_path):
    face = cr.wall_face(None, _row())

    assert face["wall_s"] == 42.0
    assert "session record" in face["source"]


def test_wall_clock_falls_back_to_the_transcript_span(tmp_path):
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("go", cwd=cwd, ts=FIRST),
                  _usage_row(sidechain=False, inp=1, out=1, cwd=cwd,
                             ts=LATER)])

    face = cr.wall_face(_transcript_of(ws), {"loop": {"session": {}}})

    assert face["wall_s"] == 600
    assert "timestamp" in face["source"]


def test_wall_clock_absent_without_either_organ(tmp_path):
    face = cr.wall_face(None, {"loop": {"session": {}}})

    assert face["wall_s"] is None
    assert "neither" in face["reason"]


def test_dispatch_count_absent_organ_stays_absent(tmp_path):
    ws = _workspace(tmp_path, dispatch_rows=2)

    face = cr.dispatch_face(ws, _row(loop={"metrics": {}, "session": {}}),
                            None)

    assert face["dispatch_count"] is None, "an unread ledger is not a " \
                                           "measurement of zero dispatches"
    assert face["dispatch_ledger_rows"] == 2
    assert "unmeasured" in face["reason"]


def test_dispatch_count_reads_the_mission_ledger_organ(tmp_path):
    ledger = ("mission:\n  history:\n"
              "    - events: {dispatch: 2}\n    - events: {dispatch: 1}\n")
    ws = _workspace(tmp_path, mission_ledger=ledger)

    face = cr.dispatch_face(ws, _row(loop={"metrics": {}, "session": {}}),
                            {"worker_transcripts": 3})

    assert face["dispatch_count"] == 3
    assert "mission_ledger" in face["source"]
    assert face["worker_transcripts"] == 3


def test_dispatch_count_prefers_the_row_metric(tmp_path):
    face = cr.dispatch_face(None, _row(), None)

    assert face["dispatch_count"] == 3
    assert "eval row" in face["source"]


def test_human_interventions_exclude_tool_result_rows(tmp_path):
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("do the thing", cwd=cwd),
                  _user_row(None, cwd=cwd, tool_result=True),
                  _user_row("paste the missing key", cwd=cwd, ts=LATER),
                  _usage_row(sidechain=False, inp=5, out=5, cwd=cwd,
                             ts=LATER)])

    face = cr.human_face(_transcript_of(ws))

    assert face["user_turn_count"] == 2, "a tool_result row is the harness " \
                                         "talking, not a person"
    assert face["intervened"] is True


def test_a_single_prompt_is_not_an_intervention(tmp_path):
    ws = _workspace(tmp_path)
    cwd = str(ws.resolve())
    _session(ws, [_user_row("do the thing", cwd=cwd),
                  _usage_row(sidechain=False, inp=5, out=5, cwd=cwd)])

    face = cr.human_face(_transcript_of(ws))

    assert face["user_turn_count"] == 1
    assert face["intervened"] is False


def test_human_face_absent_without_a_transcript(tmp_path):
    face = cr.human_face(None)

    assert face["user_turn_count"] is None
    assert face["intervened"] is None
    assert "absent" in face["reason"]


def test_cockpit_face_is_carried_and_its_absence_named(tmp_path):
    face = cr.cockpit_face(tmp_path / "nothing")
    assert face["ratio"] is None
    assert ".cockpit-ratio.json" in face["reason"]

    ws = _workspace(tmp_path, cockpit={"ratio": 607.0,
                                       "machine_input_tokens": 7,
                                       "analysis_output_tokens": 11,
                                       "worker_transcripts": 307,
                                       "worker_unread": 0,
                                       "alarm": True, "ts": FIRST})
    got = cr.cockpit_face(ws)
    assert got["ratio"] == 607.0
    assert got["worker_transcripts"] == 307
    assert got["source"].endswith(".cockpit-ratio.json")


def test_cockpit_face_junk_is_reported_not_raised(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "runs" / ".cockpit-ratio.json").write_text("{ half a json",
                                                     encoding="utf-8")

    face = cr.cockpit_face(ws)

    assert face["ratio"] is None
    assert "unreadable" in face["reason"]


# ------------------------------------------------------------------- (f) + (g)
def test_sample_report_carries_every_named_face(tmp_path):
    tdir = _unit(tmp_path)
    ws = _workspace(tmp_path, facts={"F001": "PROVEN"},
                    cockpit={"ratio": 5.0, "analysis_output_tokens": 1})
    cwd = str(ws.resolve())
    _session(ws, [_user_row("go", cwd=cwd),
                  _usage_row(sidechain=False, inp=100, out=9, cwd=cwd)],
             {"agent-a.jsonl": [_usage_row(sidechain=True, inp=1, out=50)]})
    row = _row(loop={"status": "completed",
                     "metrics": {"dispatch_count": 1},
                     "session": {"wall_s": 10.0, "returncode": 0,
                                 "timed_out": False, "session_cost": None},
                     "deliverable": None, "workspace": str(ws)})

    report = cr.sample_report(ws, task_id=str(tdir), tier="release", row=row)

    for key in ("facts", "accuracy", "ground_truth", "tokens", "cockpit",
                "wall", "dispatch", "human"):
        assert key in report, f"the report must carry the {key} face"
    assert report["schema"] == cr.SCHEMA
    assert report["facts"]["counts"] == {"PROVEN": 1}
    assert report["tokens"]["worker"]["output_tokens"] == 50
    assert report["human"]["user_turn_count"] == 1
    assert report["wall"]["wall_s"] == 10.0
    assert report["dispatch"]["dispatch_count"] == 1
    assert report["accuracy"]["correct"] is True
    assert report["cockpit"]["ratio"] == 5.0
    assert report["sample"]["transcript_window"]["candidates_in_dir"] == 1
    assert GT_SECRET not in json.dumps(report)


def test_transcript_window_is_open_and_its_organ_counted(tmp_path):
    ws = _workspace(tmp_path)
    _session(ws, [_user_row("go", cwd=str(ws.resolve()))])

    floor, source, candidates = cr.transcript_window(ws, None)

    assert floor == 0.0
    assert "local time labelled Z" in source
    assert candidates == 1


def test_report_survives_a_missing_workspace(tmp_path):
    report = cr.sample_report(None, task_id=None, row=None)

    assert report["facts"]["source"] is None
    assert report["tokens"]["orchestrator"] is None
    assert report["dispatch"]["dispatch_count"] is None
    assert report["human"]["user_turn_count"] is None
    assert report["cockpit"]["ratio"] is None


def test_batch_rates_equal_the_control_arm_on_the_same_rows(tmp_path):
    # Three samples (PASS / FAIL / SKIP) graded twice: by the control arm's own
    # metric block, and by this module's aggregate of per-sample faces.
    rows = [_row(),
            _row(verdict="FAIL", evidence_ref=None,
                 metrics={"ttc_seconds": 2.0, "dispatch_count": 1,
                          "pass_at_k_contribution": 0, "converged": 0}),
            _row(verdict="SKIP", evidence_ref=None,
                 metrics={"ttc_seconds": 3.0, "dispatch_count": 0,
                          "pass_at_k_contribution": 0, "converged": 0})]
    gt = {"present": True}
    reports = [{"accuracy": cr.accuracy_faces(r, gt, regrade=False,
                                             outdir=None)} for r in rows]

    arm = ca.arm_metrics({"arm": "loop", "rows": rows}, {}, {})
    agg = cr.aggregate(reports)

    assert agg["samples"] == 3
    assert agg["answer_rate"] == pytest.approx(arm["answer_rate"]) == 2 / 3
    assert agg["proven_with_evidence_rate"] == pytest.approx(
        arm["proven_with_evidence_rate"]) == 1 / 3
    assert agg["premature_closure_rate"] == pytest.approx(
        arm["premature_closure_rate"]) == 0.0
    assert agg["false_proven_rate"] == pytest.approx(
        arm["false_proven_rate"]) == 0.0
    assert agg["gt_accuracy_over_all"] == pytest.approx(1 / 3)
    assert agg["gt_accuracy_answered"] == pytest.approx(1 / 2)


def test_absent_faces_are_counted_as_absent(tmp_path):
    reports = [{"facts": {"source": None}, "accuracy": {"verdict": None},
                "tokens": {"source": None},
                "dispatch": {"dispatch_count": None},
                "human": {"user_turn_count": None}},
               {"facts": {"source": "x"}, "accuracy": {"verdict": "PASS",
                                                       "correct": True,
                                                       "answered": True},
                "tokens": {"source": "y"},
                "dispatch": {"dispatch_count": 0},
                "human": {"user_turn_count": 1}}]

    agg = cr.aggregate(reports)

    assert agg["units_absent"] == {"facts": 1, "verdict": 1, "tokens": 1,
                                   "dispatch": 1, "human": 1}
    assert agg["samples"] == 2


# ------------------------------------------------------------------------ (g)
def test_cli_writes_one_report_per_sample_and_a_summary(tmp_path, capsys):
    ws = _workspace(tmp_path, facts={"F001": "PROVEN"})
    doc = tmp_path / "eval-results-x.json"
    doc.write_text(json.dumps({"tier": "release", "rows": [
        _row(loop={"workspace": str(ws), "metrics": {"dispatch_count": 1},
                   "session": {"wall_s": 5.0}})]}), encoding="utf-8")
    out = tmp_path / "reports"

    rc = cr.main(["--results", str(doc), "--out", str(out)])
    printed = capsys.readouterr().out

    assert rc == 0
    assert (out / "capability-unit-x.json").is_file()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["samples"] == 1
    assert summary["reports"][0].endswith("capability-unit-x.json")
    assert "CAPABILITY-REPORTS" in printed


@pytest.mark.parametrize("argv,needle", [
    ([], "give --results"),
    (["--results", "{nope}"], "cannot read"),
])
def test_cli_refuses_without_a_usable_input(argv, needle, tmp_path, capsys):
    rc = cr.main(argv)

    assert rc == 2
    assert needle in capsys.readouterr().err


def test_cli_refuses_a_results_doc_with_no_workspace(tmp_path, capsys):
    doc = tmp_path / "eval-results-y.json"
    doc.write_text(json.dumps({"tier": "release", "rows": [_row()]}),
                   encoding="utf-8")

    rc = cr.main(["--results", str(doc), "--out", str(tmp_path / "o")])

    assert rc == 2
    assert "names a workspace" in capsys.readouterr().err


def test_cli_refuses_a_workspace_that_is_not_a_directory(tmp_path, capsys):
    rc = cr.main(["--workspace", str(tmp_path / "gone"),
                  "--out", str(tmp_path / "o")])

    assert rc == 2
    assert "not a directory" in capsys.readouterr().err
