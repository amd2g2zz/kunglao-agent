# -*- coding: utf-8 -*-
"""rlvr/pricing.py — the information-gathering price (issue-760, the pricing
face).

The loop's belief (rlvr.belief) records what a claim SAW and what the
worker DECLARED unknown; this face makes "what we do NOT know" computable
and prices information-gathering against it. Two computations, both pure
deterministic projections over EXISTING keys — no new ledger, no new
state owner (the issue-806 discipline: read the issue-800/issue-721 key surfaces, never
clone them):

  - ``unknown_set`` — the workspace-level unknown/pending view: which
    primary_questions are UNDECIDED (no terminal claim answers them),
    with each one's open-candidate count (the rival explanations still
    live in the register), and which obstacles are OPEN (the obstacle
    registry's active rows; retraction is the registry's only
    resolution transition, so a retracted obstacle is decided
    knowledge). A pure VIEW — never persisted by this module.
  - ``price_action`` — an information-gathering action's price:
    expected information gain (bits) x the undecided value weight,
    decayed by the target's repeat count joined from the issue-800 dispatch
    ledger (committed dispatches on the target's claims). A probe of a
    DECIDED target gains exactly 0 bits and prices 0 — the production
    pathology (a dead path re-probed 9 times) becomes 9 zero-value
    billings instead of 9 fresh bets; an undecided target's gain is
    log2 of its live rival count (floored at one bit — a cold question
    still resolves something on first probe), so a high-info probe
    structurally outprices a low-info one without any rule table.

Persistence rides the issue-721 consolidation core: emitted price rows land
in the TELEMETRY family under the ``probe-price/1`` stamp (identity ts
stamped at emit, never inside the pure computation). Consumers: the
issue-801 cockpit consumption face (``probe_consumption`` — probes are no
longer free; they are visible in the account the ratio reads) and the
dispatch supply-admission face (``price_for_claim`` — advisory
telemetry at the approval point, never a gate decision).

Scope fence (issue-760, the pricing slice ONLY): this module never
ingests observations (the b face), never extends the action vocabulary
(the A face), never composes a policy (the π face), and never gates —
pricing is computable, replayable, deterministic.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import warn  # canonical warn: ONE implementation

#: the emitted row's stamp in the issue-721 telemetry family.
PRICING_SCHEMA = "probe-price/1"
#: the projection view's self-naming shape (a VIEW, never persisted here).
UNKNOWN_SET_SCHEMA = "unknown-set/1"

#: documented policy constants (NOT fitted): every undecided PQ carries
#: the same value weight (the task's questions are equally the task's
#: goal — a per-question weighting would be a rule table); a cold
#: undecided target still resolves one bit on its first probe; each
#: committed prior dispatch on the target halves the marginal gain
#: (float-safety clamps the exponent); a price at/below the epsilon is
#: the ≈0 band the repeat-probe pin asserts against.
BIT_VALUE = 1.0
GAIN_FLOOR_BITS = 1.0
REPEAT_DECAY = 0.5
MAX_REPEAT_SHIFT = 62
GAIN_EPSILON = 1e-9

#: the priced target kinds (the closed v1 vocabulary: PQ probes and
#: obstacle probes; anything else is a caller bug — fail fast).
TARGET_KINDS = ("pq", "obstacle")


# ------------------------------------------------------------ the reads

def _pq_ids(ws: Path) -> list[str]:
    """The workspace's primary-question ids via THE canonical parse
    (issue-77 — the same parser the dispatch gate and the seeder consume; a
    local twin would re-create the two-parsers drift). Fail-open: an
    absent/unreadable spec or a parser outage reads [] — no PQs, no
    fabrication."""
    try:
        import yaml  # noqa: PLC0415 — lazy (house style)
        spec = yaml.safe_load(
            (ws / "task_spec.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — fail-open, loud
        return []
    try:
        from convergence_check import _parse_primary_questions  # noqa: PLC0415
        pqs, _err = _parse_primary_questions(
            spec if isinstance(spec, dict) else {})
        return [str(qid) for qid, _need in (pqs or [])]
    except Exception as exc:  # noqa: BLE001 — parser outage is not fatal
        warn("rlvr.pricing.pq_ids",
             f"{type(exc).__name__}: {exc}")
        return []


def _register_claims(ws: Path) -> list[dict]:
    """The register's claim rows (tolerant read: absent/unreadable
    register -> [] — nothing is then decided, honestly)."""
    try:
        import yaml  # noqa: PLC0415 — lazy
        doc = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — fail-open, loud
        return []
    return [c for c in (doc.get("claims") or []) if isinstance(c, dict)]


def _terminal_statuses() -> set[str]:
    """The terminal set from the ONE source of truth (status_defs); an
    unreadable import degrades to the certified pair (the
    l1_planner precedent — never a fabricated vocabulary)."""
    try:
        from status_defs import TERMINAL  # noqa: PLC0415
        return set(TERMINAL)
    except Exception:  # noqa: BLE001 — fail-open, the wall is data
        return {"PROVEN", "VERIFIED"}


def _committed_dispatch_claims(ws: Path) -> dict[str, int]:
    """claim -> committed-dispatch count, read from the issue-800 dispatch
    ledger (the path's single source is claims_store's constant — this
    module only READS the ledger, never writes or re-keys it). Absent
    or dirty rows read as no history (fail-open)."""
    try:
        import claims_store  # noqa: PLC0415 — lazy (path constant only)
        p = ws / claims_store.DISPATCH_LEDGER_REL
    except Exception:  # noqa: BLE001 — no claims_store, no history
        return {}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, int] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if (isinstance(row, dict) and row.get("state") == "committed"):
            claim = str(row.get("claim") or "")
            if claim:
                out[claim] = out.get(claim, 0) + 1
    return out


def _open_obstacles(ws: Path) -> list[dict]:
    """The obstacle registry's ACTIVE rows (retraction is the
    registry's only resolution transition — the obstacles module owns
    the read's tolerance; this module never re-validates rows)."""
    try:
        from rlvr import obstacles as _obstacles  # noqa: PLC0415 — lazy
        rows = _obstacles.read(Path(ws))
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("rlvr.pricing.obstacles",
             f"{type(exc).__name__}: {exc}")
        return []
    return [{"id": str(r.get("id") or ""),
             "kind": str(r.get("kind") or ""),
             "claim": str(r.get("claim") or "")}
            for r in rows if r.get("id")]


# -------------------------------------------------- 1. the unknown set

def unknown_set(ws) -> dict:
    """The workspace's unknown/pending VIEW: undecided PQs (with open
    rival counts), decided PQs, open obstacles. Pure projection over
    existing keys — deterministic, no ts, never persisted here."""
    ws = Path(ws)
    pq_list = _pq_ids(ws)
    terminal = _terminal_statuses()
    claims = _register_claims(ws)
    decided: set[str] = set()
    open_by_pq: dict[str, int] = {}
    for c in claims:
        qid = str(c.get("answers_question") or "").strip()
        if not qid:
            continue
        if str(c.get("status") or "") in terminal:
            decided.add(qid)
        else:
            open_by_pq[qid] = open_by_pq.get(qid, 0) + 1
    undecided = [{"qid": q, "candidates": open_by_pq.get(q, 0)}
                 for q in pq_list if q not in decided]
    obstacles_open = _open_obstacles(ws)
    return {
        "schema": UNKNOWN_SET_SCHEMA,
        "undecided": undecided,
        "decided": sorted(q for q in pq_list if q in decided),
        "open_obstacles": sorted(obstacles_open, key=lambda o: o["id"]),
        "counts": {"pqs": len(pq_list),
                   "undecided": len(undecided),
                   "decided": len(pq_list) - len(undecided) if pq_list
                   else 0,
                   "open_obstacles": len(obstacles_open)},
    }


# ---------------------------------------------------------- 2. the price

def _pq_price_parts(ws: Path, qid: str, dispatch_claims: dict[str, int],
                    claims: list[dict]) -> tuple[str, float, int, int]:
    """(status, gain_bits, candidates, repeat) for a PQ target."""
    pq_list = set(_pq_ids(ws))
    if qid not in pq_list:
        return "absent", 0.0, 0, 0
    terminal = _terminal_statuses()
    candidates = 0
    decided = False
    for c in claims:
        if str(c.get("answers_question") or "").strip() != qid:
            continue
        if str(c.get("status") or "") in terminal:
            decided = True
        else:
            candidates += 1
    if decided:
        return "decided", 0.0, candidates, 0
    repeat = sum(n for claim, n in dispatch_claims.items()
                 if claim in {str(c.get("id") or "") for c in claims
                              if str(c.get("answers_question") or "")
                              .strip() == qid
                              and str(c.get("status") or "")
                              not in terminal})
    gain = max(math.log2(max(candidates, 2)), GAIN_FLOOR_BITS)
    return "undecided", gain, candidates, repeat


def _obstacle_price_parts(ws: Path, obs_id: str,
                          dispatch_claims: dict[str, int],
                          ) -> tuple[str, float, int, int]:
    """(status, gain_bits, candidates, repeat) for an obstacle target:
    an ACTIVE row is one unexplored blocker dimension (floor gain); a
    retracted/absent row is decided knowledge (retraction is the
    registry's only resolution transition). The repeat joins the row's
    optional `claim` — a claim-less obstacle has no dispatch key and
    reads repeat 0 (the honest gap, recorded)."""
    for row in _open_obstacles(ws):
        if row["id"] != obs_id:
            continue
        claim = row["claim"]
        repeat = dispatch_claims.get(claim, 0) if claim else 0
        return "undecided", GAIN_FLOOR_BITS, 0, repeat
    # not active: a retracted row STAYS on disk (retraction writes INTO
    # the row file) -> decided knowledge; a missing file was never
    # recorded -> absent (never fabricated).
    if _obstacle_row_exists(ws, obs_id):
        return "decided", 0.0, 0, 0
    return "absent", 0.0, 0, 0


def _obstacle_row_exists(ws: Path, obs_id: str) -> bool:
    """(tolerant) does the registry still hold this row's file?"""
    from rlvr import obstacles as _obstacles  # noqa: PLC0415 — lazy
    p = ws / _obstacles.OBSTACLES_REL / f"{obs_id}.json"
    try:
        row = json.loads(p.read_text(encoding="utf-8",
                                     errors="replace"))
    except (OSError, ValueError):
        return False
    return isinstance(row, dict) and row.get("id") == obs_id


def price_action(ws, kind, target_id, *, dispatch_id: str | None = None,
                 ) -> dict:
    """One information-gathering action's price: expected gain (bits)
    x the undecided value weight, decayed by the target's committed
    repeat count. PURE — no ts, no RNG, no writes; two calls over the
    same workspace reads return identical rows. A bad kind is a caller
    bug (fail fast, the candidate-boundary precedent)."""
    kind = str(kind or "")
    if kind not in TARGET_KINDS:
        raise ValueError(
            f"kind must be one of {TARGET_KINDS}: {kind!r}")
    ws = Path(ws)
    tid = str(target_id or "").strip()
    dispatch_claims = _committed_dispatch_claims(ws)
    if kind == "pq":
        status, gain, candidates, repeat = _pq_price_parts(
            ws, tid, dispatch_claims, _register_claims(ws))
    else:
        status, gain, candidates, repeat = _obstacle_price_parts(
            ws, tid, dispatch_claims)
    shift = min(repeat, MAX_REPEAT_SHIFT)
    price = gain * BIT_VALUE * (REPEAT_DECAY ** shift)
    row = {
        "schema": PRICING_SCHEMA,
        "kind": kind,
        "target": tid,
        "status": status,
        "gain_bits": float(gain),
        "value": float(BIT_VALUE),
        "candidates": int(candidates),
        "repeat": int(repeat),
        "price": float(price),
    }
    if dispatch_id:
        row["dispatch_id"] = str(dispatch_id)
    return row


def price_for_claim(ws, claim, *, dispatch_id: str | None = None,
                    ) -> dict | None:
    """The claim-shaped face the dispatch read consumes: the claim's
    PQ probe price. A claim without ``answers_question`` prices None —
    sub-task claims are outside the v1 PQ scope, honestly (never a
    fabricated target)."""
    ws = Path(ws)
    cid = str(claim or "").strip()
    if not cid:
        return None
    for c in _register_claims(ws):
        if str(c.get("id") or "") != cid:
            continue
        qid = str(c.get("answers_question") or "").strip()
        if not qid:
            return None
        return price_action(ws, "pq", qid, dispatch_id=dispatch_id)
    return None


# ------------------------------------------------ 3. the joins (emit)

def emit_price(ws, priced: dict) -> bool:
    """Append one priced row to the issue-721 TELEMETRY family (identity ts
    stamped HERE — the pure computation above never carries wall-clock).
    The row must carry the pricing shape (gain_bits/price keys — a row
    that never went through price_action is refused at this boundary).
    Loud-result fail-open."""
    if not isinstance(priced, dict) \
            or "gain_bits" not in priced or "price" not in priced:
        warn("rlvr.pricing.emit",
             f"refused a non-priced row: {priced!r}")
        return False
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        from rlvr import consolidated_ledger as _cl  # noqa: PLC0415
        row = {**priced, "ts": utc_now_z()}
        return _cl.append(Path(ws), "telemetry", row)
    except Exception as exc:  # noqa: BLE001 — never raise into a producer
        warn("rlvr.pricing.emit", f"{type(exc).__name__}: {exc}")
        return False


def probe_consumption(ws) -> dict:
    """The issue-801-shaped consumption account over the emitted price rows:
    total probes, zero-info probes (decided-target re-probes — the
    dead-path pathology made countable), repeat probes (repeat >= 1),
    and the billed price sum. Fail-open: an unreadable family reads
    zeros."""
    try:
        from rlvr import consolidated_ledger as _cl  # noqa: PLC0415
        rows = _cl.read(Path(ws), "telemetry",
                        schema_prefix="probe-price")
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("rlvr.pricing.consumption",
             f"{type(exc).__name__}: {exc}")
        rows = []
    billed = 0.0
    for r in rows:
        v = r.get("price")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            billed += float(v)
    return {
        "schema": PRICING_SCHEMA,
        "probes": len(rows),
        "zero_info_probes": sum(
            1 for r in rows
            if isinstance(r.get("gain_bits"), (int, float))
            and not isinstance(r.get("gain_bits"), bool)
            and float(r["gain_bits"]) == 0.0),
        "repeat_probes": sum(
            1 for r in rows
            if isinstance(r.get("repeat"), int)
            and not isinstance(r.get("repeat"), bool)
            and r["repeat"] >= 1),
        "billed_price": billed,
    }
