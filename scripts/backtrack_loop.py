#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtrack_loop.py — #882 retrospective-loop host: three touchpoints, four
outputs, the cockpit trio.

RC3 close-out: the observation chain (#879 trace identity -> #880 settlement
rows -> #881 tool-value aggregator) produced data but nothing LOOKED back at
it — plan_reviser/plan_stages were orphans and kunglao-decide had zero
callers. This module hosts the three event-driven touchpoints (zero human
reminders) and the four auditable outputs:

  touchpoints
    1. micro-retro      (dispatch face, hooks/dispatch_gate.py): O(1) index
                        read of the K most recent settlements at the same
                        (scene, operation) -> the "前车之鉴" block in the
                        dispatch contract. Advisory context only; zero
                        lessons -> zero output (#754 noise contract).
    2. settlement retro (register face, register_proven_gate.emit_settlements):
                        at the moment a claim transition settles, a local
                        replay of the claim's trace subgraph lands as
                        runs/<ts>-retro-<claim>.md; PROVEN-without-PQ-movement
                        is flagged (fake-success early exposure).
    3. policy retro     (heartbeat_tick face): gated by every-N-settlements /
                        mission stall fingerprint / plan_review ritual; the
                        window aggregation + drift report + kunglao-decide
                        output land on runs/retro-agenda-<ts>.md as DATA
                        ITEMS and PROPOSAL lines.

  outputs
    settlement rows (pre-#880) / retro reports / pattern report + hypothesis
    seeds (HypothesisStore) / revision proposals (agenda only).

CONSTITUTIONAL ISOLATION (non-negotiable, issue #882): this module FILES
proposals, seeds and agendas — it NEVER executes a replan. plan_reviser
--apply and plan_stages.review stay orchestrator-owned; no code path here
calls them. The replan DECISION belongs to the orchestrator.

State (runs/, derived-data dotfiles in the recall_metrics style):
    .retro-state.json  {"settlements_since_retro": N, "last_retro_ts": ts}
                       — the backlog lag IS the cockpit 回溯滞后 field.
    .retro-index.json  {"<scene>|<operation>": [recent settlement entries]}
                       — the O(1) micro-retro read face (bounded, K per key).

Usage:
  python backtrack_loop.py --policy <workspace>   # heartbeat_tick step (advisory)
  python backtrack_loop.py --status <workspace>   # lag / pending / due JSON
Exit codes: always 0 (observability never gates; the tick rc contract is
untouched).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import kunglao_log

# #863 Family C: workspace resolution is single-sourced in ws_layout
from ws_layout import resolve_strict as _resolve_ws

MICRO_K = 3                        # rolling entries kept per (scene, operation)
POLICY_EVERY_N_SETTLEMENTS = 5     # policy-retro gate: settlements since last
BACKTRACK_LAG_WARN = 8             # statusline probe threshold (settlements)
UNATTRIBUTED_RATE_WARN = 0.30      # statusline probe threshold (fraction)
MAX_TRACE_ROWS = 40                # bounded local replay (subgraph tail)
SUBPROC_TIMEOUT_S = 30             # drift/decide inner subprocess budget
STATE_REL = Path("runs") / ".retro-state.json"
INDEX_REL = Path("runs") / ".retro-index.json"
AGENDA_GLOB = "retro-agenda-*.md"
PROPOSAL_PREFIX = "- PROPOSAL "

SCRIPTS_DIR = Path(__file__).resolve().parent


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


def _parse_ts(value) -> float | None:
    """ISO8601 Z -> epoch seconds; None on anything unparseable."""
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OSError):
        return None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# (scene, operation) vocabulary (#880 label + tool_tiers scene, zero new words)
# ---------------------------------------------------------------------------

def scene_operation_key(ws: Path, claim_id: str | None) -> tuple[str, str]:
    """The micro-retro grouping key: (tool_tiers scene, claim operation label).

    Unlabeled claims share the tool_value.UNLABELED bucket (zero new
    vocabulary — the #880 ruling). Fail-open: sniff/parse failure degrades to
    (generic-binary, unlabeled)."""
    ws = Path(ws)
    scene = "generic-binary"
    operation = "(unlabeled)"
    try:
        import tool_tiers
        scene = tool_tiers.scene_for(ws)
    except Exception:  # noqa: BLE001 — scene sniff is best-effort
        pass
    try:
        data = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
        for c in (data.get("claims") or []):
            if not isinstance(c, dict):
                continue
            if str(c.get("id", "") or "").strip() == str(claim_id or ""):
                op = str(c.get("operation", "") or "").strip().lower()
                if op:
                    operation = op
                break
    except (OSError, yaml.YAMLError):
        pass
    return scene, operation


def _key_str(scene: str, operation: str) -> str:
    return f"{scene}|{operation}"


# ---------------------------------------------------------------------------
# state faces
# ---------------------------------------------------------------------------

def lag(ws: Path) -> int:
    """回溯滞后: settlements since the last policy retro (cockpit field)."""
    return int(_read_json(Path(ws) / STATE_REL)
               .get("settlements_since_retro") or 0)


def _bump_lag(ws: Path) -> None:
    path = Path(ws) / STATE_REL
    state = _read_json(path)
    state["settlements_since_retro"] = lag(ws) + 1
    state.setdefault("last_retro_ts", None)
    _write_json_atomic(path, state)


def record_settlement(ws: Path, claim_id: str, to: str, *,
                      tools: list | None = None, outcome: str | None = None,
                      trace_id: str | None = None,
                      ts: str | None = None) -> None:
    """Settlement-face bookkeeping (called from
    register_proven_gate.emit_settlements): bump the backlog lag and roll the
    (scene, operation) index entry the dispatch face will read O(1)."""
    ws = Path(ws)
    scene, operation = scene_operation_key(ws, claim_id)
    entry = {
        "ts": ts or utc_now(),
        "claim": str(claim_id),
        "to": str(to),
        "outcome": str(outcome or to),
        "tools": [str(t) for t in (tools or [])],
        "trace_id": trace_id,
    }
    index = _read_json(ws / INDEX_REL)
    index = {k: v for k, v in index.items() if isinstance(v, list)}
    entries = index.setdefault(_key_str(scene, operation), [])
    entries.append(entry)
    index[_key_str(scene, operation)] = entries[-MICRO_K:]
    _write_json_atomic(ws / INDEX_REL, index)
    _bump_lag(ws)


def micro_lessons(ws: Path, claim_id: str | None,
                  k: int | None = None) -> list[dict]:
    """The K most recent settlements at the dispatching claim's
    (scene, operation) — the O(1) read (one small index file, never the
    whole ledger)."""
    ws = Path(ws)
    index = _read_json(ws / INDEX_REL)
    scene, operation = scene_operation_key(ws, claim_id)
    entries = index.get(_key_str(scene, operation)) or []
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)][-(k or MICRO_K):]


def micro_lessons_context(ws: Path, claim_id: str | None,
                          k: int | None = None) -> str | None:
    """The 前车之鉴 block for the dispatch contract; None when the claim's
    key has no settlement history (zero-noise #754 — nothing to look back
    at, nothing injected)."""
    hits = micro_lessons(ws, claim_id, k)
    if not hits:
        return None
    scene, operation = scene_operation_key(ws, claim_id)
    lines = [
        f"backtrack_loop: micro-lessons (前车之鉴) for {claim_id} — prior "
        f"settlements at the same scene×operation "
        f"({_key_str(scene, operation)}):"
    ]
    for e in hits:
        tools = ",".join(e.get("tools") or []) or "-"
        lines.append(
            f"- {e.get('ts')} {e.get('claim')} -> {e.get('outcome')} "
            f"tools={tools}")
    lines.append(
        "Same-key attempts failed before; change the method (or show the "
        "disproof) instead of re-running the same shape — repeats are the "
        "failure-signature the backtrack loop measures.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# settlement retro (touchpoint 2 output: runs/<ts>-retro-<claim>.md)
# ---------------------------------------------------------------------------

def _claim_attrs(ws: Path, claim_id: str) -> dict:
    try:
        data = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    for c in (data.get("claims") or []):
        if isinstance(c, dict) and \
                str(c.get("id", "") or "").strip() == str(claim_id):
            return c
    return {}


def fake_success_flags(ws: Path, claim_id: str, to: str) -> list[str]:
    """The issue's fake-success probe: a PROVEN settlement that cannot move
    PQ coverage is flagged AT the settlement point (mission_ledger.update
    maps answers_question -> PQ answered; a PROVEN claim without a live
    answer link is coverage theater)."""
    if str(to).upper() != "PROVEN":
        return []
    aq = str(_claim_attrs(ws, claim_id).get("answers_question", "")
             or "").strip()
    if not aq:
        return ["FAKE-SUCCESS: PROVEN without answers_question — PQ coverage "
                "cannot move from this settlement"]
    try:
        led = yaml.safe_load(
            (ws / "runs" / "mission_ledger.yaml").read_text(
                encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        led = {}
    pq = next((p for p in ((led.get("mission") or {}).get("pqs") or [])
               if str(p.get("id")) == aq), None)
    if pq is None:
        return [f"FAKE-SUCCESS: answers_question {aq} has no mission-ledger "
                f"PQ row (coverage unmoved)"]
    if str(pq.get("state")) != "answered":
        return [f"FAKE-SUCCESS: PROVEN but PQ {aq} state="
                f"{pq.get('state')!r} (coverage unmoved)"]
    return []


def settlement_retro(ws: Path, claim_id: str, *, to: str, frm: str | None =
                     None, trace_id: str | None = None,
                     ts: str | None = None) -> Path | None:
    """Local replay of the claim's trace subgraph at the settlement moment
    -> runs/<ts>-retro-<claim>.md (+ one retro_report ledger row). The
    report is a proposal input for the orchestrator — never an action."""
    ws = Path(ws)
    try:
        rows = [r for r in kunglao_log._all_rows(ws)
                if (trace_id and r.get("trace_id") == trace_id)
                or str(r.get("claim") or "") == str(claim_id)]
    except Exception:  # noqa: BLE001 — ledger read failure degrades to empty
        rows = []
    flags = fake_success_flags(ws, claim_id, to)
    stamp = (ts or utc_now()).replace(":", "").replace("-", "")
    doc = ws / "runs" / f"{stamp}-retro-{claim_id}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# settlement retro — {claim_id}",
        "",
        f"- ts: {ts or utc_now()}",
        f"- transition: {frm or '?'} -> {to}",
        f"- trace_id: {trace_id or '(unattributed)'}",
        f"- fake_success: {' | '.join(flags) if flags else 'none'}",
        "",
        "## trace subgraph (local replay)",
        "",
    ]
    if rows:
        for r in rows[-MAX_TRACE_ROWS:]:
            lines.append(
                f"- {r.get('ts')} {r.get('actor')} {r.get('action')} "
                f"claim={r.get('claim')} trace={r.get('trace_id')} "
                f"detail={r.get('detail')}")
    else:
        lines.append("(no ledger rows for this claim/trace)")
    lines += [
        "",
        "## reader contract",
        "",
        "Consumed by the orchestrator at plan_review. A FAKE-SUCCESS flag "
        "is a proposal on the retro agenda, never an automatic replan "
        "(#882 constitutional isolation).",
        "",
    ]
    doc.write_text("\n".join(lines), encoding="utf-8")
    try:
        kunglao_log.emit(ws, "backtrack_loop", "retro_report",
                         claim=str(claim_id), artifact=doc.name,
                         trace_id=trace_id,
                         detail=json.dumps({"to": to, "frm": frm,
                                            "fake_success": len(flags)},
                                           ensure_ascii=False))
    except Exception:  # noqa: BLE001 — logging never breaks settlement
        pass
    return doc


# ---------------------------------------------------------------------------
# policy retro (touchpoint 3: heartbeat_tick gate -> window aggregation)
# ---------------------------------------------------------------------------

def policy_due(ws: Path, n: int = POLICY_EVERY_N_SETTLEMENTS) -> dict:
    """The cheap gate (issue: 每 N 结算 / stall 指纹 / plan_review ritual).
    All three sources are pre-existing read-only faces."""
    ws = Path(ws)
    why: list[str] = []
    l = lag(ws)
    if l >= n:
        why.append(f"{l} settlements since last policy retro (>= {n})")
    try:
        import mission_stall
        if mission_stall.stall_mission(ws).get("stalled"):
            why.append("mission stall fingerprint tripped (dV_m flat x K)")
    except Exception:  # noqa: BLE001 — a gate source must never raise
        pass
    try:
        import plan_stages
        if plan_stages.should_review(ws).get("due"):
            why.append("plan_review ritual due (plan_stages.should_review)")
    except Exception:  # noqa: BLE001
        pass
    return {"due": bool(why), "why": why}


def pending_proposals(ws: Path) -> int:
    """提案待审数: PROPOSAL lines on agenda files written AFTER the most
    recent plan_review ledger row (pure read derivation — a verdict lands a
    plan_review row, which retroactively clears every older agenda; no
    write-path coupling into plan_stages)."""
    ws = Path(ws)
    review_ts = None
    try:
        for r in kunglao_log._all_rows(ws):
            if r.get("action") != "plan_review":
                continue
            t = _parse_ts(r.get("ts"))
            if t is not None and (review_ts is None or t > review_ts):
                review_ts = t
    except Exception:  # noqa: BLE001
        review_ts = None
    pending = 0
    runs = ws / "runs"
    for p in sorted(runs.glob(AGENDA_GLOB)) if runs.is_dir() else []:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^-\s+ts:\s*(\S+)", text, re.M)
        agenda_ts = _parse_ts(m.group(1)) if m else None
        if review_ts is not None and (
                agenda_ts is None or agenda_ts <= review_ts):
            continue  # a review verdict postdates this agenda -> consumed
        pending += sum(1 for ln in text.splitlines()
                       if ln.startswith(PROPOSAL_PREFIX))
    return pending


def cockpit_backtrack(ws: Path) -> dict:
    """The cockpit trio (issue: 回溯滞后 / 未归因率 / 提案待审数)."""
    ws = Path(ws)
    rate = 0.0
    try:
        rate = float(kunglao_log.unattributed_rate(ws).get("rate") or 0.0)
    except Exception:  # noqa: BLE001 — fail-open cockpit field
        rate = 0.0
    return {"backtrack_lag": lag(ws),
            "unattributed_rate": round(rate, 4),
            "pending_proposals": pending_proposals(ws)}


def _subprocess_report(script: str, ws: Path, *extra: str) -> dict:
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script), str(ws), *extra],
            capture_output=True, text=True, timeout=SUBPROC_TIMEOUT_S,
            encoding="utf-8", errors="replace")
        return {"rc": r.returncode, "stdout": r.stdout,
                "stderr": r.stderr[-400:]}
    except Exception as exc:  # noqa: BLE001 — advisory face, fail-open
        return {"rc": -1, "stdout": "", "stderr": repr(exc)}


def _window_v_m(ws: Path, start_ts: str | None) -> dict:
    """Mission-ledger value items for the agenda (replan 后 ΔV_m/claim 可算)."""
    try:
        led = yaml.safe_load(
            (ws / "runs" / "mission_ledger.yaml").read_text(
                encoding="utf-8")) or {}
        hist = ((led.get("mission") or {}).get("history")) or []
    except (OSError, yaml.YAMLError):
        hist = []
    v_now = float(hist[-1].get("v_m", 0.0)) if hist else 0.0
    v_start = None
    if start_ts:
        t0 = _parse_ts(start_ts)
        for h in hist:
            t = _parse_ts(h.get("ts"))
            if t0 is not None and t is not None and t <= t0:
                v_start = float(h.get("v_m", 0.0))
    if v_start is None:
        v_start = float(hist[0].get("v_m", 0.0)) if hist else 0.0
    return {"v_m": round(v_now, 6),
            "window_dv_m": round(v_now - v_start, 6)}


def _seed_hypotheses(ws: Path, repeated: list[dict]) -> list[dict]:
    """File one hypothesis per repeated failure signature (idempotent via a
    body marker — the hypothesis_seeder pq:<qid> convention)."""
    from hypothesis_seeder import _next_free_id
    from hypothesis_store import Hypothesis, HypothesisStore
    store = HypothesisStore(ws / "hypotheses")
    existing_markers = {h.body for h in store.list_all()}
    seeded: list[dict] = []
    for sig in repeated:
        marker = f"retro:{sig['key']}"
        if any(marker in body for body in existing_markers):
            continue
        hyp = Hypothesis(
            id=_next_free_id(store),
            claim_id=sig["last_claim"],
            competitor_group=f"retro-{sig['key']}"[:120],
            candidates=[],
            status="open",
            predicted_observation=(
                "next dispatch at the same scene x operation repeats the "
                "failure signature"),
            body=(f"{marker}\n\nSeeded by the #882 policy retro: "
                  f"{sig['count']} negative settlement(s) share the "
                  f"signature {sig['key']} (last claim {sig['last_claim']}). "
                  "Adjudicate by refute/supersede per #528.\n"),
        )
        try:
            store.create(hyp)
        except Exception:  # noqa: BLE001 — seeding must never kill the retro
            continue
        try:
            kunglao_log.emit(ws, "backtrack_loop", "hypothesis_seed",
                             claim=sig["last_claim"], artifact=hyp.id,
                             detail=json.dumps({"key": sig["key"]},
                                               ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        seeded.append({"id": hyp.id, "key": sig["key"]})
    return seeded


def run_policy_retro(ws: Path, now: datetime | None = None) -> dict:
    """Window aggregation -> agenda with data items + proposals (+ seeds).
    Returns {"agenda", "proposals", "seeds", "triggers"}. NEVER executes a
    replan (see the module docstring's constitutional isolation)."""
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    state = _read_json(ws / STATE_REL)
    last_ts = state.get("last_retro_ts")
    t0 = _parse_ts(last_ts)
    try:
        rows = [r for r in kunglao_log._all_rows(ws)
                if r.get("action") == "claim_settled"]
    except Exception:  # noqa: BLE001
        rows = []
    window = [r for r in rows
              if t0 is None or (_parse_ts(r.get("ts")) or 0) > t0]

    try:
        from tool_value import (NEGATIVE_SETTLEMENTS, POSITIVE_SETTLEMENTS,
                                _register_attrs)
        attrs = _register_attrs(ws)
    except Exception:  # noqa: BLE001 — aggregator absent: unlabeled fallback
        attrs = {}
        NEGATIVE_SETTLEMENTS = {"REFUTED", "NEGATIVE", "DEAD"}
        POSITIVE_SETTLEMENTS = {"PROVEN", "VERIFIED"}
    try:
        import tool_tiers
        scene = tool_tiers.scene_for(ws)
    except Exception:  # noqa: BLE001
        scene = "generic-binary"

    def _sign(row: dict) -> str | None:
        try:
            to = str((json.loads(str(row.get("detail") or "")) or {})
                     .get("to") or "").upper()
        except json.JSONDecodeError:
            return None
        return ("positive" if to in POSITIVE_SETTLEMENTS else
                "negative" if to in NEGATIVE_SETTLEMENTS else None)

    neg_by_key: dict[str, int] = {}
    for e in _read_json(ws / INDEX_REL).values():
        if not isinstance(e, list):
            continue
        for entry in e:
            if isinstance(entry, dict) and \
                    str(entry.get("outcome", "")).upper() in \
                    NEGATIVE_SETTLEMENTS:
                k = scene_operation_key(ws, entry.get("claim"))
                neg_by_key[_key_str(*k)] = neg_by_key.get(
                    _key_str(*k), 0) + 1

    negatives = positives = repeated_n = 0
    win_by_key: dict[str, int] = {}
    repeated: list[dict] = []
    last_claim_by_key: dict[str, str] = {}
    for r in window:
        sign = _sign(r)
        cid = str(r.get("claim") or "").strip()
        op = str((attrs.get(cid) or {}).get("operation")
                 or "(unlabeled)").lower()
        key = _key_str(scene, op)
        if sign == "negative":
            negatives += 1
            neg_by_key[key] = neg_by_key.get(key, 0) + 1
            win_by_key[key] = win_by_key.get(key, 0) + 1
            if neg_by_key[key] >= 2:
                repeated_n += 1
            last_claim_by_key[key] = cid
        elif sign == "positive":
            positives += 1
    repeated = [{"key": k, "count": c, "last_claim": last_claim_by_key.get(k, "")}
                for k, c in sorted(win_by_key.items()) if neg_by_key.get(k, 0) >= 2]
    repeat_rate = round(repeated_n / negatives, 4) if negatives else 0.0

    vm = _window_v_m(ws, last_ts)

    drift = _subprocess_report("plan_drift_detector.py", ws)
    decide = _subprocess_report("kunglao-decide.py", ws, "--json")
    try:
        decide_json = json.loads(decide["stdout"] or "{}")
    except json.JSONDecodeError:
        decide_json = {"decision": "unavailable",
                       "error": decide["stderr"][-200:]}

    from plan_reviser import run_checks as reviser_checks
    suggestions = reviser_checks(ws)

    proposals: list[str] = []
    for s in suggestions:
        proposals.append(
            f"{PROPOSAL_PREFIX}[reviser:{s.get('trigger')}] "
            f"{s.get('claim') or '(workspace)'}: {s.get('detail')}")
    for r in window:
        try:
            detail = json.loads(str(r.get("detail") or ""))
        except json.JSONDecodeError:
            continue
        cid = str(r.get("claim") or "").strip()
        if str(detail.get("to") or "").upper() != "PROVEN":
            continue
        for flag in fake_success_flags(ws, cid, "PROVEN"):
            proposals.append(f"{PROPOSAL_PREFIX}[retro:fake-success] "
                             f"{cid}: {flag}")
    for sig in repeated:
        proposals.append(
            f"{PROPOSAL_PREFIX}[retro:failure-signature] {sig['key']}: "
            f"{sig['count']} negative settlement(s) share this (scene,"
            "operation) — hypothesis seeded; micro-lessons now injects "
            "前车之鉴 at dispatch; consider a method change at plan_review")

    seeds = _seed_hypotheses(ws, repeated)

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    agenda = ws / "runs" / f"retro-agenda-{stamp}.md"
    agenda.parent.mkdir(parents=True, exist_ok=True)
    due = policy_due(ws)
    lines = [
        f"# policy retro agenda — {utc_now()} (#882)",
        "",
        f"- ts: {utc_now()}",
        f"- trigger: {'; '.join(due['why']) or '(manual run)'}",
        f"- window: settlements since {last_ts or '(beginning)'} "
        f"({len(window)} row(s))",
        "",
        "## data items",
        "",
        f"- v_m: {vm['v_m']} (window dV_m: {vm['window_dv_m']} over "
        f"{len(window)} settlement(s))",
        f"- settlements_window: {len(window)} (positive {positives} / "
        f"negative {negatives})",
        f"- repeat_rate: {repeat_rate} (repeated {repeated_n} / "
        f"negative {negatives}) — failure-signature repeat metric",
        "- top_failure_signatures: "
        + (", ".join(f"{k} x{c}" for k, c in sorted(
            win_by_key.items(), key=lambda kv: -kv[1])[:5]) or "(none)"),
        "",
        "## drift (plan_drift_detector)",
        "",
        f"rc={drift['rc']}",
        "```",
 *(drift["stdout"].strip().splitlines()[-40:] if drift["stdout"].strip()
   else ["(no output)"]),
        "```",
        "",
        "## DECIDE (kunglao-decide --json)",
        "",
        f"decision={decide_json.get('decision')} "
        f"exit_code={decide_json.get('exit_code')}",
        "```json",
        json.dumps(decide_json, ensure_ascii=False, indent=2)[:2000],
        "```",
        "",
        "## proposals (orchestrator decision REQUIRED — never "
        "auto-executed, #882 constitutional isolation)",
        "",
    ]
    lines += (proposals or ["(no proposals this window)"])
    lines += [
        "",
        "## hypothesis seeds",
        "",
    ]
    lines += [f"- {s['id']} retro:{s['key']}" for s in seeds] or \
             ["(none)"]
    lines.append("")
    agenda.write_text("\n".join(lines), encoding="utf-8")

    try:
        kunglao_log.emit(ws, "backtrack_loop", "retro_policy",
                         artifact=agenda.name,
                         detail=json.dumps(
                             {"trigger": due["why"],
                              "settlements_window": len(window),
                              "repeat_rate": repeat_rate,
                              "proposals": len(proposals),
                              "seeds": len(seeds)},
                             ensure_ascii=False))
    except Exception:  # noqa: BLE001 — logging never breaks the retro
        pass
    _write_json_atomic(ws / STATE_REL,
                       {"settlements_since_retro": 0,
                        "last_retro_ts": utc_now()})
    return {"agenda": str(agenda), "proposals": len(proposals),
            "seeds": seeds, "triggers": due["why"]}


# ---------------------------------------------------------------------------
# CLI (heartbeat_tick advisory step; rc never weighs into the tick)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # captured stream without reconfigure (pytest capsys)
    args = sys.argv[1:] if argv is None else argv
    if "--policy" in args:
        rest = args[args.index("--policy") + 1:]
    elif "--status" in args:
        rest = args[args.index("--status") + 1:]
    else:
        rest = []
    if not rest:
        print("Usage: backtrack_loop.py --policy <ws> | --status <ws>",
              file=sys.stderr)
        return 0
    ws = _resolve_ws(rest[0])
    if "--status" in args:
        due = policy_due(ws)
        print(json.dumps({"lag": lag(ws), "due": due["due"],
                          "why": due["why"],
                          **cockpit_backtrack(ws)},
                         ensure_ascii=False))
        return 0
    # --policy: gated advisory step (zero noise when not due, #754)
    due = policy_due(ws)
    if not due["due"]:
        print("backtrack: policy retro not due "
              f"(lag={lag(ws)}); nothing to do")
        return 0
    out = run_policy_retro(ws)
    print(f"backtrack: policy retro ran — agenda {out['agenda']} "
          f"(proposals={out['proposals']}, seeds={len(out['seeds'])}, "
          f"trigger={'; '.join(out['triggers'])})")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
