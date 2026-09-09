#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_cadence.py — the oracle reward channel's mechanical cadence (#132).

The oracle red/green channel (#97/#108) was wired-but-blind at the input
side: scripts/oracle_runner.py had no mechanical caller in the live loop —
its only production reference was an instruction embedded in a decide action
string (convergence_check.py), so whether the reward signal ever fired
depended on the orchestrator LLM obeying a sentence. A reward channel whose
triggering is LLM-discretionary can starve the posterior economy silently
while every mechanism above it stays green.

This module is the settlement-cadence hook the loop now calls MECHANICALLY
(outcome_capture._settle_new fires it once per capture batch that produced a
new settlement — once per BATCH, not per settled claim, because a case-set
run per claim would record identical Bernoulli observations twice and
double-count confidence into the Beta posterior):

    has armed cases (<ws>/oracle/cases/*.yaml)?
      no  -> no-op (nothing armed, nothing owed — legacy workspaces are
              byte-unaffected)
      yes -> registered client (<ws>/oracle/client.py, the #108 load_client
              contract shape) beats per-call CLI args (issue fix 1):
        no registered client      -> LOUD ``oracle_cadence_warn`` event; no
                                     status, no posterior touch (pending is
                                     the honest unknown — never fabricated)
        broken client (won't      -> LOUD warn + ALL armed cases RED: status
        load / won't import)         written all-red + red Bernoulli
                                     observations recorded — fail-loud, the
                                     reward channel screams instead of
                                     quietly pending ("never skip", issue 2)
        case set refused (#126)   -> LOUD warn; no status file (the runner's
                                     own refusal contract — a refusal must
                                     never degenerate into a green status)
        runner failure (other)    -> LOUD warn; never a silent skip
        run OK                    -> runs/oracle-status.json + posteriors
                                     updated + the #108 mutation pass run
                                     ROUTINELY (mutation=True — the
                                     discipline made mechanical, issue
                                     amendment 2) + the separation
                                     observation below

Separation observation (issue #132 amendment 1 — the empirical twin of
#126's declared update_map tooth): every real verdict (pass/fail) is
appended to ``runs/oracle-cadence.jsonl`` keyed by the case id and a content
fingerprint of the client (same digest convention as load_client — distinct
bytes = distinct candidate). When a case GREENS under a NEW distinct client
and that makes >=2 distinct greening candidates, a ``case_vacuous`` event is
emitted: the case's outcome is invariant across the hypothesis space, it
measures the environment, not the model (#126 admission checks the
DECLARATION, cadence observes the FACT). A single-client green emits
nothing; a re-run of an already-seen client emits nothing more.

Loud missing-intent census (issue fix 3): ``missing_intent_face`` counts,
mechanically and read-only, the two faces of a missing uncertainty
declaration — ``intent_unparsed`` events on the unified log (#105's word;
the dispatch face emits it since #105, the settlement face since #132) and
distinct captured outcome claims with no recorded intent (the
predicted-vs-actual comparison that went missing silently before #132).
Counted + surfaced, NOT gating: the dispatch flow is unchanged.

This card does NOT modify oracle_runner.py (#126 owns that file in wave 1);
every runner face here is consumed, never restated.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import kunglao_log
from kunglao_log import iter_jsonl  # #863 Family K single source
from outcome_capture import read_outcome_rows  # tolerant OUTCOME-row read

# #132 event faces (registered in event_taxonomy.EMIT_ACTIONS; the emit_gate
# forward net requires the production literal in scripts/*.py — kept as
# literals right here at the emit sites).
_CADENCE_WARN = "oracle_cadence_warn"
_CASE_VACUOUS = "case_vacuous"

CADENCE_LOG_REL = ("runs", "oracle-cadence.jsonl")

_ACTOR = "outcome_capture"  # the cadence fires inside the settlement path


def _cadence_log(ws: Path) -> Path:
    return Path(ws).joinpath(*CADENCE_LOG_REL)


def read_cadence_rows(ws) -> list[dict]:
    """Tolerant read of the cadence verdict log (blank/junk lines skipped)."""
    p = _cadence_log(ws)
    if not p.exists():
        return []
    return [row for row in iter_jsonl(
        p.read_text(encoding="utf-8", errors="replace").splitlines())
        if isinstance(row, dict)]


def _append_cadence_row(ws: Path, row: dict) -> None:
    p = _cadence_log(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _has_armed_cases(ws: Path) -> bool:
    import oracle_runner as orun
    cases_dir = Path(ws).joinpath(*orun.CASES_REL)
    return cases_dir.is_dir() and any(cases_dir.glob("*.yaml"))


def _registered_client(ws: Path) -> Path | None:
    """The client-registration convention (#132 fix 1): a fixed workspace
    location beats per-call CLI args; oracle_runner.load_client already
    consumes this contract shape (DEFAULT_CLIENT_REL)."""
    import oracle_runner as orun
    p = Path(ws).joinpath(*orun.DEFAULT_CLIENT_REL)
    return p if p.is_file() else None


def client_fingerprint(client_path) -> str:
    """Content fingerprint of a candidate client (same 16-hex digest
    convention as oracle_runner.load_client's snapshot naming): distinct
    bytes = distinct candidate implementation for the separation face."""
    source = Path(client_path).read_text(encoding="utf-8")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _warn(ws: Path, reason: str, detail: str,
          claim: str | None = None) -> None:
    """The loud face: a kunglao_log warn event. Never a silent skip — the
    unified log is the durable signal a human/cockpit can query."""
    kunglao_log.emit(ws, actor=_ACTOR, action=_CADENCE_WARN, claim=claim,
                     detail=f"reason={reason}: {detail}")


def _all_red_report(cases_dir: Path, cases: list[dict], client_path,
                    error: str) -> dict:
    """Issue fix 2, fail-loud face: a broken registered client is NEVER
    "skip" — every armed case lands RED (status file + red Bernoulli
    observations) so the DRAIN probe and the posterior economy both see the
    broken instrumentation scream instead of quietly pending."""
    import oracle_runner as orun
    rows = {}
    for c in cases:
        pending_entries = sum(1 for e in c["expected"] if e["pending"])
        rows[c["id"]] = {"status": "fail", "pending_entries": pending_entries,
                         "instrumented": True,
                         "failures": ["client broken — verdict forced red "
                                      "(#132: fail-loud, never skip)"],
                         "error": error}
    return {"schema": orun.SCHEMA_ID,
            "cases_dir": str(cases_dir),
            "client": str(client_path),
            "cases": rows,
            "counts": {"red": len(cases), "green": 0, "pending": 0},
            "mutation": None}


def _observe_vacuous(ws: Path, report: dict, client_path) -> list[str]:
    """#132 amendment: SEPARATION observation at cadence. Append this run's
    real verdicts to the cadence log; fire ``case_vacuous`` when a case
    greens under a NEW distinct client and crosses to >=2 distinct greening
    candidates. Returns the case ids the event fired for."""
    sha = client_fingerprint(client_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    greeners: dict[str, set[str]] = {}
    for row in read_cadence_rows(ws):
        if row.get("status") == "pass":
            greeners.setdefault(str(row.get("case_id")), set()).add(
                str(row.get("client_sha")))
    fired: list[str] = []
    for cid, row in report["cases"].items():
        if row["status"] not in ("pass", "fail"):
            continue  # pending is not an observation — nothing to append
        _append_cadence_row(ws, {"ts": now, "case_id": cid,
                                 "client_sha": sha,
                                 "status": row["status"]})
        if row["status"] != "pass":
            continue
        known = greeners.get(cid, set())
        if known and sha not in known:
            # this green is a NEW distinct candidate: the greening set just
            # crossed >=2 — the case greens under every candidate tried, so
            # it measures the environment, not the model (case_vacuous)
            kunglao_log.emit(
                ws, actor=_ACTOR, action=_CASE_VACUOUS,
                detail=json.dumps(
                    {"case_id": cid, "greening_clients": len(known) + 1,
                     "client_sha": sha}, sort_keys=True, ensure_ascii=False))
            fired.append(cid)
    return fired


def run_cadence(ws, *, claim: str | None = None) -> dict:
    """One mechanical cadence pass over the workspace's armed case set.

    Returns a summary dict ({fired, ran, counts, reason, ...}); every
    failure face emits its ``oracle_cadence_warn`` event HERE, so the
    settlement caller stays fail-open without ever going silent. See the
    module docstring for the per-face contract."""
    ws = Path(ws)
    import oracle_runner as orun
    if not _has_armed_cases(ws):
        return {"fired": False, "reason": "no_armed_cases"}
    client_path = _registered_client(ws)
    if client_path is None:
        _warn(ws, "client_not_registered",
              f"armed cases exist but no implementation-under-test is "
              f"registered at <ws>/{'/'.join(orun.DEFAULT_CLIENT_REL)} — "
              f"the reward channel cannot fire (register the client; "
              f"pending is not fabricated)", claim=claim)
        return {"fired": True, "ran": False, "reason": "client_not_registered"}
    try:
        # #126 admission lint first: a refusal must stay a refusal (no
        # status file — the runner's own contract), but LOUD via the event.
        cases = orun.load_cases(ws.joinpath(*orun.CASES_REL))
    except orun.OracleCaseError as exc:
        _warn(ws, "case_set_refused", str(exc), claim=claim)
        return {"fired": True, "ran": False, "reason": "case_set_refused"}
    try:
        # broken-client probe BEFORE the run: a present-but-unloadable
        # client is all-red + warn, never "no client" pending clothes.
        orun.load_client(client_path)
    except Exception as exc:  # noqa: BLE001 — ANY unloadable client is broken
        _warn(ws, "client_broken", f"{client_path}: {exc!r}", claim=claim)
        report = _all_red_report(ws.joinpath(*orun.CASES_REL), cases,
                                 client_path, repr(exc))
        orun.write_status(ws, report)
        orun.record_posteriors(ws, report)
        return {"fired": True, "ran": True, "reason": "client_broken",
                "counts": report["counts"], "vacuous": []}
    try:
        # mutation=True: the #108 mutation-must-fail discipline made
        # routine (#132 amendment 2) — no discretionary flag anymore.
        report = orun.run(ws.joinpath(*orun.CASES_REL), client_path,
                          mutation=True)
    except Exception as exc:  # noqa: BLE001 — a runner failure is loud
        _warn(ws, "runner_failed", repr(exc), claim=claim)
        return {"fired": True, "ran": False, "reason": "runner_failed"}
    orun.write_status(ws, report)
    orun.record_posteriors(ws, report)
    vacuous = _observe_vacuous(ws, report, client_path)
    return {"fired": True, "ran": True, "reason": "ok",
            "counts": report["counts"], "vacuous": vacuous}


def missing_intent_face(ws) -> dict:
    """#132 fix 3: the loud missing-intent census (counted, never gating).

    Two mechanical counts, both read-only:
      intent_unparsed_events   — rows on the unified log carrying the #105
                                 word (dispatch face since #105; the
                                 settlement face emits the same word since
                                 #132 when a captured outcome's claim has no
                                 recorded intent);
      unintended_outcome_claims — distinct captured outcome claims with no
                                 recorded intent in runs/roi-intents.jsonl:
                                 the predicted-vs-actual comparison signal
                                 that silently never settled before #132.
    """
    ws = Path(ws)
    unparsed = 0
    logs = ws / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for row in iter_jsonl(text.splitlines()):
                if isinstance(row, dict) \
                        and row.get("action") == "intent_unparsed":
                    unparsed += 1
    try:
        import roi_settlement
        intended = {r.get("claim_id")
                    for r in roi_settlement.read_intents(ws)}
    except Exception:  # noqa: BLE001 — a census never raises
        intended = set()
    unintended: list[str] = []
    for row in read_outcome_rows(ws):
        cid = row.get("claim_id")
        if cid and cid not in intended and cid not in unintended:
            unintended.append(str(cid))
    return {"intent_unparsed_events": unparsed,
            "unintended_outcome_claims": unintended}


if __name__ == "__main__":  # pragma: no cover — the CLI face is the hook's
    # single caller (outcome_capture); a direct run prints the census only.
    import sys

    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    if len(sys.argv) != 2:
        print("usage: oracle_cadence.py <workspace>  (prints the missing-"
              "intent census; the cadence itself is settlement-hooked)",
              file=sys.stderr)
        raise SystemExit(64)
    print(json.dumps(missing_intent_face(Path(sys.argv[1])),
                     ensure_ascii=False, indent=2))
