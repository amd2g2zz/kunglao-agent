#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""terminal_settlement.py — terminal credit assignment, the arc-close credit
ledger (issue 136, v0.1.6 P1 slice).

The ranker is single-step Thompson; before this module nothing recorded
WHICH dispatches and case-greens enabled a closure — the most valuable
lesson of a finished mission was discarded at the moment it became known
(the 2026-09-07 reward-architecture audit's "short-sightedness").

Reward-epistemology ruling (2026-09-20): per-attempt records state WHAT
happened, never worth; value attribution happens ONLY at arc close. This
module is exactly that arc-close artifact:

  - At master-oracle-green closure (convergence_check.decide -> CONVERGED,
    after the carrier-drift fail-closed gate — issue 829's fail-closed
    face) ONE task-terminal
    settlement row is emitted into the EXISTING ledger surface
    (kunglao_log.emit -> runs/logs/kunglao-*.jsonl — the same organ
    claim_settled rows use; the no-new-organs doctrine (issue 137): no new database,
    no new file format).
  - The row back-references the enabling chain: the issue-130 reference graph
    (cases -> hypotheses -> claims) read in the CLOSURE direction —
    which hypotheses' cases greened in what order (green order = first
    `observation` pass row per case in ledger append order), which claims
    settled, which premise_corrections fired en route (case bank).

Idempotency is ARC-scoped: repeated CONVERGED ticks write nothing (no new
settlements since the last terminal row); settlements after the last row
are a NEW arc — its closure writes a fresh row. Value attribution at
EVERY arc close, one row per arc.

Consumption (issue 136 fix point 3): case_bank.retrieve weights terminal-chain
claims above mid-loop entries WITHIN each roi class — a lesson that led to
closure is worth more than one that merely resolved a side question.
Owner ruling 4's failures-first class rank stays the primary sort.

Fail-open everywhere: a terminal row is observability of success — it must
never block, and never fail, the closure it credits (issue-275 WARN policy).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ACTION = "task_terminal_settlement"   # registered in event_taxonomy.EMIT_ACTIONS
SCHEMA = "task-terminal-settlement/1"

# Bounded whole-ledger scan (closures are rare; the ledger is the organ).
LEDGER_SCAN_LIMIT = 100_000

ORACLE_STATUS_REL = Path("runs") / "oracle-status.json"
CASES_DIR_REL = Path("oracle") / "cases"

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] terminal_settlement WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _ledger_rows(ws: Path) -> list[dict]:
    """Every parseable ledger row, chronological (kunglao_log's one read
    path). Missing ledger -> [] — a legacy workspace closes with an empty
    chain, not an error."""
    from kunglao_log import tail
    return tail(ws, LEDGER_SCAN_LIMIT)


def _green_case_ids(ws: Path) -> list[str]:
    """Green (status == pass) case ids in verdict-file order (the oracle-status face, issue 108).

    Tolerant read: an absent/unreadable verdict file is an empty green set
    (the closure's chain is then claims_settled/corrections only)."""
    path = Path(ws) / ORACLE_STATUS_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cases = doc.get("cases")
        if not isinstance(cases, dict):
            return []
    except (OSError, ValueError, TypeError):
        return []
    out = []
    for cid, raw in cases.items():
        if isinstance(raw, dict) \
                and str(raw.get("status") or "").lower() == "pass":
            out.append(str(cid))
    return out


def _case_declarations(ws: Path) -> dict[str, dict]:
    """case_id -> {hypothesis_ref, green_up} from oracle/cases/*.yaml — the
    issue-130 case leg. Tolerant per file (the settlement-side reader shape of
    oracle_runner._load_pq_declarations): an unreadable/wrong-shaped case
    is a missing declaration, never a refusal into the closure path."""
    import yaml
    cases_dir = Path(ws) / CASES_DIR_REL
    out: dict[str, dict] = {}
    if not cases_dir.is_dir():
        return out
    for p in sorted(cases_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — unreadable case is not signal
            continue
        if not isinstance(doc, dict):
            continue
        cid = str(doc.get("id") or p.stem).strip()
        if not cid:
            continue
        green_up = doc.get("update_map", {}).get("green_up") \
            if isinstance(doc.get("update_map"), dict) else None
        out[cid] = {
            "hypothesis_ref": str(doc.get("hypothesis_ref") or "").strip(),
            "green_up": [str(x) for x in green_up] if isinstance(green_up,
                                                                 list) else [],
        }
    return out


def _hypothesis_claims(ws: Path) -> dict[str, str]:
    """hypothesis id -> claim id — the issue-130 hypothesis leg. Fail-open (the
    store read failing is the documented hypothesis_store_unreadable face)."""
    try:
        from hypothesis_store import HypothesisStore
        root = Path(ws) / "hypotheses"
        if root.exists() and not root.is_dir():
            return {}
        return {h.id: (h.claim_id or "") for h in
                HypothesisStore(root).list_all()}
    except Exception:  # noqa: BLE001 — the chain degrades, the row lands
        return {}


def _detail_json(row: dict) -> dict:
    try:
        doc = json.loads(str(row.get("detail") or ""))
        return doc if isinstance(doc, dict) else {}
    except ValueError:
        return {}


def _chain_entry(cid: str, green_order: dict[str, int],
                 decls: dict[str, dict], hyp_claims: dict[str, str]) -> dict:
    """One chain entry for green case `cid`, with ledger-style null_reasons
    (issue 880: field -> reason) for every leg the graph could not resolve."""
    decl = decls.get(cid) or {}
    hyp_ref = decl.get("hypothesis_ref") or None
    claim_id = hyp_claims.get(hyp_ref or "") or None if hyp_ref else None
    null_reasons: dict[str, str] = {}
    if hyp_ref is None:
        null_reasons["hypothesis_ref"] = "not_declared"
    elif claim_id is None:
        null_reasons["claim_id"] = "hypothesis_unresolved"
    if green_order.get(cid) is None:
        null_reasons["order"] = "no_observation_event"
    entry = {
        "order": green_order.get(cid),
        "case_id": cid,
        "hypothesis_ref": hyp_ref,
        "green_up": decl.get("green_up") or [],
        "claim_id": claim_id,
    }
    if null_reasons:
        entry["null_reasons"] = null_reasons
    return entry


def build_enabling_chain(ws: Path) -> dict:
    """The terminal-row payload: the issue-130 graph read closure-side.

    - chain: one entry per GREEN case, ordered by first-green (the first
      `observation` pass row in ledger append order; never-observed greens
      trail in verdict-file order with a null_reasons explanation).
      Each entry resolves case -> hypothesis_ref -> claim_id, degrading to
      null legs + null_reasons (the issue-880 honesty pattern) per unresolvable
      leg.
    - claims_settled: the arc's claim_settled rows in settlement order.
    - premise_corrections: every banked correction (issues 110/146), each marked
      in_chain when its claim sits in the enabling chain.
    """
    rows = _ledger_rows(ws)
    green_order: dict[str, int] = {}
    claims_settled: list[dict] = []
    for row in rows:
        action = str(row.get("action") or "")
        if action == "observation":
            detail = _detail_json(row)
            cid = str(detail.get("case_id") or "")
            if detail.get("status") == "pass" and cid \
                    and cid not in green_order:
                green_order[cid] = len(green_order) + 1
        elif action == "claim_settled":
            claims_settled.append({"claim": str(row.get("claim") or ""),
                                   "to": str(_detail_json(row).get("to")
                                            or "")})

    greens = _green_case_ids(ws)
    decls = _case_declarations(ws)
    hyp_claims = _hypothesis_claims(ws)
    ordered = sorted(enumerate(greens),
                     key=lambda pair: (green_order.get(pair[1], 10 ** 9),
                                       pair[0]))
    chain = [_chain_entry(cid, green_order, decls, hyp_claims)
             for _, cid in ordered]

    chain_claims = {str(c.get("claim_id")) for c in chain
                    if c.get("claim_id")}
    corrections = []
    try:
        import case_bank
        for e in case_bank.read_entries(ws):
            corr = str(e.get("premise_correction") or "").strip()
            if not corr:
                continue
            claim = str(e.get("claim_id") or "")
            corrections.append({
                "claim_id": claim,
                "method": str(e.get("method") or ""),
                "premise_correction": corr,
                "in_chain": bool(claim) and claim in chain_claims,
            })
    except Exception as exc:  # noqa: BLE001 — corrections are additive
        warn("premise_corrections", f"{type(exc).__name__}: {exc}")

    return {
        "schema": SCHEMA,
        "chain": chain,
        "claims_settled": claims_settled,
        "premise_corrections": corrections,
    }


def latest_terminal_row(ws: Path) -> dict | None:
    """The most recent task_terminal_settlement row, or None."""
    found = None
    for row in _ledger_rows(ws):
        if str(row.get("action") or "") == ACTION:
            found = row
    return found


def terminal_chain_claims(ws: Path) -> set[str]:
    """Claim ids in the LATEST terminal row's enabling chain — the
    retrieval-weighting read face (case_bank). Unreadable row -> empty set
    (weighting degrades, ordering contract survives)."""
    row = latest_terminal_row(ws)
    if not row:
        return set()
    try:
        chain = _detail_json(row).get("chain") or []
        return {str(c.get("claim_id")) for c in chain
                if isinstance(c, dict) and c.get("claim_id")}
    except Exception:  # noqa: BLE001 — fail-open read face
        return set()


def write_terminal_settlement(ws: Path) -> dict:
    """Emit the arc-close terminal row (arc-deduped, fail-open).

    Dedup semantics: a terminal row exists AND no claim_settled row follows
    it -> this closure tick is the SAME arc, write nothing ({"duplicate":
    True}); settlements after the last row are a NEW arc -> a fresh row.
    Returns {"written": bool, "duplicate": bool[, "reason": str]}.
    """
    ws = Path(ws)
    try:
        rows = _ledger_rows(ws)
        last_terminal = None
        settled_after = False
        for row in rows:
            action = str(row.get("action") or "")
            if action == ACTION:
                last_terminal = row
                settled_after = False
            elif action == "claim_settled" and last_terminal is not None:
                settled_after = True
        if last_terminal is not None and not settled_after:
            return {"written": False, "duplicate": True}

        payload = build_enabling_chain(ws)
        from kunglao_log import emit
        ok = emit(ws, actor="convergence_check", action=ACTION,
                  detail=json.dumps(payload, ensure_ascii=False,
                                    sort_keys=True))
        return {"written": bool(ok), "duplicate": False}
    except Exception as exc:  # noqa: BLE001 — never gate the closure
        warn("write_terminal_settlement", f"{type(exc).__name__}: {exc}")
        return {"written": False, "duplicate": False,
                "reason": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":  # pragma: no cover — library module; CLI via ledger
    print(__doc__)
