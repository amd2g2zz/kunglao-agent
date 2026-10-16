#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle_round_credit.py - #634: the LIVE round-credit settlement feed.

The dispatch observations (worker_budget_sinks -> q_cells) accumulate as
pending mass; ``rlvr.scalar.settle_round_credit`` - the ONE face that
grades the issue-433 ladder credit and banks it into the matching Q cell
(#462 W5) - had NO live caller (only compat re-exports and the eval
harness). This CLI is that caller, wired as the registry mechanism
``credit_settle`` (channel: tick): per pass it assembles one round per
TERMINAL claim (``dispatch_id`` = the claim id - the dispatch ALLOW
tail's echo / ``observe_settlement``'s match key) plus the fact-artifact
rows (``rlvr.scalar.fact_artifacts``) and runs the settlement.

Idempotent at any wall-clock distance: the identity-ts freeze plus the
settlement-presence guard inside settle_round_credit dedupe record and
settle (re-runs are byte-identical no-ops). No terminal claim -> no work.

Eager-banking note (#462 W5, by design): the FIRST successful settlement
of a dispatch banks its then-current ladder value into the Q cell; the
late-cite amendment path refines the LEDGER only (the observation log is
append-only, so re-banking would double-count). The ladder grades what
EXISTS - verified-but-uncited facts read as trace, and a missing pending
dispatch row is the honest gap (a rate-limited warn, never a fabricated
bucket).

Two further legs ride the SAME pass (the live-seam wiring): the bank's
matched arm_key/fingerprint key a cross-task posterior-store row
(rlvr.strategy_store), the settled claim's decisive status records one
Bernoulli observation per linked oracle case in the posterior ledger the
ranker prices claims from, and the episode-tier amendment
(rlvr.scalar.settle_workspace_scalars) revives the experience-tuple /
scalar-prior feed. Every leg shares this pass's posture: idempotent at
any wall-clock distance (the first-settlement guard is the clock) and
fail-open (a broken leg is a counted error field or a rate-limited warn,
never a crash and never a fabricated row).

The case-observation leg runs TWICE per pass, on one invariant: every
(armed case, decisive-terminal claim linked to its target_pq) pair is
observed EXACTLY ONCE, whatever the arming order. The fresh leg
(``record_case_settlements``) covers claims settling now; the late-arm
amendment (``amend_case_settlements``) sweeps claims that settled BEFORE
their case was armed — the live ordering, in which the fresh leg alone
leaves ``runs/posteriors.yaml`` uncreated forever. Each observation is
an auditable ``case-observation/1`` row in the consolidated experience
ledger, and those rows ARE the amendment's dedup record (no separate
bookkeeping to drift).

Usage:
  python settle_round_credit.py <workspace> [--json]
Exit codes: 0 ok (including nothing-to-do) / 2 usage / 3 not a workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation


def _register_claims(ws: Path) -> list[dict]:
    """The claim-register rows (id-bearing mappings). Tolerant read:
    unreadable/invalid register -> [] (nothing to settle is never an
    error for this telemetry face)."""
    import yaml

    try:
        doc = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    return [c for c in (doc or {}).get("claims") or []
            if isinstance(c, dict) and c.get("id")]


def terminal_claims(ws: Path) -> list[str]:
    """Claim ids whose register status is terminal (the settlement set)."""
    from status_defs import TERMINAL

    return [str(c["id"]) for c in _register_claims(ws)
            if str(c.get("status") or "").upper() in TERMINAL]


# the credit ladder's own decisive vocabulary: a claim settling under
# either set is a pass / fail observation on every oracle case linked to
# the claim's answers_question; every other terminal status reflects
# nothing about the case (pending is never an observation).
CASE_PASS_STATUSES = frozenset({"PROVEN", "VERIFIED"})
CASE_FAIL_STATUSES = frozenset({"NEGATIVE", "REFUTED"})


# the oracle-arm arming fields: a case doc carrying ALL five (non-empty)
# is ARMED — a complete, deliberate question-linkage. Arming is NOT
# runner-loadability (the loader's `expected` shape differs; tracked as
# its own defect). A thinner doc is readable but not armed. The armed
# count is what makes the live silent gap LOUD: without oracle/cases/
# no case posterior ever moved — invisibly.
CASE_ARMING_FIELDS = ("channel", "hypothesis_ref", "update_map",
                      "expected", "mutations")


def _arming_field_present(doc: dict, field: str) -> bool:
    """One arming field non-empty: ``expected`` must carry a non-empty
    ``evidence_refs`` list; mappings/lists must be non-empty; scalars
    must be non-blank strings."""
    value = doc.get(field)
    if field == "expected":
        return (isinstance(value, dict)
                and bool(value.get("evidence_refs")))
    if isinstance(value, (dict, list)):
        return bool(value)
    return bool(str(value or "").strip())


def armed_case_ids(ws: Path) -> set[str]:
    """Case ids whose oracle/cases/*.yaml doc is ARMED (every field in
    CASE_ARMING_FIELDS present and non-empty). Deterministic file order;
    a broken or non-mapping case doc is skipped (an unreadable case is
    never armed). Fail-open: never raises into the tick."""
    import yaml

    cdir = Path(ws) / "oracle" / "cases"
    if not cdir.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(cdir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(
                path.read_text(encoding="utf-8", errors="replace")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        if not all(_arming_field_present(doc, f)
                   for f in CASE_ARMING_FIELDS):
            continue
        cid = str(doc.get("id") or path.stem).strip()
        if cid:
            out.add(cid)
    return out


CASE_OBS_SCHEMA = "case-observation/1"


def _empty_obs() -> dict:
    return {"case_observations": 0, "cases_passed": 0, "cases_failed": 0}


def _cases_by_pq(ws: Path, *, armed_only: bool) -> dict[str, list[str]]:
    """Case ids grouped by ``target_pq`` — ONE scan per observation leg,
    the answers_question <-> target_pq link index.

    ``armed_only`` is the one axis the two legs differ on, and the
    difference is deliberate:

    - the AMENDMENT back-fills claims that settled before their case
      existed, so it must only write cases that are complete, deliberate
      question-linkages. ``armed_only`` requires every field of
      CASE_ARMING_FIELDS (the same five the acceptance net arms on): a
      stub doc with a bare ``target_pq`` is not a hypothesis anybody
      committed to, and observing against it would move a posterior on
      the strength of a placeholder.
    - the FRESH leg keeps the link it has always had (``target_pq``
      alone). Tightening it is a behaviour change with its own blast
      radius and is NOT part of this change.

    Retired cases are skipped by BOTH legs, mirroring the runner's
    loader: a case retired out of the acceptance net must not keep
    collecting observations.

    NOTE — arming is NOT runner-loadability. The arming shape and the
    runner's ``load_cases`` shape disagree on ``expected`` (mapping with
    ``evidence_refs`` vs a non-empty list of entries), so a doc can be
    armed-but-not-loadable or loadable-but-not-armed. That mismatch is a
    pre-existing defect in the arming definition, tracked separately; the
    observation legs key on the ARMING definition, not on loadability.

    Deterministic file order; duplicate case ids collapse (the pair is
    the unit, so a second doc claiming the same id is the same case); a
    broken or non-mapping doc is skipped."""
    import yaml

    cdir = Path(ws) / "oracle" / "cases"
    out: dict[str, list[str]] = {}
    if not cdir.is_dir():
        return out
    for path in sorted(cdir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(
                path.read_text(encoding="utf-8", errors="replace")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "").strip().lower() == "retired":
            continue
        if armed_only and not all(_arming_field_present(doc, f)
                                  for f in CASE_ARMING_FIELDS):
            continue
        pq = str(doc.get("target_pq") or "").strip()
        cid = str(doc.get("id") or path.stem).strip()
        if pq and cid and cid not in out.setdefault(pq, []):
            out[pq].append(cid)
    return out


def _observed_pairs(ws: Path) -> set[tuple[str, str]]:
    """The (case_id, claim_id) pairs already observed — read back from
    the consolidated experience ledger, whose ``case-observation/1`` rows
    ARE the dedup record. Making the record explicit is what lets an
    observation depend on the PAIR rather than on which pass happened to
    be running when the case was armed."""
    from rlvr import consolidated_ledger as cl

    out: set[tuple[str, str]] = set()
    for row in cl.read(ws, "experience",
                       schema_prefix=CASE_OBS_SCHEMA.split("/")[0]):
        cid = str(row.get("case_id") or "").strip()
        claim = str(row.get("claim_id") or "").strip()
        if cid and claim:
            out.add((cid, claim))
    return out


def _observation_entries(claims: list[dict], index: dict[str, list[str]],
                         seen: set[tuple[str, str]]
                         ) -> list[tuple[str, str, bool]]:
    """Decisive claims -> (case, claim, passed) entries, skipping every
    pair already in ``seen`` — which this EXTENDS as it builds, so a
    duplicate case id, a duplicate claim, or a second leg arriving at the
    same pair all collapse. The pair is the unit of observation; nothing
    downstream re-checks it."""
    entries: list[tuple[str, str, bool]] = []
    for claim in claims:
        status = str(claim.get("status") or "").upper()
        if status in CASE_PASS_STATUSES:
            passed = True
        elif status in CASE_FAIL_STATUSES:
            passed = False
        else:
            continue
        pq = str(claim.get("answers_question") or "").strip()
        claim_id = str(claim.get("id") or "").strip()
        if not pq or not claim_id:
            continue
        for cid in index.get(pq, ()):
            key = (cid, claim_id)
            if key in seen:
                continue
            seen.add(key)
            entries.append((cid, claim_id, passed))
    return entries


def _apply_case_observations(ws: Path, entries: list[tuple[str, str, bool]],
                             source: str) -> dict:
    """The one observation face: the closed-form posterior update for
    every entry, then one auditable ``case-observation/1`` row per entry.

    The BELIEF is written first, deliberately — the two failure windows
    are not equally bad. Rows-without-the-posterior would leave the pair
    reading as observed forever while the belief never moved: a
    permanent, SILENT gap. Belief-first fails the other way: if the rows
    never land the pair is never marked seen, so every following pass
    re-observes it and the posterior keeps moving.

    That second failure is NOT self-healing even when the write does
    recover: the retried row lands and marks the pair seen, but the
    belief update from the failed pass is already banked — one Bernoulli
    event moves the posterior twice. And for as long as the rows stay
    refused, EVERY following pass re-observes, so the posterior keeps
    moving while ``case_observations`` (which counts rows that actually
    landed) reads lower than the posterior's mass. The error field is
    what makes that divergence loud, and on a shortfall it is set on
    EVERY pass rather than once. ``cases_passed``/``cases_failed`` count
    the entries the pass attempted, not the rows that landed.

    Both failures are counted; neither raises."""
    out = _empty_obs()
    try:
        if not entries:
            return out
        import posteriors as po  # the posterior-ledger leaf
        from rlvr import consolidated_ledger as cl
        from harness_common import utc_now_z  # the one timestamp source

        led = po.PosteriorLedger.load(ws)
        for cid, _claim, passed in entries:
            cp = led.cases.get(cid) or po.CasePosterior(cid)
            cp.update(passed)
            led.cases[cid] = cp
        led.save(ws)
        ts = utc_now_z()
        landed = sum(
            1 for cid, claim, passed in entries
            if cl.append(ws, "experience", {
                "schema": CASE_OBS_SCHEMA, "ts": ts, "case_id": cid,
                "claim_id": claim, "passed": bool(passed),
                "source": source}))
        passed_n = sum(1 for _, _, ok in entries if ok)
        out["case_observations"] = landed
        out["cases_passed"] = passed_n
        out["cases_failed"] = len(entries) - passed_n
        if landed != len(entries):
            out["case_observations_error"] = (
                f"{len(entries) - landed} observation row(s) refused")
        return out
    except Exception as exc:  # noqa: BLE001 - telemetry, never a pass break
        warn("case_settlements", f"{type(exc).__name__}: {exc}")
        out["case_observations_error"] = f"{type(exc).__name__}: {exc}"
        return out


def record_case_settlements(ws: Path, banked: list[str]) -> dict:
    """The ranker's live posterior-update leg: for every dispatch this
    pass newly banked, record ONE Bernoulli observation per linked oracle
    case in the posterior ledger (``runs/posteriors.yaml``) the ranker
    prices every dispatchable claim from.

    The ledger had no live writer: the ranking sampled the wide Beta(1,1)
    prior forever and no settled claim ever moved a case posterior. A
    claim settling PROVEN/VERIFIED (the credit ladder's admission
    vocabulary) passes; NEGATIVE/REFUTED fails; every other terminal
    status records nothing, the same posture the runner's recorder holds.
    A claim without answers_question, or a question no case doc targets,
    writes nothing — the honest cold start, never a fabricated bucket.
    This leg links on ``target_pq`` alone and does NOT filter on arming;
    only the amendment does (see below).

    ``banked`` is the FIRST-settlement set (the settle path's clock), so
    in production each claim reaches this leg at most once. The pair-level
    dedup still applies: a retry pass banking a claim an earlier amendment
    already observed must NOT observe it again. Fail-open: the breakage is
    a counted error field, never a pass break.

    The ARMING-ORDER gap this leg cannot reach (a case armed after its
    claims settled is unreachable from here) is
    ``amend_case_settlements``'s job."""
    try:
        by_id = {str(c.get("id")): c for c in _register_claims(ws)}
        claim_set = [by_id[str(d)] for d in banked if str(d) in by_id]
        entries = _observation_entries(
            claim_set, _cases_by_pq(ws, armed_only=False),
            _observed_pairs(ws))
        return _apply_case_observations(ws, entries, source="fresh")
    except Exception as exc:  # noqa: BLE001 - telemetry, never a pass break
        warn("case_settlements", f"{type(exc).__name__}: {exc}")
        out = _empty_obs()
        out["case_observations_error"] = f"{type(exc).__name__}: {exc}"
        return out


def amend_case_settlements(ws: Path) -> dict:
    """The late-arm amendment: sweep EVERY decisive-terminal claim against
    the ARMED cases and observe each un-observed pair.

    ``record_case_settlements`` keys on ``banked`` — the dispatches whose
    first settlement rode the current pass. That guard bought idempotency
    at the cost of ARMING ORDER: a case armed after its claims settled can
    never observe them (their ids never re-enter ``banked``), so
    ``runs/posteriors.yaml`` is never created in the live ordering and the
    ranker prices every claim from the wide Beta(1,1) prior forever. The
    late-arm ordering is the COMMON one — you learn what to ask after the
    first claims land.

    Idempotent at any wall-clock distance: the dedup set is read from the
    ledger's own ``case-observation/1`` rows, so a re-run is a no-op and
    the belief stays reconcilable with the evidence that produced it.
    Fail-open: a counted error field, never a pass break."""
    try:
        index = _cases_by_pq(ws, armed_only=True)
        if not index:
            return _empty_obs()
        entries = _observation_entries(
            _register_claims(ws), index, _observed_pairs(ws))
        return _apply_case_observations(ws, entries, source="late-arm")
    except Exception as exc:  # noqa: BLE001 - telemetry, never a pass break
        warn("case_settlements", f"{type(exc).__name__}: {exc}")
        out = _empty_obs()
        out["case_observations_error"] = f"{type(exc).__name__}: {exc}"
        return out


def _round_credit_pass(ws: Path, dispatches: list[dict], *,
                       dry_run: bool) -> dict:
    """The round-credit leg: grade (dry run) or settle + bank one round
    per dispatch. Telemetry posture: any failure inside degrades to an
    error field, never a crash (the tick must not die)."""
    try:
        from rlvr.scalar import backfill_artifact_creators, fact_artifacts
        artifacts = fact_artifacts(ws)
        if dry_run:
            from rlvr.scalar import round_credit
            # the SAME backfill the settle path applies, so the dry-run
            # grade matches what a real pass would settle (issue-678 T3)
            dispatch_ids = [str(d.get("dispatch_id") or "")
                            for d in dispatches]
            graded = backfill_artifact_creators(artifacts, dispatch_ids)
            doc = round_credit(dispatches, graded, [])
            return {"settled": 0, "rounds": len(dispatches),
                    "artifacts": len(artifacts), "dry_run": True,
                    "would_settle": len(doc.get("rows") or []),
                    "untraced": len(doc.get("untraced") or []),
                    "rewards": [r.get("r") for r in doc.get("rows") or []]}
        from rlvr.scalar import settle_round_credit
        res = settle_round_credit(ws, dispatches, artifacts, [])
    except Exception as exc:  # noqa: BLE001 - telemetry face, never a gate
        return {"settled": 0, "rounds": len(dispatches),
                "error": f"{type(exc).__name__}: {exc}"}
    return {"settled": int(res.get("settled") or 0),
            "rounds": len(dispatches), "artifacts": len(artifacts),
            "untraced": len(res.get("untraced") or []),
            "unattributed_waste": res.get("unattributed_waste", 0),
            # the first-settled dispatch ids (the case-posterior leg's
            # key set; run() consumes it and reports the count)
            "banked": [str(d) for d in (res.get("banked") or [])]}


def _pending_tier_rows(ws: Path) -> int:
    """Settled task rollouts whose settlement carries no tier scalar yet
    — the read-only dry-run face of the episode-tier leg."""
    from rlvr import ledger as rl

    return sum(1 for row in rl.settled(ws, kind="task")
               if "tier" not in (row.get("settlement") or {}))


def _settle_episode_tiers(ws: Path) -> dict:
    """The episode-tier leg: amend every settled task rollout whose
    settlement has no tier scalar yet (rlvr.scalar.settle_workspace_scalars
    — the episode settlement face that writes the experience-tuple birth
    certificate and feeds the continuous scalar prior).

    The amendment face had no live caller: episode tiers stayed unset,
    the tuple extraction view carried no episode rows, and the scalar
    observation feed stayed empty. Same idempotent + fail-open posture as
    the round-credit leg — a re-run amends nothing, and a failure
    degrades to an error field, never a crash (the tick must not die)."""
    try:
        from rlvr.scalar import settle_workspace_scalars
        res = settle_workspace_scalars(ws)
    except Exception as exc:  # noqa: BLE001 - telemetry face, never a gate
        return {"tiers_error": f"{type(exc).__name__}: {exc}"}
    return {"tiers_seen": int(res.get("seen") or 0),
            "tiers_settled": int(res.get("settled") or 0),
            "tiers_by_tier": res.get("by_tier") or {}}


def run(ws: Path, *, dry_run: bool = False) -> dict:
    """Assemble + settle one pass. Telemetry posture: any failure inside
    degrades to an error field, never a crash (the tick must not die).
    dry_run assembles and grades only — no ledger rows, no Q-cell bank.

    Both legs ride the pass: the round-credit settlement (+ its Q-cell
    bank and case-posterior observations) for the terminal-claim set, and
    the episode-tier amendment. The tier leg keys on settled task
    rollouts, not on the round-credit set, so it runs even when no
    terminal claim is currently dispatchable-visible."""
    claims = terminal_claims(ws)
    dispatches = [{"dispatch_id": cid, "round": i + 1}
                  for i, cid in enumerate(claims)]
    # issue-678 T5: the armed-case count rides EVERY pass (dry included)
    # — zero armed cases is the silent gap that kept
    # runs/posteriors.yaml from ever existing, now loud
    armed = armed_case_ids(ws)
    if not armed:
        warn("settle_round_credit.run",
             "no armed oracle cases (oracle/cases/*.yaml missing or "
             "lacking the arming fields channel/hypothesis_ref/"
             "update_map/expected.evidence_refs/mutations) — case "
             "posteriors never move (issue-678 T5)")
    if dispatches:
        out = _round_credit_pass(ws, dispatches, dry_run=dry_run)
        banked = [str(d) for d in (out.pop("banked", None) or [])]
        if not dry_run:
            out["banked"] = len(banked)
            # Fresh leg first, so the attribution stays meaningful: the
            # fresh run reports what THIS pass's bank list observed and
            # the amendment reports the back-fill. Both dedup against
            # the ledger, so the reverse order would still be
            # double-count safe — it would just credit every observation
            # to the amendment and report the fresh leg as a no-op.
            fresh = record_case_settlements(ws, banked)
            late = amend_case_settlements(ws)
            out["case_observations"] = (
                fresh["case_observations"] + late["case_observations"])
            out["cases_passed"] = (
                fresh["cases_passed"] + late["cases_passed"])
            out["cases_failed"] = (
                fresh["cases_failed"] + late["cases_failed"])
            out["case_observations_late_arm"] = late["case_observations"]
            errs = [leg["case_observations_error"]
                    for leg in (fresh, late)
                    if leg.get("case_observations_error")]
            if errs:
                out["case_observations_error"] = " | ".join(errs)
    else:
        out = {"settled": 0, "rounds": 0,
               "reason": "no terminal claims - nothing to settle"}
    out["cases_armed"] = len(armed)
    if dry_run:
        out["would_amend_tiers"] = _pending_tier_rows(ws)
    else:
        out.update(_settle_episode_tiers(ws))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#634 live round-credit settlement feed")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble + grade only; no ledger rows, no bank")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"settle_round_credit: not a kunglao workspace: {ws}",
              file=sys.stderr)
        return 3
    out = run(ws, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("settle_round_credit: " + ", ".join(
            f"{k}={v}" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
