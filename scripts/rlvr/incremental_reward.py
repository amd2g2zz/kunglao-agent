#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/incremental_reward.py — potential-based per-act reward + the
transition ledger (issue #539 Phase B, PR-1).

The 2026-10-06 owner ruling reframes kunglao as an external SMDP over a
frozen model: every dispatch→outcome pair must produce a TRANSITION
(s, a, o, s', r) and a per-act INCREMENTAL reward, because the one-shot
settlement credit gives ordinary tool success zero signal (the owner's
attribution gap). This module is pure instrumentation — no behavior
change, no sampling change, no critic.

Reward form (design doc docs/design/external-smdp-phase-b.md §2):

    r_t = ALPHA * [Φ(s') - Φ(s)] - LAMBDA * cost_t
    Φ(s) = W_FACTS * graded_fact_fraction + W_ORACLE * oracle_green_rate

(the facts term is fact_face's graded ``weighted_fraction`` since
issue-678 D-678.5 — certified 1.0 / present 0.5 / draft 0.25; the
binary verified-count it replaced made Φ degenerate in live
workspaces)

Φ is a potential function — potential-based shaping (Ng, Harada & Russell
1999) preserves the optimal-policy order, so layering it over the
terminal settlement credit cannot corrupt the task objective. All four
coefficients are DOCUMENTED POLICY CONSTANTS (the state.py precedent:
"policy constants, not fitted parameters") — the whole phase adds at
most three; ALPHA/LAMBDA ride at 1.0 until the offline comparison says
otherwise.

The transition ledger is append-only runs/transitions.jsonl — the s'
face the 2026-09-27 quadruple-rejection pin denied; the 2026-10-06
ruling (external SMDP, transition recording authorized) overturns that
pin (see scripts/rlvr/triples.py's docstring pin block for the citation).
"""
from __future__ import annotations

import json
import re
import uuid

from _common import utc_now_z
from pathlib import Path

from rlvr.state import fact_face, _oracle_status_progress

TRANSITIONS_REL = "runs/transitions.jsonl"
LAUNCH_REL = "runs/dispatch-launch-{claim}.json"
# #550: action-type-scoped stashes — a verify/red-team act keeps its own
# stash so it never clobbers a pending dispatch stash for the same claim
# (the untyped path stays byte-identical for in-flight workspaces).
LAUNCH_REL_TYPED = "runs/dispatch-launch-{claim}--{action_type}.json"
# 1-F3: the stash namespace is owned by record_launch's shape — the
# schema stamp is what append_transition's wall checks the doc against
# (a foreign schema or a status-bearing envelope is never launch state).
LAUNCH_SCHEMA = "dispatch-launch/1"
# #690 review CRITICAL: claim/action_type are formatted into the stash
# FILENAME, so both must be single path tokens — starts alnum, then
# alnum / '.' / '_' / '-', bounded length. Traversal payloads
# (``/``, ``..``, absolute paths) never match.
_STASH_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# ---- policy constants (design doc §2; NOT fitted) ------------------------
ALPHA = 1.0          # potential-difference weight
LAMBDA_COST = 1.0    # cost weight
W_FACTS = 0.3        # Φ: verified-facts fraction weight
W_ORACLE = 0.5       # Φ: oracle green-rate weight
COST_TOKENS_DIV = 10_000.0   # normalize: 10k tokens = 1 cost unit
COST_SECONDS_DIV = 3_600.0   # normalize: 1 wall hour = 1 cost unit


def potential(ws) -> float:
    """Φ(s) ∈ [0, 1]: verified-facts fraction + oracle green rate,
    renormalized over PRESENT dims (a missing organ drops its dim —
    the honest-absence doctrine, state.py precedent). The facts term
    reads fact_face's GRADED ``weighted_fraction`` (issue-678 D-678.5:
    certified terminal 1.0 / present non-terminal 0.5 / draft 0.25), so
    partially-verified workspaces produce INTERMEDIATE potentials — the
    binary verified-count made Φ degenerate ({0.0, 1.0} in live
    workspaces) and the transition ledger recorded no partial progress."""
    ws = Path(ws)
    parts: list[tuple[float, float]] = []  # (weight, value)
    ff = fact_face(ws)
    if ff["count"] > 0:
        parts.append((W_FACTS, float(ff.get("weighted_fraction", 0.0))))
    oracle = _oracle_status_progress(ws)
    if oracle is not None:
        passed, total = oracle
        parts.append((W_ORACLE, passed / total if total else 0.0))
    if not parts:
        return 0.0
    wsum = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / wsum


def incremental_reward(phi_before: float, phi_after: float, *,
                       tokens: float = 0.0, seconds: float = 0.0) -> float:
    """r_t = ALPHA·ΔΦ − LAMBDA·cost. Both terms are bounded: ΔΦ ∈ [−1,1],
    cost normalized to hours-equivalent scale."""
    cost = tokens / COST_TOKENS_DIV + seconds / COST_SECONDS_DIV
    return round(ALPHA * (phi_after - phi_before) - LAMBDA_COST * cost, 6)


def _launch_path(ws: Path, claim: str, action_type: str) -> Path:
    """The stash path for one action type: ""/"dispatch" keeps the
    legacy untyped filename (in-flight workspaces keep working); any
    other type lands the scoped sibling (#550).

    #690 review CRITICAL wall: the claim and action_type are formatted
    into the FILENAME, so a worker-writable stash doc (or a malformed
    envelope) carrying ``/`` / ``..`` would resolve outside runs/ and
    the settle's unlink would delete an arbitrary workspace file
    (reproduced: claim ``x/../../victim-important`` + a planted
    intermediate dir deleted ws/victim-important.json). Both components
    must be single safe path tokens or the path is refused (ValueError
    -> the callers' fail-open warn + None)."""
    for name, value in (("claim", claim), ("action_type", action_type)):
        if value in ("", None):
            continue
        if not _STASH_TOKEN_RE.match(str(value)):
            raise ValueError(
                f"unsafe launch-stash {name} {value!r}: not a single "
                f"path token (#690 — stash paths never leave runs/)")
    if action_type in ("", "dispatch"):
        return ws / LAUNCH_REL.format(claim=claim)
    return ws / LAUNCH_REL_TYPED.format(claim=claim, action_type=action_type)


def _safe_stash_token(value) -> bool:
    """One launch-stash path component is safe iff it is a single token:
    starts alnum, then alnum / ``.`` / ``_`` / ``-`` only (no separators,
    no dot-dot, no leading dot), bounded length. Claims (C-NN) and
    action types (dispatch / verify / redteam / prediction-settle) all
    pass; traversal payloads never do."""
    return bool(_STASH_TOKEN_RE.match(str(value or "")))


def verify_credit(verdict: str) -> float:
    """#550: the verifier verdict -> settle credit. verified / CONFIRMED
    bank 1.0 (an adversarial pass that failed to refute IS success);
    refuted, unverified-with-gap, timeout, and everything else bank 0.0
    — an unverifiable verification decided nothing."""
    return 1.0 if str(verdict).strip().lower() == "verified" \
        or str(verdict).strip().upper() == "CONFIRMED" else 0.0


def record_launch(ws, claim: str, action_key: str, phi: float | None = None,
                  s_hash: str = "", propensity: float | None = None,
                  action_type: str = "dispatch",
                  variant: str = "",
                  branch_budget: dict | None = None) -> dict | None:
    """Stash the launch-side state at dispatch time — the settle face
    reads it to close the transition. Fail-open telemetry: never raises
    into the dispatch path. #550: action_type scopes the stash (a verify
    act cannot clobber a pending dispatch stash); the variant marker
    (verify | redteam) rides the doc for the row's provenance. 1-F2:
    every launch stamps a fresh ``attempt_id`` (returned with the
    doc) so a settle that outlived a re-dispatch is refused instead of
    banking the newer launch's state (append_transition's guard).
    #690: the dispatch envelope's branch_budget ({wall_s, retries} — the
    act budget, parsed since #539 with zero consumers) rides the stash so
    the settle face can price a wall_s overrun into attributed-waste and
    the barrier can name the budget it is enforcing. Absent/empty keeps
    the doc shape byte-identical."""
    try:
        ws = Path(ws)
        p = _launch_path(ws, claim, action_type)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": LAUNCH_SCHEMA,
            "ts": utc_now_z(),
            "claim": str(claim),
            "a": str(action_key),
            "s": str(s_hash),
            "phi": potential(ws) if phi is None else float(phi),
            "action_type": str(action_type or "dispatch"),
            "attempt_id": uuid.uuid4().hex[:12],
            **({"variant": str(variant)} if variant else {}),
            **({"propensity": float(propensity)}
               if propensity is not None else {}),
            **({"branch_budget": {str(k): v for k, v in
                                  dict(branch_budget).items()}}
               if branch_budget else {}),
        }
        p.write_text(json.dumps(doc), encoding="utf-8")
        return doc
    except (OSError, ValueError) as exc:  # telemetry, never the producer
        from kunglao_log import warn  # noqa: PLC0415
        warn("incremental_reward.record_launch",
             f"{type(exc).__name__}: {exc}")
        return None


def append_transition(ws, claim: str, outcome: str, *,
                      status: str = "", facts: int = 0,
                      tokens: float = 0.0, seconds: float = 0.0,
                      r_settle: float | None = None,
                      done: bool = False,
                      action_type: str = "dispatch",
                      variant: str = "",
                      lift: float | None = None,
                      absorbed_from_disk: bool = False,
                      attempt_id: str = "") -> dict | None:
    """Close one transition: read the launch stash, compute Φ(s′) and
    r_t, append the row. Returns the row (None when no launch stash —
    a settle without a recorded launch banks nothing rather than
    inventing a before-state; ONE warn trace names the miss, 1-F1).
    Fail-open telemetry. #550: the stash is action-type-scoped (verify
    acts close against their own stash) and the row carries the additive
    action_type column plus the o.variant provenance marker when set.
    The optional lift argument rides the row as an additive weight column
    (absent when not supplied). absorbed_from_disk rides the o face as an
    additive audit marker (the settle was read from the act's own on-disk
    verdict face after a hard kill — the outcome status still shows the
    kill; absent when False, keeping every legacy row byte-identical).
    1-F2: when the caller passes the ``attempt_id`` it observed at
    launch and the stash carries a DIFFERENT one (a re-dispatch
    overwrote it), the settle is refused — the newer launch keeps
    ownership of its stash, and no row banks the newer launch's
    phi_before/a. An empty attempt_id keeps the exact legacy behavior.
    1-F3: the schema wall — a stash doc bearing a foreign ``schema`` or
    any ``status`` field is NOT launch state (the live shape: an
    orchestrator PARKED envelope with a wake plan parked in this
    namespace); the settle is refused with ONE warn and the file is
    LEFT INTACT (consuming it would delete the wake plan). Legacy
    schema-less stashes carry neither field and settle unchanged.
    Issue-678 T4: every row carries the explicit ``phi_delta``
    (= s_prime_phi − phi_before) plus ``claim_ref``/``action_key``
    copied from the launch stash — additive columns, self-attributing
    provenance for the tiebreaker feed."""
    try:
        ws = Path(ws)
        launch_p = _launch_path(ws, claim, action_type)
        if not launch_p.is_file():
            from kunglao_log import warn  # noqa: PLC0415
            warn("incremental_reward.append_transition",
                 f"settle without launch stash for {claim!r} "
                 f"(action_type={action_type or 'dispatch'!r}) — no "
                 f"transition row banked (1-F1)")
            return None
        launch = json.loads(launch_p.read_text(encoding="utf-8"))
        if "status" in launch or ("schema" in launch
                                  and launch.get("schema")
                                  != LAUNCH_SCHEMA):
            from kunglao_log import warn  # noqa: PLC0415
            warn("incremental_reward.append_transition",
                 f"refused settle for {claim!r} "
                 f"(action_type={action_type or 'dispatch'!r}): the "
                 f"stash doc is not launch state (schema="
                 f"{launch.get('schema')!r}, status="
                 f"{launch.get('status')!r}) — foreign envelopes are "
                 f"never consumed and never deleted (1-F3)")
            return None
        if str(attempt_id) and str(launch.get("attempt_id") or "") \
                != str(attempt_id):
            from kunglao_log import warn  # noqa: PLC0415
            warn("incremental_reward.append_transition",
                 f"refused stale settle for {claim!r}: expected attempt "
                 f"{attempt_id!r}, stash carries "
                 f"{launch.get('attempt_id')!r} (a re-dispatch owns this "
                 f"stash — 1-F2)")
            return None
        phi_after = potential(ws)
        r_incr = incremental_reward(
            float(launch.get("phi", 0.0)), phi_after,
            tokens=tokens, seconds=seconds)
        row = {
            "ts": utc_now_z(),
            "dispatch_id": str(claim),
            "action_type": str(launch.get("action_type")
                               or action_type or "dispatch"),
            "s": str(launch.get("s") or ""),
            "a": str(launch.get("a") or ""),
            "o": {"status": str(outcome), "class": str(status),
                  "facts": int(facts),
                  **({"variant": str(variant
                                     or launch.get("variant") or "")}
                     if variant or launch.get("variant") else {}),
                  **({"absorbed_from_disk": True}
                     if absorbed_from_disk else {})},
            "s_prime_phi": round(phi_after, 6),
            "phi_before": round(float(launch.get("phi", 0.0)), 6),
            # issue-678 T4: the EXPLICIT Φ movement (the #548 tiebreaker
            # raw material was previously only derivable by subtraction)
            # plus the launch stash's claim/action provenance — the row
            # is self-attributing without re-reading the (consumed) stash
            "phi_delta": round(phi_after
                               - float(launch.get("phi", 0.0)), 6),
            "claim_ref": str(launch.get("claim") or claim),
            "action_key": str(launch.get("a") or ""),
            "r_incr": r_incr,
            "r_settle": (round(float(r_settle), 6)
                         if r_settle is not None else None),
            "done": bool(done),
            **({"lift": round(float(lift), 6)}
               if lift is not None else {}),
            **({"propensity": launch["propensity"]}
               if launch.get("propensity") is not None else {}),
        }
        out = ws / TRANSITIONS_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        launch_p.unlink(missing_ok=True)  # stash consumed
        return row
    except (OSError, ValueError, TypeError) as exc:  # loud telemetry (#275)
        from kunglao_log import warn  # noqa: PLC0415
        warn("incremental_reward.append_transition",
             f"{type(exc).__name__}: {exc}")
        return None  # telemetry, never the producer


def _stash_identity(path: Path) -> tuple[str, str] | None:
    """(claim, action_type) for one launch-stash file. The stash doc wins
    when it carries the fields; otherwise the filename is decoded
    (``dispatch-launch-<claim>[--<action_type>].json`` — the untyped name
    means action_type ``dispatch``). A foreign doc parked in the
    namespace (the 1-F3 envelope) still resolves by filename. None when
    neither source yields a claim (not a stash shape — skipped, never
    guessed)."""
    claim = action_type = ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None  # unreadable/broken doc: the filename identity carries
    if isinstance(doc, dict):
        claim = str(doc.get("claim") or "").strip()
        action_type = str(doc.get("action_type") or "").strip()
    if not claim:
        rest = path.stem
        prefix = "dispatch-launch-"
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
        if "--" in rest:
            rest, action_type = rest.rsplit("--", 1)
        claim = rest.strip()
    if not claim:
        return None
    return claim, (action_type or "dispatch")


def sweep_orphan_launches(ws) -> list[dict]:
    """1-F1 — the end-of-run orphan sweep over the launch-stash
    namespace: every runs/dispatch-launch-*.json with NO transitions row
    for its (claim, action_type) is an orphan (the discarded transition
    the live audit caught: a writer/consumer action_type drift landed a
    stash whose settle never fired, silently). Emits exactly ONE warn
    trace when orphans exist; returns the orphan list (each {claim,
    action_type, path, ts}) for the caller. Fail-open: a broken
    workspace yields [] and never raises into the closure path."""
    orphans: list[dict] = []
    try:
        ws = Path(ws)
        runs = ws / "runs"
        if not runs.is_dir():
            return orphans
        settled = {(str(r.get("dispatch_id") or ""),
                    str(r.get("action_type") or "dispatch"))
                   for r in read_transitions(ws)}
        for path in sorted(runs.glob("dispatch-launch-*.json")):
            ident = _stash_identity(path)
            if ident is None or ident in settled:
                continue
            ts = ""
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(doc, dict):
                    ts = str(doc.get("ts") or "")
            except (OSError, ValueError):
                ts = ""
            orphans.append({"claim": ident[0], "action_type": ident[1],
                            "path": str(path), "ts": ts})
        if orphans:
            from kunglao_log import warn  # noqa: PLC0415
            listing = ", ".join(f"{o['claim']}/{o['action_type']}"
                                for o in orphans[:5])
            more = f" (+{len(orphans) - 5} more)" if len(orphans) > 5 else ""
            warn("incremental_reward.sweep_orphan_launches",
                 f"{len(orphans)} orphan launch stash(es) with no "
                 f"transitions row: {listing}{more} (1-F1)")
    except OSError as exc:  # telemetry, never the producer — but loud
        from kunglao_log import warn  # noqa: PLC0415
        warn("incremental_reward.sweep_orphan_launches",
             f"{type(exc).__name__}: {exc}")
        return []
    return orphans


def read_transitions(ws) -> list[dict]:
    """The ledger read face: all rows, oldest first; absent = []."""
    p = Path(ws) / TRANSITIONS_REL
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
