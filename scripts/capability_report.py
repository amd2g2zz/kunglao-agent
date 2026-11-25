#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capability_report.py — one capability report per eval sample.

The eval row already carries the loop's outcome face, but the capability
question needs six numbers in ONE document, and three of them only exist in
organs nobody joins: the facts counted by status (``facts/_INDEX.md``, or the
fact files' own frontmatter where no index was written), the
orchestrator-vs-worker token split (the session transcript — the gauge fixed
in the same issue), and the human-intervention count
(``bench_tokens``'s genuine-user-turn rule).

Every face carries its own provenance, under one rule:

  * measured -> the number, plus ``source`` naming the organ it came from;
  * absent   -> ``None`` plus ``reason``: a blank is never read as zero, and
    an unread organ never becomes a measurement of zero (the dispatch face
    distinguishes "the ledger said 0" from "there is no ledger");
  * not asked -> the field says so. The two ground-truth falsification legs
    (minted-probe subset, fresh re-run) execute a toolchain, so they are
    opt-in (``--regrade``); an unrun leg reports "ungraded" and accuses
    nothing, which is ``eval_control_arm``'s own posture.

Accuracy reuses ``eval_control_arm``'s predicates and rate functions rather
than restating what the metrics mean — that module's five-metric block is
the repo's definition, and ``aggregate`` computes the batch rates through the
same functions, so a per-sample face and a campaign readout cannot drift.

The report NEVER copies corpus content: the ground-truth face names the unit
and the checker's verdict, not a constant from ``ground_truth.json`` (owner
rule: the eval corpus is intermediate material and does not travel).

Cost unit (owner ruling on this slice): the cross-arm denominator is
``bench_tokens.grand_total`` — the repo's declared experiment cost unit
(``bench_tokens.py:10``), obtainable on EVERY session including the hard-killed
ones, with zero pricing assumption. Dollars are a SECONDARY face that exists
only where the CLI itself reported them, attached to its coverage share, and
are never interpolated from token counts (the transcript's usage rows and the
CLI's own ``modelUsage`` face are different populations). ``aggregate`` exposes
both through ``cost_faces``.

Usage:
  capability_report.py --results experiments/.../eval-results-*.json [--out DIR]
  capability_report.py --workspace WS [--task UNIT] [--tier T] [--out DIR]
  capability_report.py --results R --regrade      # run the minted-probe legs

Default ``--out`` is ``<repo>/experiments/capability-reports/<utc-ts>/`` — the
gitignored local run tree; a report is a run artifact, not a repo asset.

Exit: 0 (a sample whose face is absent still produces a report); 2 for a
refused call (no input, unreadable results doc, no workspace in it).

stdlib + repo scripts only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from _common import scripts_bootstrap

SCRIPT_DIR = scripts_bootstrap()

import bench_tokens as bt        # noqa: E402
import eval_checker as chk       # noqa: E402
import eval_control_arm as ca    # noqa: E402
import eval_dataset as ds        # noqa: E402
import eval_loop_runner as lr    # noqa: E402
import lint_facts as lf          # noqa: E402
import update_index as ui            # noqa: E402 — the _INDEX status counter

SCHEMA = "capability-report/1"
SUMMARY_SCHEMA = "capability-report-summary/1"
DEFAULT_OUT_REL = Path("experiments") / "capability-reports"

MISSION_LEDGER_REL = Path("runs") / "mission_ledger.yaml"
DISPATCH_LEDGER_REL = Path("runs") / "dispatch-ledger.jsonl"
COCKPIT_RATIO_REL = Path("runs") / ".cockpit-ratio.json"

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- facts face
FACT_INDEX_REL = Path("facts") / "_INDEX.md"


def facts_by_status(ws: Path) -> dict:
    """The workspace's facts counted by status, from the organ that exists.

    ``facts/_INDEX.md`` is the sanctioned O(1) status-count source (its schema
    and parser are single-source in ``tools/_lib/index_schema.py``), so it is
    read first and ``update_index.count_by_status`` does the counting. When a
    workspace has no index — or a malformed one — the count falls back to the
    fact files' own frontmatter, which is the same status vocabulary the
    linter reads (``lint_facts.parse_frontmatter``). The organ used is named in
    the face, and the blind spots stay in the numbers: an unreadable fact file
    counts as UNREADABLE, a missing status as UNKNOWN, and the index file
    itself is never counted as a fact."""
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return {"counts": {}, "total": 0, "source": None,
                "reason": "no facts/ directory in the workspace"}
    index = facts_dir / FACT_INDEX_REL.name
    if index.is_file():
        files = sum(1 for p in facts_dir.glob("*.md")
                    if p.name != FACT_INDEX_REL.name)
        try:
            counts = ui.count_by_status(index)
        except Exception as exc:  # noqa: BLE001 — a torn index falls back
            return {**_facts_from_frontmatter(facts_dir),
                    "files_seen": files,
                    "index_error": f"{type(exc).__name__}: {exc}"}
        face = {"counts": counts, "total": sum(counts.values()),
                "files_seen": files,
                "source": "facts/_INDEX.md (index_schema parser)"}
        if files != face["total"]:
            # a stale index is a finding, not something to average away: the
            # count stands on the sanctioned organ, the disagreement is shown
            face["index_vs_files_delta"] = files - face["total"]
        return face
    face = _facts_from_frontmatter(facts_dir)
    face["reason"] = "no facts/_INDEX.md — counted from the fact files' status"
    return face


def _facts_from_frontmatter(facts_dir: Path) -> dict:
    counts: dict[str, int] = {}
    for p in sorted(facts_dir.glob("*.md")):
        if p.name == FACT_INDEX_REL.name:
            continue  # the index is an organ, not a fact
        try:
            fm, _body, _err = lf.parse_frontmatter(
                p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            counts["UNREADABLE"] = counts.get("UNREADABLE", 0) + 1
            continue
        status = str((fm or {}).get("status") or "").strip().upper()
        counts[status or "UNKNOWN"] = counts.get(status or "UNKNOWN", 0) + 1
    return {"counts": counts, "total": sum(counts.values()),
            "source": "facts/*.md frontmatter"}


# ------------------------------------------------------------- ground truth
def ground_truth_face(task_id: str | None, tier: str | None, *,
                      regrade: bool) -> dict:
    """The unit's ground-truth organ: does the corpus carry it, and was a
    regrade asked for. The face names the artifact and never reads a value
    out of it — the checker decides the grade, this only says the organ is
    there."""
    face: dict = {"unit": task_id, "present": False, "regrade_requested":
                  bool(regrade)}
    if not task_id:
        face["reason"] = "no task id: the sample is not tied to a unit"
        return face
    try:
        tdir = ds.resolve_task_dir(task_id, tier=tier)
    except FileNotFoundError as exc:
        face["reason"] = f"unit not resolvable in the corpus root: {exc}"
        return face
    face["task_dir"] = str(tdir)
    face["present"] = (tdir / "ground_truth.json").is_file()
    if not face["present"]:
        face["reason"] = "the unit carries no ground_truth.json"
    elif not regrade:
        face["reason"] = ("ground truth present; the minted-probe and re-run "
                          "legs were not requested (--regrade runs them, and "
                          "they execute a toolchain)")
    return face


def _candidate_of(row: dict, doc_dir: Path | None = None) -> Path | None:
    """The delivered candidate artifact of a sample, if the row names one:
    the loop's deliverable face first, then the control arm's own field. A
    recorded relative path is resolved the same way a workspace path is."""
    for got in (((row.get("loop") or {}).get("deliverable")),
                row.get("candidate_path")):
        if not (isinstance(got, str) and got):
            continue
        cand, _src = resolve_artifact(got, doc_dir)
        if cand.is_file():
            return cand
    return None


def accuracy_faces(row: dict, gt: dict, *, regrade: bool,
                   outdir: Path | None,
                   doc_dir: Path | None = None) -> dict:
    """The control arm's metric definitions applied to ONE sample: answered,
    proven-with-evidence, and the two falsification legs when a regrade ran.

    The run-time verdict IS the checker's grade against the unit's ground
    truth; with no row verdict the grade is absent, never a silent FAIL. An
    ungradeable candidate (toolchain absent) is reported, not accused —
    ``is_false_proven`` returns False for ``minted=None`` by that module's own
    rule, so the legs are reported separately from the booleans."""
    row = row or {}
    verdict = str(row.get("verdict") or "").strip().upper()
    # arm_metrics counts r["metrics"]["converged"] == 1 — the checker's bit
    claimed = (row.get("metrics") or {}).get("converged") == 1
    face: dict = {
        "verdict": verdict or None,
        "correct": (verdict == "PASS") if verdict else None,
        # the arm's own answer set (PASS/FAIL; SKIP/REFUSED is not an answer)
        "answered": verdict in ca._ANSWER_VERDICTS,
        "proven_with_evidence": bool(verdict == "PASS"
                                     and row.get("evidence_ref")),
        "checker_kind": row.get("checker_kind"),
        "claimed_converged": claimed,
        "regraded": False,
        "minted_matched": None,
        "minted_total": None,
        "rerun_verdict": None,
        "false_proven": None,
        "premature_closure": None,
    }
    if not verdict:
        face["reason"] = ("no eval row verdict: the checker never graded "
                          "this sample")
    minted = rerun = None
    if regrade and gt.get("present") and gt.get("task_dir"):
        face.update(_regrade_legs(row, Path(gt["task_dir"]), outdir,
                                  doc_dir))
        minted = (face["minted_matched"], face["minted_total"]) \
            if face["minted_total"] is not None else None
        rerun = face["rerun_verdict"]
    # the arm's predicates, not a local opinion: an ungraded candidate can
    # never be accused of false PROVEN or premature closure
    face["false_proven"] = ca.is_false_proven(verdict, minted)
    face["premature_closure"] = ca.is_premature_closure(claimed, rerun,
                                                        minted)
    return face


def _regrade_legs(row: dict, tdir: Path, outdir: Path | None,
                  doc_dir: Path | None = None) -> dict:
    """Run the two falsification legs, tolerantly: a missing toolchain or an
    unreadable unit degrades to a reason, never to an accusation."""
    candidate = _candidate_of(row, doc_dir)
    if candidate is None:
        return {"reason_regrade": "no candidate artifact to regrade"}
    out = Path(outdir or ".")
    try:
        family = ds.load_task(tdir)["family"]
        gt_doc = json.loads((tdir / "ground_truth.json")
                            .read_text(encoding="utf-8"))
        minted = ca.minted_only_grade(family, tdir, gt_doc, candidate, out)
        rerun = ca.rerun_verdict(tdir, candidate, out)
    except chk.Skip as exc:
        return {"reason_regrade": f"toolchain unavailable: {exc}"}
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"reason_regrade":
                f"regrade refused: {type(exc).__name__}: {exc}"}
    return {
        "regraded": minted is not None or rerun is not None,
        "minted_matched": minted[0] if minted else None,
        "minted_total": minted[1] if minted else None,
        "rerun_verdict": rerun,
    }


# ------------------------------------------------------------------- tokens
def transcript_usage(session_cost: dict | None,
                     tx: Path | None) -> tuple[dict | None, str | None]:
    """(usage face, source) — the run-time harvest when the row carries it,
    else one fresh fold of the session (the same-issue gauge), else no number
    at all; ``token_faces`` then states why."""
    if isinstance(session_cost, dict) and isinstance(
            session_cost.get("transcript_usage"), dict):
        return session_cost["transcript_usage"], \
            "session_cost.transcript_usage (harvested at run)"
    if tx is not None:
        return lr.transcript_usage(tx), "transcript usage rows (fresh fold)"
    return None, None


def _grand_total(inp: int | None, out: int | None, cr: int | None,
                 cc: int | None) -> int:
    """The experiment's declared cost unit — ``bench_tokens.py:10`` "all four
    summed", computed at ``bench_tokens.py:94-95``. Reused here as the SAME
    arithmetic over each population separately, because
    ``bench_tokens.collect(transcript)`` reads ONE file and therefore returns
    only the orchestrator part: a session's denominator is the orchestrator and
    worker totals ADDED (owner ruling on this slice, item (a))."""
    return sum(int(v or 0) for v in (inp, out, cr, cc))


def token_faces(usage: dict | None, source: str | None,
                session_cost: dict | None) -> dict:
    """Orchestrator and worker token accounts kept APART — the split the
    same-issue gauge produces — with the dollar face's provenance so a mixed
    cost account stays visible on the data.

    ``grand_total`` is the comparison denominator (the repo's declared cost
    unit, see ``_grand_total``); dollars are a SECONDARY face that exists only
    where the CLI actually reported them and is never interpolated from tokens."""
    face: dict = {"source": source, "orchestrator": None, "worker": None,
                  "grand_total": None, "cost_unit": None,
                  "total_cost_usd": None, "cost_source": None}
    if isinstance(session_cost, dict):
        face["cost_source"] = session_cost.get("cost_source")
        if session_cost.get("total_cost_usd") is not None:
            face["total_cost_usd"] = session_cost.get("total_cost_usd")
            face["cost_source"] = session_cost.get(
                "cost_source") or "cli-result (pre-provenance row)"
        face["cost_unavailable_reason"] = \
            session_cost.get("cost_unavailable_reason")
    if usage is None:
        face["reason"] = "no usage face: the token account is absent"
        return face
    face["orchestrator"] = {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens":
            usage.get("cache_creation_input_tokens"),
        "usage_rows": usage.get("usage_rows"),
    }
    face["worker"] = {
        "input_tokens": usage.get("worker_input_tokens"),
        "output_tokens": usage.get("worker_output_tokens"),
        "cache_read_input_tokens":
            usage.get("worker_cache_read_input_tokens"),
        "cache_creation_input_tokens":
            usage.get("worker_cache_creation_input_tokens"),
        "usage_rows": usage.get("worker_usage_rows"),
        "transcripts": usage.get("worker_transcripts"),
        "unread": usage.get("worker_unread"),
    }
    orch = face["orchestrator"]
    wkr = face["worker"]
    face["grand_total"] = {
        "orchestrator": _grand_total(orch["input_tokens"],
                                     orch["output_tokens"],
                                     orch["cache_read_input_tokens"],
                                     orch["cache_creation_input_tokens"]),
        "worker": _grand_total(wkr["input_tokens"], wkr["output_tokens"],
                               wkr["cache_read_input_tokens"],
                               wkr["cache_creation_input_tokens"]),
    }
    face["grand_total"]["session"] = (face["grand_total"]["orchestrator"]
                                      + face["grand_total"]["worker"])
    face["cost_unit"] = ("bench_tokens.grand_total (input+output+cache_read"
                         "+cache_creation), summed per population then added; "
                         "the cross-arm denominator")
    face["cost_state_rows"] = usage.get("cost_state_rows")
    if face["total_cost_usd"] is None:
        face["total_cost_usd"] = usage.get("total_cost_usd")
    return face


def cockpit_face(ws: Path | None) -> dict:
    """The harness-vs-analysis ratio the capture hook persists, read as the
    writer left it (the same face ``scripts/heartbeat_tick.py`` rides into the
    tick report). Absent when the hook never sampled this workspace."""
    if ws is None:
        return {"ratio": None, "source": None,
                "reason": "no workspace path for this sample"}
    p = Path(ws) / COCKPIT_RATIO_REL
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ratio": None, "source": None,
                "reason": f"no {COCKPIT_RATIO_REL} in the workspace"}
    except (OSError, ValueError) as exc:
        return {"ratio": None, "source": None,
                "reason": f"unreadable ratio face: {type(exc).__name__}"}
    if not isinstance(doc, dict):
        return {"ratio": None, "source": None,
                "reason": "ratio face is not an object"}
    return {"ratio": doc.get("ratio"),
            "machine_input_tokens": doc.get("machine_input_tokens"),
            "analysis_output_tokens": doc.get("analysis_output_tokens"),
            "worker_transcripts": doc.get("worker_transcripts"),
            "worker_unread": doc.get("worker_unread"),
            "alarm": doc.get("alarm"), "ts": doc.get("ts"),
            "source": str(COCKPIT_RATIO_REL)}


# --------------------------------------------- wall clock / dispatch / human
def wall_face(tx: Path | None, row: dict) -> dict:
    """Wall clock: the session record's own seconds first, the transcript's
    first→last timestamp span as the fallback organ."""
    session = ((row or {}).get("loop") or {}).get("session") or {}
    if session.get("wall_s") is not None:
        return {"wall_s": session.get("wall_s"),
                "source": "session record wall_s"}
    if tx is not None:
        return {"wall_s": bt.collect(tx).get("wall_s"),
                "source": "transcript first→last timestamp"}
    return {"wall_s": None, "source": None,
            "reason": "neither a session record nor a transcript exists"}


def dispatch_face(ws: Path | None, row: dict, usage: dict | None) -> dict:
    """How many workers this sample dispatched, with the organ named.

    The eval row's harvested metric wins. Otherwise the runner's own organ is
    read (``lr._factor_face`` over the mission ledger's dispatch events) — and
    when THAT organ does not exist the count is reported absent, because "0
    read off a missing ledger" is not a measurement of zero dispatches. The
    dispatch ledger's row count and the worker-transcript count ride along as
    independent lower bounds: where they disagree with the ledger, the report
    shows the disagreement instead of averaging it away."""
    face: dict = {"dispatch_count": None, "source": None,
                  "dispatch_ledger_rows": None, "worker_transcripts": None}
    metrics = ((row or {}).get("loop") or {}).get("metrics") or {}
    if isinstance(metrics.get("dispatch_count"), int):
        face["dispatch_count"] = metrics["dispatch_count"]
        face["source"] = "eval row loop.metrics.dispatch_count"
    elif ws is not None and (Path(ws) / MISSION_LEDGER_REL).is_file():
        _vectors, dispatch, _cost = lr._factor_face(Path(ws))
        face["dispatch_count"] = dispatch
        face["source"] = "runs/mission_ledger.yaml dispatch events"
    else:
        face["reason"] = ("no row metric and no mission ledger: the dispatch "
                          "count is unmeasured, not zero")
    if ws is not None:
        try:
            face["dispatch_ledger_rows"] = sum(
                1 for ln in (Path(ws) / DISPATCH_LEDGER_REL)
                .open(encoding="utf-8", errors="replace") if ln.strip())
        except OSError:
            face["dispatch_ledger_rows"] = None
    if usage is not None:
        face["worker_transcripts"] = usage.get("worker_transcripts")
    return face


def human_face(tx: Path | None) -> dict:
    """Human interventions: ``bench_tokens``'s genuine-user-turn rule (a
    tool_result row is the harness talking, not a person), with its own >1
    rescue threshold — the same contamination signal the AB design reads."""
    if tx is None:
        return {"user_turn_count": None, "intervened": None, "source": None,
                "reason": "no transcript: the intervention count is absent"}
    tokens = bt.collect(tx)
    return {"user_turn_count": tokens.get("user_turn_count"),
            "intervened": bt.human_intervention(tokens),
            "source": "bench_tokens genuine-user-turn count",
            "usage_incomplete": tokens.get("usage_incomplete")}


# ------------------------------------------------------------------ sample
def transcript_window(ws: Path, started_s: float | None) -> tuple[
        float, str, int]:
    """(launch floor for the transcript search, provenance, how many
    transcripts live in this workspace's directory).

    The floor is OPEN (0.0) unless the caller supplies the real launch epoch,
    because the workspace name's stamp cannot be trusted as one: the runner
    builds it with ``time.strftime('%Y%m%dT%H%M%SZ')`` on a LOCAL clock
    (``eval_loop_runner.py:1175,1281``), so on this UTC+8 machine the trailing
    ``Z`` is false — measured: a workspace named ``…20261028T131042Z`` holds
    the transcript of a session whose last row was written ``06:39:44Z``. An
    open window still requires each candidate's own rows to name this cwd, and
    the candidate count is reported so a reused workspace directory stays
    visible instead of silently yielding its newest session."""
    d = lr.claude_projects_dir(ws)
    try:
        candidates = len(list(d.glob("*.jsonl")))
    except OSError:
        candidates = 0
    if started_s is not None:
        return started_s, "caller supplied launch epoch", candidates
    return 0.0, ("open window (the name stamp is local time labelled Z, so it "
                 "cannot bound the search)"), candidates


def sample_report(ws: Path | str | None, *, task_id: str | None = None,
                  tier: str | None = None, row: dict | None = None,
                  started_s: float | None = None, regrade: bool = False,
                  outdir: Path | None = None, doc_dir: Path | None = None,
                  workspace_source: str | None = None) -> dict:
    """One sample's capability report. Every organ is read tolerantly: a
    missing face is reported as absent with its reason, never as zero, and
    never as an exception that drops the whole report."""
    row = row or {}
    loop = row.get("loop") or {}
    session = loop.get("session") or {}
    if isinstance(ws, str):
        ws, workspace_source = resolve_artifact(ws, doc_dir)
    elif ws is not None and workspace_source is None:
        workspace_source = "caller supplied path"
    ws = Path(ws) if ws else None
    if ws is not None:
        floor, window_src, candidates = transcript_window(ws, started_s)
        tx = lr.session_transcript(ws, floor)
    else:
        floor, window_src, candidates = 0.0, "no workspace", 0
        tx = None
    session_cost = session.get("session_cost")
    usage, usage_src = transcript_usage(session_cost, tx)
    unit = task_id or row.get("task_id")
    gt = ground_truth_face(unit, tier or row.get("tier"), regrade=regrade)
    return {
        "schema": SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": {
            "unit": unit,
            "tier": tier or row.get("tier"),
            "arm": row.get("arm"),
            "family": row.get("family"),
            "workspace": str(ws) if ws else None,
            "workspace_resolution": workspace_source,
            "transcript": str(tx) if tx else None,
            "transcript_window": {"started_s": floor, "source": window_src,
                                  "candidates_in_dir": candidates},
            "session": {"returncode": session.get("returncode"),
                        "timed_out": session.get("timed_out"),
                        "status": loop.get("status")},
        },
        "facts": facts_by_status(ws) if ws else {
            "counts": {}, "total": 0, "source": None,
            "reason": "no workspace path for this sample"},
        "accuracy": accuracy_faces(row, gt, regrade=regrade, outdir=outdir,
                                   doc_dir=doc_dir),
        "ground_truth": gt,
        "tokens": token_faces(usage, usage_src, session_cost),
        "cockpit": cockpit_face(ws),
        "wall": wall_face(tx, row),
        "dispatch": dispatch_face(ws, row, usage),
        "human": human_face(tx),
    }


# ---------------------------------------------------------------- aggregate
def aggregate(reports: list[dict]) -> dict:
    """The control arm's rates over a batch of sample reports, computed by
    that module's own functions — a per-sample face and a campaign readout
    cannot drift apart. Denominators follow ``arm_metrics`` exactly."""
    total = len(reports)
    acc = [r.get("accuracy") or {} for r in reports]
    claimed = [a for a in acc if a.get("claimed_converged")]
    proven = [a for a in acc if a.get("proven_with_evidence")]
    return {
        "schema": SUMMARY_SCHEMA,
        "samples": total,
        "answer_rate": ca.answer_rate(
            sum(1 for a in acc if a.get("answered")), total),
        "proven_with_evidence_rate": ca.proven_with_evidence_rate(
            len(proven), total),
        "premature_closure_rate": ca.premature_closure_rate(
            sum(1 for a in claimed if a.get("premature_closure")),
            len(claimed)),
        "false_proven_rate": ca.false_proven_rate(
            sum(1 for a in proven if a.get("false_proven")), len(proven)),
        "regraded": sum(1 for a in acc if a.get("regraded")),
        # ground-truth accuracy two ways, both through the arm's rate face:
        # over every sampled unit, and over only the answered ones
        "gt_accuracy_over_all": ca.answer_rate(
            sum(1 for a in acc if a.get("correct")), total),
        "gt_accuracy_answered": ca.answer_rate(
            sum(1 for a in acc if a.get("correct")),
            sum(1 for a in acc if a.get("answered"))),
        # the ruling's denominator: tokens primary, dollars secondary
        "cost": cost_faces(reports),
        "units_absent": {
            "facts": sum(1 for r in reports
                         if not (r.get("facts") or {}).get("source")),
            "verdict": sum(1 for r in reports
                           if not (r.get("accuracy") or {}).get("verdict")),
            "tokens": sum(1 for r in reports
                          if not (r.get("tokens") or {}).get("source")),
            "dispatch": sum(1 for r in reports
                            if (r.get("dispatch") or {}).get("dispatch_count")
                            is None),
            "human": sum(1 for r in reports
                         if (r.get("human") or {}).get("user_turn_count")
                         is None),
        },
    }


def _share(part: int, whole: int) -> float | None:
    """A coverage ratio. None (not 0) over an empty whole — the share of a
    nothing is unmeasured, never zero."""
    return part / whole if whole else None


def cost_faces(reports: list[dict]) -> dict:
    """What one correct solution costs, in the repo's declared cost unit.

    Owner ruling on this slice: the cross-arm denominator is
    ``bench_tokens.grand_total`` (available on EVERY session, including the
    hard-killed ones, with zero pricing assumption); dollars are a SECONDARY
    face that exists only where the CLI actually reported them, attached with
    its coverage share and never interpolated to fill the rest. Numerators and
    denominators are kept on the SAME covered subset so an absent organ cannot
    silently deflate a per-solution cost."""
    acc = [r.get("accuracy") or {} for r in reports]
    with_tokens = [r for r in reports
                   if ((r.get("tokens") or {}).get("grand_total") or {})
                   .get("session") is not None]
    with_dollars = [r for r in reports
                    if (r.get("tokens") or {}).get("total_cost_usd") is not None]
    solved_tokens = [r for r in with_tokens
                     if (r.get("accuracy") or {}).get("correct")]
    solved_dollars = [r for r in with_dollars
                      if (r.get("accuracy") or {}).get("correct")]
    tokens_total = sum(
        (r["tokens"]["grand_total"]["session"]) for r in with_tokens)
    solved_total = sum(
        (r["tokens"]["grand_total"]["session"]) for r in solved_tokens)
    return {
        "unit": "bench_tokens.grand_total",
        "samples": len(reports),
        "cost_per_correct_solution_tokens": (
            round(solved_total / len(solved_tokens), 1)
            if solved_tokens else None),
        "correct_solutions": sum(1 for a in acc if a.get("correct")),
        "correct_solutions_with_tokens": len(solved_tokens),
        "tokens_total": tokens_total,
        "tokens_covered_samples": len(with_tokens),
        "tokens_coverage": _share(len(with_tokens), len(reports)),
        "dollars_secondary": {
            "samples_with_dollars": len(with_dollars),
            "coverage": _share(len(with_dollars), len(reports)),
            "cost_per_correct_solution_usd": (
                round(sum((r["tokens"]["total_cost_usd"])
                          for r in solved_dollars) / len(solved_dollars), 6)
                if solved_dollars else None),
            "note": ("secondary face only; absent dollars are never filled by "
                     "pricing token counts"),
        },
    }


# ---------------------------------------------------------------------- CLI
def _write(out_dir: Path, name: str, doc: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


def resolve_artifact(raw: str, doc_dir: Path | None = None,
                     max_ancestors: int = 4) -> tuple[Path, str]:
    """(path, provenance) for a path recorded inside a results row.

    Rows carry both shapes and they must not be conflated: an absolute path is
    used as recorded, while a RELATIVE one is repo-root-relative — measured on
    ``eval-results-20261018T082158Z-47837.json``, whose row workspace is
    ``experiments/exp-s12-e2e-userpath/…``. Resolving that against the caller's
    cwd silently yields "no facts, no transcript", which is the exact failure
    this report exists to prevent, so the roots tried are bounded and explicit:
    the cwd, the results document's own directory and up to ``max_ancestors``
    of its ancestors, then this repo's root. Nothing found keeps the recorded
    string and says it is unresolved rather than pointing at an empty path."""
    p = Path(raw)
    if p.is_absolute():
        return p, "absolute path as recorded"
    roots: list[Path] = [Path.cwd()]
    if doc_dir is not None:
        roots.append(Path(doc_dir))
        roots.extend(list(Path(doc_dir).parents)[:max_ancestors])
    roots.append(REPO_ROOT)
    for root in roots:
        cand = root / p
        if cand.exists():
            return cand, f"relative path resolved against {root}"
    return p, "relative path unresolved (kept as recorded)"


def reports_from_results(doc: dict, doc_dir: Path | None = None) -> list[dict]:
    """One report per row of a kunglao eval-results document."""
    out = []
    for row in doc.get("rows") or []:
        ws_raw = (row.get("loop") or {}).get("workspace")
        if not ws_raw:
            continue
        ws, ws_src = resolve_artifact(ws_raw, doc_dir)
        out.append(sample_report(ws, task_id=row.get("task_id"),
                                 tier=doc.get("tier"), row=row,
                                 doc_dir=doc_dir, workspace_source=ws_src))
    return out


def _print_table(reports: list[dict]) -> None:
    print(f"{'unit':<26}{'verdict':<9}{'facts':>7}{'orch_out':>11}"
          f"{'wkr_out':>10}{'wall_s':>9}{'disp':>6}{'human':>7}")
    for r in reports:
        s = r.get("sample") or {}
        a = r.get("accuracy") or {}
        t = r.get("tokens") or {}
        orch = t.get("orchestrator") or {}
        wkr = t.get("worker") or {}
        print(f"{str(s.get('unit'))[:25]:<26}{str(a.get('verdict')):<9}"
              f"{(r.get('facts') or {}).get('total', 0):>7}"
              f"{str(orch.get('output_tokens')):>11}"
              f"{str(wkr.get('output_tokens')):>10}"
              f"{str((r.get('wall') or {}).get('wall_s')):>9}"
              f"{str((r.get('dispatch') or {}).get('dispatch_count')):>6}"
              f"{str((r.get('human') or {}).get('user_turn_count')):>7}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="one capability report per eval sample")
    ap.add_argument("--results", help="a kunglao eval-results-*.json doc")
    ap.add_argument("--workspace", help="a single sample workspace")
    ap.add_argument("--task", help="the unit id (with --workspace)")
    ap.add_argument("--tier", help="the corpus tier (optional)")
    ap.add_argument("--regrade", action="store_true",
                    help="run the minted-probe + re-run legs (toolchain)")
    ap.add_argument("--out",
                    help=f"output dir (default {DEFAULT_OUT_REL}/<utc-ts>)")
    args = ap.parse_args(argv)

    if not args.results and not args.workspace:
        print("REFUSE: give --results <doc> or --workspace <ws>",
              file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else (
        REPO_ROOT / DEFAULT_OUT_REL /
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))

    reports: list[dict] = []
    if args.results:
        try:
            doc = json.loads(Path(args.results).read_text(encoding="utf-8",
                                                          errors="replace"))
        except (OSError, ValueError) as exc:
            print(f"REFUSE: cannot read --results: {exc}", file=sys.stderr)
            return 2
        reports = reports_from_results(doc, Path(args.results).parent)
        if not reports:
            print("REFUSE: no row in that document names a workspace",
                  file=sys.stderr)
            return 2
    else:
        ws = Path(args.workspace)
        if not ws.is_dir():
            print(f"REFUSE: not a directory: {ws}", file=sys.stderr)
            return 2
        reports = [sample_report(ws, task_id=args.task, tier=args.tier,
                                 regrade=args.regrade, outdir=out_dir)]

    paths = []
    for r in reports:
        unit = re.sub(r"[^A-Za-z0-9_.-]", "_",
                      str((r.get("sample") or {}).get("unit") or "sample"))
        paths.append(_write(out_dir, f"capability-{unit}.json", r))
    summary = aggregate(reports)
    summary["reports"] = [str(p) for p in paths]
    _write(out_dir, "summary.json", summary)

    print(f"CAPABILITY-REPORTS {out_dir} samples={len(reports)}")
    _print_table(reports)
    print(f"answer_rate={summary['answer_rate']:.2f} "
          f"gt_accuracy_over_all={summary['gt_accuracy_over_all']:.2f} "
          f"gt_accuracy_answered={summary['gt_accuracy_answered']:.2f} "
          f"proven_with_evidence_rate="
          f"{summary['proven_with_evidence_rate']:.2f} "
          f"cost_per_correct_solution_tokens="
          f"{cost_fmt(summary['cost'])} "
          f"absent={summary['units_absent']}")
    return 0


def cost_fmt(cost: dict) -> str:
    """One printable line for the cost face: the token denominator first, the
    dollar figure only as a covered subset with its share."""
    dollars = cost.get("dollars_secondary") or {}
    usd = dollars.get("cost_per_correct_solution_usd")
    share = dollars.get("coverage")
    samples = int(cost.get("samples") or 0)
    covered = int(cost.get("tokens_covered_samples") or 0)
    return (f"{cost.get('cost_per_correct_solution_tokens')} tokens "
            f"(on {covered}/{samples} covered samples; usd secondary "
            f"{usd if usd is not None else 'absent'} on "
            f"{(f'{share:.0%}' if isinstance(share, float) else '0%')} "
            f"of samples)")


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
