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


def _linked_case_ids(ws: Path, pq: str) -> list[str]:
    """Oracle case ids whose ``target_pq`` is ``pq`` — the
    answers_question <-> target_pq linkage the ranker and the failure
    gate both key on. Deterministic file order; a broken case doc is
    skipped (an unreadable case is not evidence)."""
    import yaml

    cdir = ws / "oracle" / "cases"
    if not cdir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(cdir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(
                path.read_text(encoding="utf-8", errors="replace")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict) \
                or str(doc.get("target_pq") or "").strip() != pq:
            continue
        cid = str(doc.get("id") or path.stem).strip()
        if cid:
            out.append(cid)
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
    A claim without answers_question, or a question no case targets,
    writes nothing — the honest cold start, never a fabricated bucket.
    Idempotent at any wall-clock distance: only the freshly banked
    dispatches are observed, so re-runs add nothing. Fail-open: the
    breakage is a counted error field, never a pass break."""
    out = {"case_observations": 0, "cases_passed": 0, "cases_failed": 0}
    try:
        outcomes = {str(c["id"]): (
                        str(c.get("status") or "").upper(),
                        str(c.get("answers_question") or "").strip())
                    for c in _register_claims(ws)}
        entries: list[tuple[str, bool]] = []  # (case_id, passed)
        for did in banked:
            status, pq = outcomes.get(str(did), ("", ""))
            if status in CASE_PASS_STATUSES:
                passed = True
            elif status in CASE_FAIL_STATUSES:
                passed = False
            else:
                continue
            if not pq:
                continue
            entries.extend((cid, passed)
                           for cid in _linked_case_ids(ws, pq))
        if not entries:
            return out
        import posteriors as po  # the posterior-ledger leaf
        led = po.PosteriorLedger.load(ws)
        for cid, passed in entries:
            cp = led.cases.get(cid) or po.CasePosterior(cid)
            cp.update(passed)
            led.cases[cid] = cp
        led.save(ws)
        passed_n = sum(1 for _, ok in entries if ok)
        out["case_observations"] = len(entries)
        out["cases_passed"] = passed_n
        out["cases_failed"] = len(entries) - passed_n
        return out
    except Exception as exc:  # noqa: BLE001 - telemetry, never a pass break
        warn("case_settlements", f"{type(exc).__name__}: {exc}")
        out["case_observations_error"] = f"{type(exc).__name__}: {exc}"
        return out


def _round_credit_pass(ws: Path, dispatches: list[dict], *,
                       dry_run: bool) -> dict:
    """The round-credit leg: grade (dry run) or settle + bank one round
    per dispatch. Telemetry posture: any failure inside degrades to an
    error field, never a crash (the tick must not die)."""
    try:
        from rlvr.scalar import fact_artifacts
        artifacts = fact_artifacts(ws)
        if dry_run:
            from rlvr.scalar import round_credit
            doc = round_credit(dispatches, artifacts, [])
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
    if dispatches:
        out = _round_credit_pass(ws, dispatches, dry_run=dry_run)
        banked = [str(d) for d in (out.pop("banked", None) or [])]
        if not dry_run:
            # the case-posterior leg keys on the dispatches this pass
            # FIRST-settled (the bank list): replays and amendments
            # observe nothing, so re-runs stay byte-identical no-ops
            out["banked"] = len(banked)
            out.update(record_case_settlements(ws, banked))
    else:
        out = {"settled": 0, "rounds": 0,
               "reason": "no terminal claims - nothing to settle"}
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
