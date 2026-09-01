#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""think_seat.py — the tick's THINK seat (#759 H1/H3; semantic source #711).

Issue #704 backgrounded dispatch. Its side effect (#711 field evidence E1):
the waiting-period tick produced action_taken EMPTY and zero cognitive
output — tokens burned with no reasoning artifact (#237 named the idle fault,
nobody gave it a replacement). This script gives the wait a SEAT:

  - detects the waiting period MECHANICALLY: a claim-register.yaml exists AND
    the VoI ranking (priority_ratio, the #499 authority) yields zero
    dispatchable actions. Undecidable inputs (no register / broken YAML /
    scorer crash) are never-waiting — the seat must not hijack workspaces the
    legacy #237 EMPTY contract still governs;
  - writes runs/.think-<ts>.md with a FIXED three-section schema
    (patterns / hypotheses / value) embedding an INPUT DIGEST (facts/_INDEX
    tail + hypothesis_store open list). The script guarantees the seat
    exists + the artifact lands + the path is machine-readable; it NEVER
    generates the thinking — the pending sections are filled IN PLACE by the
    orchestrator LLM;
  - tracks a stall counter (runs/think-state.json): unchanged
    (terminal_facts, open_claims) digest across consecutive waiting ticks.
    At STALL_TICKS_FOR_SEARCH the artifact gains a `## suggested_searches`
    section with mechanically-seeded retrieval queries (#759 H3: #711 E3's
    "not searching is a deterministic loss" countermeasure);
  - prints ONE LINE of JSON so heartbeat_tick can consume it (a waiting seat
    becomes the tick's action_taken). Advisory by construction: handled
    inputs exit 0; the caller treats unparseable stdout as seat-unavailable.

Usage: python think_seat.py <workspace>
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

from priority_ratio import EvidenceView, classify_action, is_open, priority_ratio
from status_defs import TERMINAL
from hypothesis_store import HypothesisStore, Hypothesis  # #711: bets

# H3 knob: consecutive zero-progress waiting ticks before retrieval is forced.
STALL_TICKS_FOR_SEARCH = 3
MAX_SUGGESTED_CLAIMS = 3      # cap the seeded query rows
INDEX_TAIL_LINES = 10         # facts/_INDEX.md tail embedded as input digest
THINK_STATE = "runs/think-state.json"

_HUMAN_CATEGORY = {
    "c2_config_extract": "C2 config extraction precedent",
    "command_table": "command dispatch table precedent",
    "protocol_restore": "protocol restoration precedent",
    "persistence": "persistence mechanism precedent",
    "injection": "injection technique precedent",
    "anti_analysis": "anti-analysis family precedent",
    "family_attribution": "family attribution precedent",
    "evidence_collection": "sample family precedent",
}


def _utc_compact() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — fail-open: corrupt state is not authority
        return {}


def dispatchable_count(ws: Path) -> int | None:
    """Zero-LLM proxy count of dispatchable actions; None = undecidable.

    Any failure here degrades to not-waiting: the seat fires only on a
    workspace whose ranking machinery ran clean and found nothing."""
    try:
        reg = _load_yaml(ws / "claim-register.yaml")
        deps = _load_yaml(ws / "claim_deps.yaml")
        evidence = EvidenceView.from_workspace(ws)
        return len(priority_ratio(reg.get("claims") or [], deps, evidence))
    except Exception:  # noqa: BLE001 — undecidable ≠ waiting
        return None


def progress_digest(ws: Path) -> tuple[int, int]:
    """(terminal_facts, open_claims) — the mechanical progress signal driving
    the stall counter. A new fact landing or a claim closing resets it."""
    evidence = EvidenceView.from_workspace(ws)
    claims = _load_yaml(ws / "claim-register.yaml").get("claims") or []
    terminal = len(evidence.terminal_fact_claims)
    open_count = sum(1 for c in claims if c.get("id") and is_open(c))
    return terminal, open_count


def update_stall_state(ws: Path, digest: tuple[int, int]) -> int:
    """Read-modify-write runs/think-state.json; returns current stall_ticks."""
    path = ws / THINK_STATE
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev_digest = prev.get("digest")
        stall = int(prev.get("stall_ticks", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        prev_digest, stall = None, 0
    stall = stall + 1 if prev_digest == list(digest) else 0
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "ts": _utc_compact(), "digest": list(digest), "stall_ticks": stall,
        }, indent=2), encoding="utf-8")
    except OSError:
        pass  # advisory counter — unwritable state costs a reset next run
    return stall


def facts_index_tail(ws: Path) -> list[str]:
    for cand in (ws / "facts" / "_INDEX.md", ws / "_INDEX.md"):
        if cand.exists():
            lines = [ln for ln in cand.read_text(
                encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            return lines[-INDEX_TAIL_LINES:]
    return []


def open_hypothesis_rows(ws: Path) -> list[str]:
    from hypothesis_store import HypothesisStore
    store = HypothesisStore(ws / "hypotheses")
    rows = [f"{h.id} claim={h.claim_id} group={h.competitor_group} "
            f"candidates={h.candidates}"
            for h in store.list_open()]
    return rows


def suggested_searches(ws: Path, stall_ticks: int) -> list[str]:
    """H3 seed rows — mechanically derived, non-empty once stalled. Wording
    refinement is the orchestrator's job; EXISTENCE is ours (#759 H3)."""
    if stall_ticks < STALL_TICKS_FOR_SEARCH:
        return []
    return precedent_rows(ws)
    claims = [c for c in _load_yaml(ws / "claim-register.yaml").get("claims") or []
              if c.get("id") and is_open(c)]
    rows: list[str] = []
    seen: set[str] = set()
    for c in claims[:MAX_SUGGESTED_CLAIMS]:
        cat = classify_action(c)
        label = _HUMAN_CATEGORY.get(cat, f"{cat} precedent")
        if label in seen:
            continue
        seen.add(label)
        rows.append(f"- websearch: {label} — public sample teardown matching "
                    f"claim {c['id']} (refine the query before running)")
        rows.append(f"- reference-library: `{cat}` scenario — "
                    f"`references_recall.py {cat}`, then read the hit domain file")
    return rows


def precedent_rows(ws: Path) -> list[str]:
    """Precedent-retrieval seed rows over OPEN claims (#711 E3 不搜=确定性损失)."""
    claims = [c for c in _load_yaml(
        ws / "claim-register.yaml").get("claims") or []
        if c.get("id") and is_open(c)]
    rows: list[str] = []
    seen: set[str] = set()
    for c in claims[:MAX_SUGGESTED_CLAIMS]:
        cat = classify_action(c)
        label = _HUMAN_CATEGORY.get(cat, f"{cat} precedent")
        if label in seen:
            continue
        seen.add(label)
        rows.append(f"- websearch: {label} — public sample teardown matching "
                    f"claim {c['id']} (refine the query before running)")
        rows.append(f"- reference-library: `{cat}` scenario — "
                    f"`references_recall.py {cat}`, read the hit domain file")
    return rows


FAILURE_ACTIONS = frozenset(("death_verdict_rejected", "top1_reject"))
K_FAILURE_WINDOW = 10          # ledger rows scanned back for failure events
BET_GROUP = "think-bet"        # separates bets from #528 competitor lineage


def recent_failures(ws: Path, k: int = K_FAILURE_WINDOW) -> list[dict]:
    """近 K 条失败事件（新→旧）。kunglao-*.jsonl 全文件 glob 扫描（跨日安全）。"""
    rows: list[dict] = []
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    for p in reversed(logs):
        try:
            lines = p.read_text(encoding="utf-8",
                                errors="replace").splitlines()
        except OSError:
            continue
        for ln in reversed(lines):
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("action") in FAILURE_ACTIONS:
                rows.append({"action": str(row.get("action")),
                             "claim_id": str(row.get("claim") or "")})
                if len(rows) >= k:
                    return rows
    return rows


def bets_owed(ws: Path) -> list[str]:
    """失败 claim 无 think-bet 覆盖 → 欠注名单。"""
    covered = {h.claim_id for h in HypothesisStore(
        ws / "hypotheses").list_all()
        if h.competitor_group == BET_GROUP}
    owed: list[str] = []
    for f in recent_failures(ws):
        cid = f["claim_id"]
        if cid and cid not in covered and cid not in owed:
            owed.append(cid)
    return owed


def file_bet(ws: Path, claim_id: str, statement: str,
             predicted_observation: str):
    """立案可证伪赌注。空 predicted_observation 拒绝——无预测的思考不被
    采纳（文书零奖励的入口面）。"""
    if not (statement and statement.strip()):
        raise ValueError("bet statement must not be empty")
    if not (predicted_observation and predicted_observation.strip()):
        raise ValueError(
            "predicted_observation must not be empty — a bet without a "
            "falsifiable prediction is narrative, not thinking (#711)")
    store = HypothesisStore(ws / "hypotheses")
    n = 1
    existing = {x.id for x in store.list_all()}
    while f"H-{n:03d}" in existing:
        n += 1
    h = store.create(Hypothesis(
        id=f"H-{n:03d}", claim_id=claim_id, competitor_group=BET_GROUP,
        candidates=[], status="open",
        predicted_observation=predicted_observation.strip(),
        body=statement.strip()))
    try:
        import kunglao_log
        kunglao_log.emit(ws, "orchestrator", "bet_filed", claim=claim_id,
                         artifact=f"hypotheses/{h.id}.md",
                         hypothesis_ref=h.id,
                         detail=predicted_observation.strip())
    except Exception:  # noqa: BLE001 — advisory emit must never raise
        pass
    return h


def settle_bet(ws: Path, hyp_id: str, outcome: str,
               evidence_id: str | None):
    """结算赌注：confirmed（需 confirming 证据）/ refuted（需 refuting 证据）。
    clawback 留 #823-P4，本批次只记账。"""
    if outcome not in ("confirmed", "refuted"):
        raise ValueError(f"unknown bet outcome: {outcome!r}")
    store = HypothesisStore(ws / "hypotheses")
    h = store.transition(
        hyp_id, outcome,
        refuting_fact_id=evidence_id if outcome == "refuted" else None,
        confirming_fact_id=evidence_id if outcome == "confirmed" else None)
    try:
        import kunglao_log
        kunglao_log.emit(ws, "orchestrator", "bet_settled", claim=h.claim_id,
                         artifact=f"hypotheses/{h.id}.md",
                         hypothesis_ref=h.id,
                         exit=1 if outcome == "confirmed" else 0,
                         detail=f"{outcome} by {evidence_id}")
    except Exception:  # noqa: BLE001 — advisory emit must never raise
        pass
    return h


def _render_artifact(ws: Path, ts: str, digest: tuple[int, int],
                     stall_ticks: int) -> str:
    weights_file = ws / "runs" / "value-weights.yaml"
    weights_note = ("present — weighting applies to rank recalculation"
                    if weights_file.exists() else
                    "absent — neutral weights (every claim weight 1.0)")
    hyp_rows = open_hypothesis_rows(ws) or ["(none open)"]
    idx_lines = facts_index_tail(ws) or ["(no facts yet)"]
    owed = bets_owed(ws)
    search = suggested_searches(ws, stall_ticks) or (
        precedent_rows(ws) if owed else [])
    bet_lines = ([f"  - OWED for {cid}: file a falsifiable bet "
                  f"(file_bet: claim / 含义 / predicted_observation)"
                  for cid in owed] or
                 ["(none — every recent failure has a filed bet)"])
    blocks = [
        f"# THINK {ts} — waiting-period cognitive action (#759 H1)",
        "",
        f"inputs: terminal_facts={digest[0]} · open_claims={digest[1]} · "
        f"stall_ticks={stall_ticks}",
        "(the script guarantees this seat; the THINKING is yours, "
        "orchestrator — fill every `(pending …)` in place)",
        "",
        "## patterns — cross-fact patterns observed this round",
        *[f"  | {ln}" for ln in idx_lines],
        "(pending orchestrator)",
        "",
        "## hypotheses — open list to update / verify / refute",
        *[f"  - {r}" for r in hyp_rows],
        "(pending orchestrator)",
        "",
        "## bets — falsifiable bets owed (#711: 文书零奖励，下注才算思考)",
        *bet_lines,
        "(file via file_bet: statement + predicted_observation; settle via "
        "settle_bet confirmed/refuted with evidence id)",
        "",
        "## value — worth ordering under current value weights",
        f"(weights: {weights_note})",
        "(pending orchestrator)",
    ]
    if search:
        blocks += ["", "## suggested_searches",
                   "(#711 对策：these are the NEXT action, not optional — "
                   "SKILL contract enforces execution)", *search]
    return "\n".join(blocks) + "\n"


def _write_artifact(ws: Path, content: str) -> str:
    base = _utc_compact()
    rel_dir = ws / "runs"
    rel_dir.mkdir(parents=True, exist_ok=True)
    name, k = f".think-{base}.md", 0
    while (rel_dir / name).exists():
        k += 1
        name = f".think-{base}-{k}.md"
    (rel_dir / name).write_text(content, encoding="utf-8")
    return f"runs/{name}"


def maybe_think(ws: Path) -> dict:
    """The seat entry point. Returns one JSON-shaped dict; never raises on
    handled input."""
    ws = Path(ws)
    reg = ws / "claim-register.yaml"
    if not reg.exists():
        return {"waiting": False, "reason": "no-register", "artifact": None}
    n = dispatchable_count(ws)
    if n is None:
        return {"waiting": False, "reason": "ranking-undecidable", "artifact": None}
    if n > 0:
        return {"waiting": False, "reason": f"{n}-dispatchable-actions",
                "artifact": None}
    digest = progress_digest(ws)
    stall = update_stall_state(ws, digest)
    owed = bets_owed(ws)
    art = _write_artifact(ws, _render_artifact(ws, _utc_compact(), digest,
                                               stall))
    return {"waiting": True, "reason": "no-dispatchable-action",
            "artifact": art, "terminal_facts": digest[0],
            "open_claims": digest[1], "stall_ticks": stall,
            "bets_owed": owed, "bet_required": bool(owed)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="think_seat.py",
                                 description="waiting-period THINK seat")
    ap.add_argument("workspace", help="workspace root")
    args = ap.parse_args(argv)
    try:
        res = maybe_think(args.workspace)
    except Exception as exc:  # noqa: BLE001 — advisory face: rc stays 0
        res = {"waiting": False, "reason": "seat-crashed", "error": str(exc),
               "artifact": None}
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
