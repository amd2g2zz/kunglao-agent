# -*- coding: utf-8 -*-
"""rlvr/disposition_producer.py — THE runtime disposition producer (issue-988).

The algebra and both consumers are landed: ``disposition.classify_episode``
+ ``write_row`` (the evidence-gated row), ``disposition_reward`` (the
bounded choice signal) and ``disposition_measure`` (the denominators).
What did not exist is the WRITER — nothing in production called
``write_row``, so ``settle_mission``'s disposition-signal face settled 0
on every mission.

This module writes ONE ``disposition/1`` row per TERMINAL claim at the
mission boundary. The producer supplies EVIDENCE only — the classifier
owns the verdict:

  claim           the claim-register row id
  authorization   ``task_spec.authorization``; empty targets => OUT_OF_SCOPE,
                  several targets => ambiguous (no rows + one warn)
  oracle          the terminal status PLUS a PASS resolved on the claim's
                  canonical verification surfaces (a status alone is a
                  completion claim, not a pass; the trust mirror never
                  counts)
  wall            the interruption classifier over a claim-bound session
                  record (it derives both anti-laundering legs itself)
  ledger          ``route_ledger.classify`` (routes / attempted / budget)
  act_outcomes    the claim's transition rows' outcome statuses
  session         minimal claim-bound record (the wall's binding leg)
  strategic       the claim's strategic_action row (action + propensity)

Determinism: the ts is DERIVED (the claim's settlement ts, else its
latest transition ts), because ``write_row`` refuses a divergent
rewrite — a second settle must rebuild the identical row. A mission
without a ``task_spec.authorization`` block writes nothing and warns
once: the classifier demands an explicit bool, and a missing context
must never read as authorized.
"""
from __future__ import annotations

from pathlib import Path

from kunglao_log import warn
from rlvr import authorization
from rlvr import disposition
from rlvr import interruption
from rlvr import route_ledger
from rlvr import strategic_action

#: the terminal claim statuses (pass + fail); anything else is skipped —
#: a claim still in flight has no episode end to classify
_TERMINAL_STATUSES = frozenset({"proven", "verified", "negative", "refuted"})

#: the derived-ts floor (a settled claim with no timestamped evidence)
_TS_FLOOR = "1970-01-01T00:00:00Z"


def _load_spec(ws: Path) -> dict:
    import ws_yaml  # noqa: PLC0415 — leaf face, import-light
    p = ws / "task_spec.yaml"
    try:
        doc = ws_yaml.yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError, ws_yaml.yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _load_claims(ws: Path) -> list[dict]:
    import ws_yaml  # noqa: PLC0415 — leaf face, import-light
    p = ws / "claim-register.yaml"
    try:
        doc = ws_yaml.yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError, ws_yaml.yaml.YAMLError):
        return []
    rows = (doc or {}).get("claims") if isinstance(doc, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _all_transitions(ws: Path) -> list[dict]:
    """The mission's transition rows, read ONCE (per-claim filtering
    happens in memory — a per-claim re-read would scan the append-only
    ledger once per claim)."""
    from rlvr import incremental_reward as ir  # noqa: PLC0415 — lazy
    try:
        return ir.read_transitions(ws)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        warn("rlvr.disposition_producer", f"transitions unreadable: {exc}")
        return []


def _transitions(rows: list[dict], claim: str) -> list[dict]:
    return [r for r in rows
            if str(r.get("dispatch_id") or r.get("claim_ref") or "") == claim]


def _settled_rows(ws: Path) -> list[dict]:
    from rlvr import ledger as _ledger  # noqa: PLC0415 — lazy
    try:
        return _ledger.settled(ws)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        warn("rlvr.disposition_producer", f"settlement read failed: {exc}")
        return []


def _claim_ts(claim: str, transitions: list[dict],
              settled_rows: list[dict]) -> str:
    """A DERIVED, stable stamp: write_row refuses a divergent rewrite, so
    a re-settle must rebuild the identical row. The claim's settlement
    stamp wins; the latest transition ts is the fallback."""
    for row in settled_rows:
        if str(row.get("rollout_id") or "") in (claim, f"task/{claim}"):
            ts = str((row.get("settlement") or {}).get("settled_ts") or "")
            if ts:
                return ts
    stamps = [str(r.get("ts") or "") for r in transitions if r.get("ts")]
    return max(stamps) if stamps else _TS_FLOOR


def _rel(ws: Path, p: str) -> str | None:
    """Workspace-relative posix path (the row cites workspace evidence);
    an outside path is kept verbatim (the rules table precedent)."""
    if not p:
        return None
    try:
        return Path(p).resolve().relative_to(ws.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def _wall(ws: Path, session: dict) -> tuple[dict | None, str | None]:
    """The two-leg wall AND its blocker reference, DERIVED by the
    interruption classifier — the same anti-laundering rule the algebra
    applies: only a session-bound, harness-corroborated env blocker
    yields both legs (and the row's ``wall_ref`` names the file)."""
    verdict = interruption.classify(session, ws)
    if verdict.get("class") != interruption.CENSORED_ENV:
        return None, None
    detail = interruption.active_env_blocker_detail(
        ws, claim=str(session.get("claim") or ""))
    return ({"session_bound": True, "corroborated": True},
            _rel(ws, str((detail or {}).get("path") or "")))


def _evidence_refs(ws: Path, ledger_ref: str | None,
                   oracle_ref: str | None) -> list[str]:
    """The evidence pointers the disposition row cites: the RESOLVED
    verification record (whichever of the four canonical surfaces
    passed — the resolver picked it; the trust mirror is never resolved
    as a pass) and the route ledger. Only paths that exist are cited: a
    SOLVED row must name the artifact that proved it."""
    refs: list[str] = []
    for ref in (oracle_ref, ledger_ref):
        if ref and (ws / ref).is_file():
            refs.append(ref)
    return refs


#: the mission-terminal trust mirror's own marker (episode_settle writes
#: it from the register stamp when no real record exists — projecting the
#: stamp is not a pass)
_TRUST_MIRROR_MARKER = "mission-terminal trust mirror"


def _oracle_evidence(ws: Path, claim: str,
                     status: str) -> tuple[bool, bool, str | None]:
    """(oracle_pass, completion_claimed, resolved_ref) from the claim's
    terminal status PLUS the canonical verification surfaces.

    A PROVEN status is a completion CLAIM, not a pass: SOLVED requires
    ``verifier_integrity.resolve_verification`` to resolve a PASS verdict
    on one of the claim's four canonical surfaces (the same resolver the
    settlement, reward and pool faces read — a ``verdict: refuted``
    record never passes). The mission-terminal trust mirror is excluded
    by its own marker: it projects the register's stamp onto the surface,
    and a projection is not evidence. The resolver's own resolved record
    is returned so the row can cite EXACTLY the surface that passed.
    Without a real pass the claim classifies FAILED /
    unverified_completion."""
    claimed = status in ("proven", "verified")
    if not claimed:
        return False, False, None
    try:
        import verifier_integrity  # noqa: PLC0415 — scripts face, lazy
        passed, _word, detail = verifier_integrity.resolve_verification(
            ws, claim, "")
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        warn("rlvr.disposition_producer",
             f"{claim}: verification resolve failed: {exc}")
        passed, detail = False, ""
    if passed and detail:
        try:
            text = (ws / detail).read_text(encoding="utf-8",
                                           errors="replace")
        except OSError:
            passed = False
        else:
            if _TRUST_MIRROR_MARKER in text:
                passed = False
    ref = detail if passed else None
    return passed, not passed, ref


def _episode_target(block) -> tuple[str | None, str | None]:
    """(target, ambiguity-reason). ONE declared target is the episode
    target; several declared targets leave the episode target ambiguous —
    a scope verdict minted from ``targets[0]`` would be evidence-free
    (an exclusion of the first target would flip EVERY claim), so the
    honest gap is no row. An empty scope is legitimate (OUT_OF_SCOPE)."""
    targets = [str(t).strip() for t in ((block or {}).get("targets") or [])
               if str(t).strip()]
    if len(targets) == 1:
        return targets[0], None
    if not targets:
        return None, None
    return None, ("multiple declared targets — the episode target is "
                  "ambiguous")


def _strategic_rows(ws: Path) -> list[dict]:
    """The strategic-action rows, read ONCE per mission."""
    try:
        return strategic_action.read(ws)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the verdict
        warn("rlvr.disposition_producer", f"strategic read failed: {exc}")
        return []


def _strategic(rows: list[dict], claim: str) -> dict:
    """The claim's strategic-action fields (action + propensity); absent
    -> {} so the classifier's SURRENDER residual applies."""
    for row in reversed(rows):
        if str(row.get("claim") or "") == claim:
            try:
                return strategic_action.disposition_fields(row)
            except Exception as exc:  # noqa: BLE001 — malformed row
                warn("rlvr.disposition_producer",
                     f"{claim}: strategic row unusable: {exc}")
                return {}
    return {}


def _record(ws: Path, claim_row: dict, block: dict | None,
            target: str | None, *, transitions: list[dict], session: dict,
            ledger: dict, strategic: dict) -> dict:
    claim = str(claim_row.get("id") or "")
    authorized = bool(block is not None and target
                      and authorization.authorized_target(block, target))
    oracle_pass, completion_claimed, oracle_ref = _oracle_evidence(
        ws, claim, str(claim_row.get("status") or "").strip().casefold())
    ledger_ref = _rel(ws, str(ledger.get("path") or ""))
    wall, wall_ref = _wall(ws, session)
    record = {
        "claim": claim,
        "authorized": authorized,
        "authorization": block,
        "target": target,
        "oracle_pass": oracle_pass,
        "wall": wall,
        "wall_ref": wall_ref,
        "evidence_refs": _evidence_refs(ws, ledger_ref, oracle_ref),
        "ledger": {k: ledger.get(k) for k in
                   ("routes", "attempted", "budget", "budget_exhausted")},
        "route_ledger_ref": ledger_ref,
        "act_outcomes": [str((r.get("o") or {}).get("status") or "").strip()
                         for r in transitions
                         if isinstance(r.get("o"), dict)
                         and str(r["o"].get("status") or "").strip()],
        "session": session,
        "completion_claimed": completion_claimed,
    }
    record.update(strategic)
    return record


def produce(ws) -> dict:
    """Write one disposition row per terminal claim (idempotent).

    Per-claim cage: one unusable claim is ONE warn and is skipped; the
    rest still produce. Returns ``{"written", "skipped", "failed"}``.
    """
    ws = Path(ws)
    spec = _load_spec(ws)
    claims = _load_claims(ws)
    summary = {"written": 0, "skipped": [], "failed": []}
    block = authorization.authorization_from_task_spec(spec)
    if block is None:
        # the classifier requires an explicit bool; a missing context
        # must never read as authorized (the honest gap)
        summary["skipped"] = [str(c.get("id") or "") for c in claims]
        if claims:
            warn("rlvr.disposition_producer",
                 "no task_spec.authorization block — no disposition rows "
                 "(a missing context must never read as authorized)")
        return summary
    target, ambiguous = _episode_target(block)
    if ambiguous:
        summary["skipped"] = [str(c.get("id") or "") for c in claims]
        warn("rlvr.disposition_producer",
             f"{ambiguous} — no disposition rows")
        return summary
    transition_rows = _all_transitions(ws)
    settled_rows = _settled_rows(ws)
    strategic_rows = _strategic_rows(ws)
    for row in claims:
        claim = str(row.get("id") or "").strip()
        if not claim:
            continue
        status = str(row.get("status") or "").strip().casefold()
        if status not in _TERMINAL_STATUSES:
            summary["skipped"].append(claim)
            continue
        try:
            transitions = _transitions(transition_rows, claim)
            session = {"returncode": None, "timed_out": False,
                       "liveness": None, "claim": claim}
            ledger = route_ledger.classify(ws, claim)
            record = _record(ws, row, block, target,
                             transitions=transitions, session=session,
                             ledger=ledger,
                             strategic=_strategic(strategic_rows, claim))
            disposition.write_row(ws, record, episode_id=claim,
                                  ts=_claim_ts(claim, transitions,
                                               settled_rows))
            summary["written"] += 1
        except Exception as exc:  # noqa: BLE001 — one claim's cage
            summary["failed"].append(
                f"{claim}: {type(exc).__name__}: {exc}")
            warn("rlvr.disposition_producer", f"{claim}: {exc}")
    return summary
