# -*- coding: utf-8 -*-
"""state_signature.py — canonical workspace state signature + V(s) anchor
(issue 396, v0.1.6 RECORDING face; owner pins 2026-09-27).

## State signature (the owner spec, mechanized)

``s_t`` = the pre-dispatch workspace state. The workspace already records
every face the owner lists; the only missing piece was a canonical
DISCRETIZED encoding so states are comparable, bucketable, and
table-addressable (issue 386: Q-table keys on state signatures). This module
derives that encoding from EXISTING files only:

  ================  ===================================================
  face              derivation (existing file, tolerant read)
  ================  ===================================================
  fact count        ``facts/F*.md`` frontmatter count (the
                    scalar_settlement.fact_artifacts read precedent);
                    bucketed FACT_BUCKETS: 0 | 1-4 | 5-9 | 10-19 |
                    20-49 | 50+
  verified facts    frontmatter ``status`` in TERMINAL_FACT_STATUSES
                    (the settlement currency's credit terminals:
                    PROVEN / VERIFIED)
  claim pattern     ``claim-register.yaml`` claims: canonical per-status
                    counts, sorted (``NEGATIVE=1|OPEN=2|PROVEN=1``)
  budget fraction   cost telemetry: tuition_curve.cost_state spent /
                    hard cap, clamped [0,1]; bucketed BUDGET_BUCKETS
  chain progress    k/N, first face that answers wins:
                    1. rollout-ledger probe signals (last non-null
                       dense_layers / static_probes / replay_probes,
                       the scalar_settlement._probe_progress
                       aggregation);
                    2. ``runs/oracle-status.json`` armed cases
                       (pass / total, the harvest _oracle_face shape);
                    3. ``runs/mission_ledger.yaml`` last history vector
                       with checks_impl > 0 (oracle_pass / checks_impl);
                    None when no face exists (honest absence)
  phase             ``<ws>/.hook_state.json`` "phase"
                    (DISPATCH/MONITOR/VERIFY/IDLE — the issue-461/issue-527
                    dispatch-lifecycle vocabulary)
  sides             RESERVED: always {} — the side-trajectory tree is
                    v0.2 (owner design pin 2026-09-26); the field exists
                    so signatures never re-key when sides land
  ================  ===================================================

Canonical forms (pure, order-stable):

  signature_str  ``state-sig/1|fc=<bucket>|fv=<verified>|cp=<pattern|->|
                 bg=<bucket>|ch=<k/n|->|ph=<phase|->|sd=-``
  signature_hash sha256(signature_str)[:12] — the short table key

## V(s) anchor (deterministic, lookup-only)

``V(s) = Σ(w_i · term_i) / Σ w_i`` over PRESENT dims (renormalized;
honest absence drops a dim, it never fabricates a 0):

  chain   (w=0.5)  k/N
  facts   (w=0.3)  verified / max(count, 1)
  budget  (w=0.2)  remaining fraction (1 - spent/cap); present iff the
                   cost_events face exists — a fresh workspace with no
                   cost telemetry has no budget dim
  sides   (w=0.0)  RESERVED v0.2 (side completion rate)

No learning, no critic, no data files — weights are documented policy
constants, not fitted parameters. Cold start (no faces at all) anchors
at 0.0.

**v0.2 seam (documented, not built):** per-signature EMPIRICAL
CORRECTION — banked triples grouped by signature give an empirical
pass-rate that refines the anchor (owner pin 2026-09-27). Nothing here
reads the triple bank; the correction lands as a separate v0.2 face so
this anchor stays a pure function of the workspace.

## Mainline situation snapshot stream

``runs/situation-stream.jsonl`` — append-only JSONL of
{schema, ts, trigger, tick, state, signature, signature_hash} rows: the
mainline situation snapshot sequence the owner separates from tuple
columns (feeds v0.2 ΔV attribution and stall detection; flat V
trajectory = the rigorous "no progress"). Written by the loop runner's
worker-return / terminal faces. Fail-open everywhere: recording never
breaks the producer.

ZERO DECISION POSTURE: pure reads + fail-open appends. No dispatch,
gate, or settlement face imports this module (pinned by
test_experience_freeze_396).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from kunglao_log import iter_jsonl

SCHEMA = "state-sig/1"
SITUATIONS_REL = "runs/situation-stream.jsonl"
SITUATION_SCHEMA = "situation/1"

# the settlement currency's fact credit terminals (scalar_settlement
# _CREDIT_TERMINALS semantics; redeclared to keep this module
# dependency-light and import-direction clean)
TERMINAL_FACT_STATUSES = frozenset({"PROVEN", "VERIFIED"})

# fact-count buckets (upper-inclusive edges): 0 | 1-4 | 5-9 | 10-19 |
# 20-49 | 50+. Discretization keeps signatures bucketable per the owner
# spec; the raw counts ride the snapshot document beside the bucket.
FACT_BUCKET_EDGES = (0, 4, 9, 19, 49)

# budget-fraction buckets: <0.10 | <0.25 | <0.50 | <0.75 | <1.0 | >=1.0.
# Coarse spend bands — the owner's "budget fraction" as a discretized
# signature dim.
BUDGET_BUCKET_EDGES = (0.10, 0.25, 0.50, 0.75, 1.0)

# V-anchor weights: documented policy constants (the repo's lambda
# precedent — rationale carried, never fitted). Chain progress is the
# dominant real progress measure on verifiable-RE tasks; verified-fact
# share second; budget remaining third (capacity to continue).
W_CHAIN = 0.5
W_FACTS = 0.3
W_BUDGET = 0.2
W_SIDES = 0.0  # RESERVED v0.2: side completion rate (weight 0 = absent)

COST_EVENTS_REL = "cost_events.jsonl"  # tuition_curve single source

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] state_signature WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


# ---------- face readers (tolerant, existing files only) ----------------

def fact_face(ws) -> dict:
    """{"count", "verified"} over facts/F*.md frontmatter status."""
    ws = Path(ws)
    count = verified = 0
    facts_dir = ws / "facts"
    if not facts_dir.is_dir():
        return {"count": 0, "verified": 0}
    for path in sorted(facts_dir.glob("F*.md")):
        try:
            parts = path.read_text(
                encoding="utf-8", errors="replace").split("---", 2)
            meta = None
            if len(parts) >= 3:
                import yaml
                meta = yaml.safe_load(parts[1])
        except OSError:
            continue
        except Exception:  # noqa: BLE001 — unreadable frontmatter: skip
            meta = None
        count += 1  # the file exists: it counts (lint owns loudness)
        if isinstance(meta, dict) and str(
                meta.get("status") or "").strip().upper() \
                in TERMINAL_FACT_STATUSES:
            verified += 1
    return {"count": count, "verified": verified}


def fact_bucket(count: int) -> int:
    """Bucket index for a fact count (FACT_BUCKET_EDGES)."""
    for i, edge in enumerate(FACT_BUCKET_EDGES):
        if count <= edge:
            return i
    return len(FACT_BUCKET_EDGES)


def claim_pattern(ws) -> str:
    """Canonical per-status claim counts, status-sorted
    (``NEGATIVE=1|OPEN=2|PROVEN=1``); "" when no register/claims."""
    ws = Path(ws)
    claims: list = []
    try:
        import yaml
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
        claims = reg.get("claims") or []
    except Exception:  # noqa: BLE001 — tolerant read
        claims = []
    if not isinstance(claims, list):
        return ""
    counts: dict[str, int] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "").strip().upper()
        if status:
            counts[status] = counts.get(status, 0) + 1
    return "|".join(f"{k}={counts[k]}" for k in sorted(counts))


def budget_fraction(ws, hard_cap: float | None = None) -> float:
    """Spent / hard cap from the cost telemetry (tuition_curve single
    source), clamped into [0, 1]. No cost face -> 0.0."""
    ws = Path(ws)
    try:
        from tuition_curve import cost_state, HARD_CAP_DEFAULT
        cap = float(hard_cap) if hard_cap else float(HARD_CAP_DEFAULT)
        spent = float(cost_state(ws)["spent"])
        return min(max(spent / cap, 0.0), 1.0)
    except Exception:  # noqa: BLE001 — telemetry absence is zero, not signal
        return 0.0


def budget_bucket(fraction: float) -> int:
    """Bucket index for a budget fraction (BUDGET_BUCKET_EDGES)."""
    for i, edge in enumerate(BUDGET_BUCKET_EDGES):
        if fraction < edge:
            return i
    return len(BUDGET_BUCKET_EDGES)


def _probe_signal_progress(ws) -> tuple[int, int] | None:
    """Rollout-ledger probe signals: last non-null dense_layers /
    static_probes / replay_probes value in append order, aggregated
    done/total (scalar_settlement._probe_progress semantics)."""
    try:
        import rollout_ledger as rl
        rows = rl.read(ws)
    except Exception:  # noqa: BLE001 — no ledger is no chain face
        return None
    last: dict[str, dict] = {}
    for row in rows:
        for sig in row.get("signals") or []:
            if not isinstance(sig, dict):
                continue
            type_ = str(sig.get("type") or "")
            if type_ in ("dense_layers", "static_probes", "replay_probes") \
                    and isinstance(sig.get("value"), dict):
                last[type_] = sig["value"]
    done = total = 0.0
    for v in last.values():
        d = v.get("passed", v.get("completed", 0))
        t = v.get("total", 0)
        if not isinstance(d, (int, float)) or not isinstance(
                t, (int, float)):
            continue
        done += max(float(d), 0.0)
        total += max(float(t), 0.0)
    if total <= 0:
        return None
    return int(done), int(total)


def _oracle_status_progress(ws) -> tuple[int, int] | None:
    """runs/oracle-status.json armed cases: (pass, total) — the harvest
    _oracle_face document shape ({"cases": {id: {"status": ...}}})."""
    p = Path(ws) / "runs" / "oracle-status.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        cases = doc.get("cases") or {}
    except (OSError, ValueError, AttributeError):
        return None
    total = 0
    passed = 0
    for case in cases.values():
        total += 1
        if str((case or {}).get("status") or "").lower() == "pass":
            passed += 1
    return (passed, total) if total > 0 else None


def _mission_ledger_progress(ws) -> tuple[int, int] | None:
    """runs/mission_ledger.yaml: the LAST history vector with
    checks_impl > 0 -> (oracle_pass, checks_impl)."""
    p = Path(ws) / "runs" / "mission_ledger.yaml"
    history: list = []
    try:
        import yaml
        led = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        history = led.get("mission", {}).get("history") or []
    except Exception:  # noqa: BLE001 — tolerant read
        history = []
    for vector in reversed(history):
        if not isinstance(vector, dict):
            continue
        try:
            impl = int(vector.get("checks_impl") or 0)
        except (TypeError, ValueError):
            continue
        if impl > 0:
            try:
                passed = int(vector.get("oracle_pass") or 0)
            except (TypeError, ValueError):
                passed = 0
            return (max(passed, 0), impl)
    return None


def chain_progress(ws) -> tuple[int, int] | None:
    """Chain progress k/N — first face that answers wins:
    probe signals -> oracle-status -> mission-ledger history. None when
    no face exists (honest absence never fabricates progress)."""
    return (_probe_signal_progress(ws)
            or _oracle_status_progress(ws)
            or _mission_ledger_progress(ws))


def phase(ws) -> str | None:
    """The dispatch-lifecycle phase (issue-461/issue-527 vocabulary) from .hook_state.json
    (DISPATCH / MONITOR / VERIFY / IDLE). None when absent/invalid."""
    p = Path(ws) / ".hook_state.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = doc.get("phase") if isinstance(doc, dict) else None
    return str(value) if value else None


# ---------- canonical snapshot + signature -------------------------------

def snapshot(ws) -> dict:
    """The canonical state document (discretized; sides reserved empty).
    Pure read — never raises on a bare workspace. The budget doc carries
    ``present`` (the cost_events face exists): the V anchor counts the
    budget dim only when spend was actually measured — a workspace with
    no cost telemetry contributes no budget term."""
    facts = fact_face(ws)
    frac = budget_fraction(ws)
    chain = chain_progress(ws)
    pattern = claim_pattern(ws)
    return {
        "schema": SCHEMA,
        "facts": {"count": facts["count"], "verified": facts["verified"],
                  "bucket": fact_bucket(facts["count"])},
        "claims": {"pattern": pattern},
        "budget": {"fraction": round(frac, 4),
                   "bucket": budget_bucket(frac),
                   "present": (Path(ws) / COST_EVENTS_REL).is_file()},
        "chain": None if chain is None else {"k": chain[0], "n": chain[1]},
        "phase": phase(ws),
        "sides": {},  # RESERVED: v0.2 side-trajectory tree (owner pin)
    }


def signature_str(snap: dict) -> str:
    """The canonical signature string — the issue-386 Q-table key form.
    Order-stable; '-' marks an absent dim; sides stays '-' until v0.2."""
    pattern = (snap.get("claims") or {}).get("pattern") or "-"
    chain = snap.get("chain")
    chain_part = "-" if not chain else f"{chain['k']}/{chain['n']}"
    phase_part = snap.get("phase") or "-"
    budget = snap.get("budget") or {}
    facts = snap.get("facts") or {}
    return (f"{SCHEMA}|fc={facts.get('bucket', 0)}"
            f"|fv={facts.get('verified', 0)}"
            f"|cp={pattern}"
            f"|bg={budget.get('bucket', 0)}"
            f"|ch={chain_part}"
            f"|ph={phase_part}"
            f"|sd=-")


def signature_hash(snap: dict) -> str:
    """Short table-addressable hash of the canonical signature."""
    return hashlib.sha256(
        signature_str(snap).encode("utf-8")).hexdigest()[:12]


# ---------- V(s) anchor (deterministic, lookup-only) ----------------------

def v_anchor(snap: dict) -> float:
    """The deterministic progress anchor V(s): weighted mean over PRESENT
    dims (absent dims renormalize out; no faces -> 0.0). Pure — no
    learning, no banked data (per-signature empirical correction is the
    documented v0.2 seam). Result in [0, 1]."""
    terms: list[tuple[float, float]] = []
    chain = snap.get("chain")
    if chain:
        n = int(chain.get("n") or 0)
        k = int(chain.get("k") or 0)
        if n > 0:
            terms.append((W_CHAIN, min(max(k / n, 0.0), 1.0)))
    facts = snap.get("facts") or {}
    count = int(facts.get("count") or 0)
    if count > 0:
        verified = int(facts.get("verified") or 0)
        terms.append((W_FACTS, min(max(verified / count, 0.0), 1.0)))
    budget = snap.get("budget") or {}
    if budget.get("present"):
        frac = float(budget.get("fraction") or 0.0)
        terms.append((W_BUDGET, min(max(1.0 - frac, 0.0), 1.0)))
    # W_SIDES stays 0.0 in v0.1.6 — the reserved side-completion seam
    if not terms:
        return 0.0
    total_w = sum(w for w, _ in terms)
    return sum(w * t for w, t in terms) / total_w


# ---------- mainline situation snapshot stream ----------------------------

def v_from_workspace(ws) -> float:
    """V(s) over the workspace as it stands (the situation-stream and
    runner face). Pure; deterministic."""
    return v_anchor(snapshot(ws))


def append_snapshot(ws, trigger: str, tick=None, ts=None) -> dict:
    """Append one mainline situation snapshot row. Fail-open: any failure
    returns {"appended": False, ...} and never raises into the producer
    (recording never breaks the loop). ``tick=None`` inherits the
    convergence-ledger tick (kunglao_log.current_tick)."""
    ws = Path(ws)
    row: dict = {}
    try:
        if tick is None:
            from kunglao_log import current_tick
            tick = current_tick(ws)
        state = snapshot(ws)
        row = {
            "schema": SITUATION_SCHEMA,
            "ts": ts or _now(),
            "trigger": str(trigger),
            "tick": tick,
            "state": state,
            "signature": signature_str(state),
            "signature_hash": signature_hash(state),
        }
        p = ws / SITUATIONS_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        import os
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return {"appended": True, "row": row}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("append_snapshot", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "row": row}


def read_situations(ws) -> list[dict]:
    """Tolerant read of the snapshot stream (missing -> [])."""
    p = Path(ws) / SITUATIONS_REL
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
