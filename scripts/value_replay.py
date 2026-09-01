#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""value_replay.py — P1 offline replay settlement (#823, AB-VALUE arm N).

Replays HISTORICAL workspaces to produce the N-arm's starting priors:
  1. z_self relabeling — first-pass completion over four mechanical channels
     (verify-thrash reopen / gate interceptions / notes-due compensation /
     human turns). Channels absent from historical artifacts are reported
     `available: false` instead of guessed; the experiment runner (B5)
     feeds them via the `extra` record so A1 and B5 share this function.
  2. Bucket priors — runs/value-priors.yaml keyed `<depth>|<tool-family>`
     with P(z_self=1), token stats (None until token telemetry exists —
     the #818 gap means historical workspaces carry no token records).
  3. (score, outcome) pairs — the joinable export for Platt calibration.
     Scores are POST-HOC (final register state): recorded as such in the
     receipt, never presented as dispatch-time scores.
  4. Reward-table replay validation — a known-bad workspace must score
     below known-good ones or P1 is BLOCKED from feeding A4 (plan gate).

Reward scoring is evidence-gated (the #819 lesson: PROVEN without a
passing verify record is bookkeeping, not evidence): a claim earns +10
only when its final status is PROVEN/VERIFIED AND its latest verify row
is VERIFIED; REFUTED claws back −10; unsupported PROVEN scores 0 and is
counted in `unsupported_proven`.

Usage:
  python value_replay.py <ws>... [--priors-out F] [--pairs-out F]
                         [--validate-bad WS]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

import priority_ratio

SCHEMA = "kunglao-value-priors/1"
REWARD_PROVEN = 10.0
REWARD_REFUTED = -10.0

# ledger interception faces (event_taxonomy.EMIT_ACTIONS subset) — any row
# with one of these actions means a gate had to stop the loop mid-flight
GATE_FACES = frozenset({
    "top1_reject", "capability_reject", "must_stop", "must_ask",
    "ladder_required", "death_verdict_rejected", "failure_blocked",
    "write_blocked", "ask_back",
})

_TERMINAL_PASS = {"PROVEN", "VERIFIED"}


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def verify_rows(ws: Path) -> list[dict]:
    """runs/verify-*.json rows, filename order (= time order for the
    timestamped producer names). Unparsable rows are skipped."""
    rows: list[dict] = []
    vdir = Path(ws) / "runs"
    if not vdir.is_dir():
        return rows
    for p in sorted(vdir.glob("verify-*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _overall(row: dict) -> str:
    return str(row.get("overall") or "").strip().upper()


def detect_reopen(ws: Path) -> list[str]:
    """Fact ids whose verify stream shows REJECTED followed by a later
    VERIFIED — evidence the claim was refuted and reopened for rework."""
    by_fact: dict[str, list[str]] = {}
    for row in verify_rows(ws):
        fid = str(row.get("fact_id") or "")
        if fid and _overall(row):
            by_fact.setdefault(fid, []).append(_overall(row))
    thrashed = []
    for fid, verdicts in by_fact.items():
        seen_reject = False
        for v in verdicts:
            if v == "REJECTED":
                seen_reject = True
            elif v == "VERIFIED" and seen_reject:
                thrashed.append(fid)
                break
    return sorted(thrashed)


def gate_interceptions(ws: Path) -> list[str]:
    """Sorted unique interception faces present in the kunglao_log stream."""
    faces: Counter = Counter()
    logs = Path(ws) / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("action") in GATE_FACES:
                    faces[str(row["action"])] += 1
    return sorted(faces)


def z_self(ws: Path, extra: dict | None = None) -> dict:
    """First-pass completion label. extra (experiment runner, B5) carries
    counts of events the historical artifacts cannot show: notes_due /
    human_turns; absent keys stay `available: false`."""
    extra = extra or {}
    faces = gate_interceptions(ws)
    channels = {
        "reopen": _channel(True, bool(detect_reopen(ws)), detect_reopen(ws)),
        "gate_blocked": _channel(True, bool(faces), faces),
    }
    for name in ("notes_due", "human_turns"):
        if name in extra:
            channels[name] = _channel(True, int(extra[name]) > 0, [])
        else:
            channels[name] = _channel(False, False, [])
    available = [c for c in channels.values() if c["available"]]
    clean = all(not c["triggered"] for c in available)
    return {"z_self": 1 if clean else 0,
            "partial": any(not c["available"] for c in channels.values()),
            "channels": channels}


def _channel(available: bool, triggered: bool, evidence: list) -> dict:
    return {"available": available, "triggered": triggered, "evidence": evidence}


def _index_rows(ws: Path) -> list[tuple[str, str, str]]:
    """facts/_INDEX.md rows → (fact_id, status, claim_id)."""
    index = Path(ws) / "facts" / "_INDEX.md"
    if not index.exists():
        index = Path(ws) / "_INDEX.md"
    out: list[tuple[str, str, str]] = []
    if not index.exists():
        return out
    try:
        text = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[0].startswith("F"):
            out.append((parts[0], parts[1].upper(), parts[2]))
    return out


def _latest_support(ws: Path) -> dict[str, bool]:
    """fact_id → its LATEST verify row is VERIFIED."""
    latest: dict[str, str] = {}
    for row in verify_rows(ws):
        fid = str(row.get("fact_id") or "")
        if fid and _overall(row):
            latest[fid] = _overall(row)
    return {fid: v == "VERIFIED" for fid, v in latest.items()}


def ws_score(ws: Path) -> dict:
    """Evidence-gated reward total (#823 reward table, replay form)."""
    support = _latest_support(ws)
    per_claim: dict[str, float] = {}
    unsupported = 0
    for fid, status, cid in _index_rows(ws):
        if not cid:
            continue
        if status in _TERMINAL_PASS:
            if support.get(fid):
                per_claim[cid] = per_claim.get(cid, 0.0) + REWARD_PROVEN
            else:
                unsupported += 1
        elif status == "REFUTED":
            per_claim[cid] = per_claim.get(cid, 0.0) + REWARD_REFUTED
    return {"total": round(sum(per_claim.values()), 3),
            "unsupported_proven": unsupported,
            "per_claim": {k: round(v, 3) for k, v in sorted(per_claim.items())}}


def replay_validation_pass(good: list[Path], bad: list[Path]) -> bool:
    """Replay gate: mean(good ws score) > mean(bad ws score), else P1 is
    blocked from feeding A4 (plan Task A1)."""
    if not good or not bad:
        return False
    g = sum(ws_score(Path(w))["total"] for w in good) / len(good)
    b = sum(ws_score(Path(w))["total"] for w in bad) / len(bad)
    return g > b


def _depth(ws: Path) -> str:
    spec = _read_yaml(Path(ws) / "task_spec.yaml")
    return str(spec.get("depth") or "unknown").strip().lower()


def dominant_family(ws: Path) -> str:
    fams: Counter = Counter()
    logs = Path(ws) / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("tool"):
                    fams |= Counter(priority_ratio.tool_families_from_tools([row["tool"]]))
    return fams.most_common(1)[0][0] if fams else "none"


def build_priors(ws_list: list[Path]) -> dict:
    """Bucket priors keyed `<depth>|<tool-family>`. Token stats stay None —
    historical workspaces carry no token telemetry (#818 gap); the
    experiment runner fills them once B3 exists."""
    buckets: dict[str, dict] = {}
    for ws in ws_list:
        ws = Path(ws)
        key = f"{_depth(ws)}|{dominant_family(ws)}"
        z = z_self(ws)
        b = buckets.setdefault(key, {"n": 0, "p_complete": 0.0,
                                     "token_median": None, "token_variance": None,
                                     "ws_ids": []})
        b["n"] += 1
        b["p_complete"] += z["z_self"]
        b["ws_ids"].append(ws.name)
    for b in buckets.values():
        b["p_complete"] = round(b["p_complete"] / b["n"], 4)
    return {"schema": SCHEMA,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "buckets": buckets}


def score_outcome_pairs(ws_list: list[Path]) -> list[dict]:
    """(ws, claim_id, action_cat, score, outcome) rows for Platt fitting.

    outcome = claim reached PROVEN/VERIFIED with verify support (the same
    evidence gate as ws_score). score = post-hoc priority_ratio score for
    OPEN claims; terminal claims score 0.0 here (they left the queue) —
    the receipt must state POST-HOC whenever these pairs are consumed."""
    pairs: list[dict] = []
    for ws in ws_list:
        ws = Path(ws)
        reg = _read_yaml(ws / "claim-register.yaml")
        claims = reg.get("claims") or []
        deps = _read_yaml(ws / "claim_deps.yaml")
        support = _latest_support(ws)
        supported_claims = {cid for fid, status, cid in _index_rows(ws)
                            if status in _TERMINAL_PASS and support.get(fid)}
        ranked = {a.claim_id: a.score
                  for a in priority_ratio.priority_ratio(
                      claims, deps, priority_ratio.EvidenceView.from_workspace(ws))}
        for c in claims:
            cid = str(c.get("id") or "")
            if not cid:
                continue
            pairs.append({
                "ws": ws.name,
                "claim_id": cid,
                "action_cat": priority_ratio.classify_action(c),
                "score": round(float(ranked.get(cid, 0.0)), 4),
                "outcome": 1 if cid in supported_claims else 0,
            })
    return pairs


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="value_replay.py",
                                 description="P1 offline replay settlement (#823)")
    ap.add_argument("workspaces", nargs="+", help="historical workspace roots")
    ap.add_argument("--priors-out", default=None, help="write value-priors YAML here")
    ap.add_argument("--pairs-out", default=None, help="write (score,outcome) JSONL here")
    ap.add_argument("--validate-bad", default=None,
                    help="known-bad workspace; its mean score must sit below "
                         "the good list or the replay gate FAILS (exit 3)")
    args = ap.parse_args(argv)
    ws_list = [Path(w) for w in args.workspaces]
    for ws in ws_list:
        if not ws.is_dir():
            print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
            return 64
    if args.validate_bad:
        bad = Path(args.validate_bad)
        if not replay_validation_pass(ws_list, [bad]):
            print("REPLAY GATE FAILED: reward table does not separate "
                  f"good {ws_list} from bad {bad} — P1 blocked from A4",
                  file=sys.stderr)
            return 3
        print(f"replay gate PASS (good mean > bad mean: {bad})")
    priors = build_priors(ws_list)
    if args.priors_out:
        Path(args.priors_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.priors_out).write_text(
            yaml.safe_dump(priors, allow_unicode=True, sort_keys=True), encoding="utf-8")
    if args.pairs_out:
        Path(args.pairs_out).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.pairs_out).open("w", encoding="utf-8") as f:
            for row in score_outcome_pairs(ws_list):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(priors, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
