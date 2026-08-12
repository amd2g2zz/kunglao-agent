#!/usr/bin/env python3
"""priority.py - kunglao-agent greedy best-first dispatch ranker (DESIGN section 8.5).

This is the SINGLE SANCTIONED dispatch ranker (v1.9.29, R4). priority_ratio.py
is M1-internal (reachable only via kunglao-decide); the hook audit
(worker_budget.py) and pulse (worker_pulse.py) consume THIS module's output.
Makes "greedy best-first" a REAL code-computed heuristic (not LLM free judgment).
Each round the orchestrator runs this, then dispatches the top-ranked claim(s)
within the <=3-workers cap and tier gate.

Priority(C) = w_value*value + w_leverage*leverage + w_cheap*cheapness + w_novel*novelty
  value     : 1.0 if answers_question set (PRIMARY); 0.6 if competitor_group set; else 0.2
  leverage  : v2 sigmoid-based reward (see _leverage_v2 below) - captures
              transitive unlock potential, not just direct dependents
  cheapness : next evidence-tier cost: T1=1.0 T2=0.5 T3=0.2 (cheaper first)
  novelty   : 1/(1+promotion_attempts) - fresh claims before re-tries
Default weights value=0.4 leverage=0.3 cheapness=0.2 novelty=0.1; override via
task_spec.priority_weights or env PRIORITY_WEIGHTS=v,l,c,n.

LEVERAGE V2 (User pain point: "no value selection ability - some work unlocks
most of the rest"). The original min(1, open_deps/3) saturates at 3 dependents
and loses cumulative unlock effect. V2 uses:
  - direct_count: len(claims that depend on C)
  - transitive_count: len(claims transitively reachable from C)
  - gateway_bonus: +0.5 if direct_count >= 2 (claim is a structural bottleneck)
  - score = sigmoid((transitive_count - 3) / 4) + gateway_bonus, clipped [0, 1]
This rewards claims that unlock 5+ downstream claims without overflowing the
weight budget. A claim unlocking 8 transitively gets leverage ~ 0.82 vs old 1.0
(cap) but the math now reflects the cumulative value.

A claim is DISPATCHABLE when: status non-terminal AND promotion_attempts<3 AND
every depends_on[C] is terminal. The tier gate (worker_budget.check_tier_gate)
still decides if the next tier is currently ALLOWED - shown per-claim.

Usage:
  python scripts/priority.py [workspace]          # human table
  python scripts/priority.py [workspace] --json   # machine-readable
  python scripts/priority.py [workspace] --leverage-v1  # legacy direct-cap formula
Workspace defaults to $PWD/malware-analysis-workspace if it has claim-register.yaml, else $PWD.
"""
from __future__ import annotations
import json, math, os, sys
from pathlib import Path
import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES

NEXT_TIER_CHEAP = {0: 1.0, 1: 0.5, 2: 0.2}
DEFAULT_WEIGHTS = {'value': 0.4, 'leverage': 0.3, 'cheapness': 0.2, 'novelty': 0.05, 'outcome': 0.05}


def _load(p):
    return (yaml.safe_load(p.read_text(encoding='utf-8')) or {}) if p.exists() else {}


def _resolve_ws(arg):
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / 'malware-analysis-workspace'
    return sub if (sub / 'claim-register.yaml').exists() else cwd


def _is_open(c):
    # v1.9.16: IN_PROGRESS = dispatched to a worker, NOT dispatchable (was
    # treated as open -> priority re-recommended in-flight claims -> orchestrator
    # saw a full queue, dispatched nothing, left slots empty).
    return c.get('status') not in TERMINAL and c.get('status') not in IN_PROGRESS_STATUSES


def _transitive_unlocks(cid, depends_on, by_id, open_set):
    """Return set of all OPEN claim IDs transitively UNLOCKED by cid (downstream).

    Walks the reverse graph: claims whose depends_on list contains cid (directly),
    then their downstream, etc. Excludes cid itself.
    """
    # Build reverse map: claim -> [claims that depend on it]
    rev = {}
    for child, parents in depends_on.items():
        for p in (parents or []):
            rev.setdefault(p, []).append(child)

    seen = set()
    stack = list(rev.get(cid, []) or [])
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in open_set or cur == cid:
            continue
        seen.add(cur)
        # Recurse: claims that depend on cur
        for next_child in rev.get(cur, []) or []:
            if next_child not in seen and next_child in open_set and next_child != cid:
                stack.append(next_child)
    return seen


def _leverage_v2(cid, depends_on, by_id, open_set):
    """Sigmoid-based leverage capturing cumulative unlock potential.

    direct_count: claims whose depends_on list contains cid (i.e. cid unblocks them)
    transitive_count: open claims transitively reachable DOWNSTREAM from cid
    gateway_bonus: +0.5 if direct_count >= 2 (structural pinch point)
    """
    # Build reverse: claim -> children that depend on it
    rev = {}
    for child, parents in depends_on.items():
        for p in (parents or []):
            rev.setdefault(p, []).append(child)

    direct = [ch for ch in rev.get(cid, []) or [] if ch in by_id and _is_open(by_id[ch])]
    direct_count = len(direct)
    reachable = _transitive_unlocks(cid, depends_on, by_id, open_set)
    transitive_count = len(reachable)
    sig = 1.0 / (1.0 + math.exp(-(transitive_count - 3) / 4.0))
    gw = 0.5 if direct_count >= 2 else 0.0
    score = sig + gw
    return min(1.0, max(0.0, score)), direct_count, transitive_count


def _leverage_v1(cid, depends_on, by_id):
    """Original leverage: min(1, direct/3). Kept for backward compat."""
    rev = {}
    for child, parents in depends_on.items():
        for p in (parents or []):
            rev.setdefault(p, []).append(child)
    open_deps = [ch for ch in rev.get(cid, []) if _is_open(by_id.get(ch, {'status': 'OPEN'}))]
    return min(1.0, len(open_deps) / 3.0), len(open_deps), 0


def rank_claims(reg, deps, weights, leverage_v2=True, ws=None):
    claims = (reg or {}).get('claims', []) or []
    by_id = {c.get('id'): c for c in claims if c.get('id')}
    depends_on = (deps or {}).get('depends_on', {}) or {}
    open_set = {cid for cid, c in by_id.items() if _is_open(c)}
    terminal_ids = {cid for cid, c in by_id.items() if not _is_open(c)}

    # v1.9.6: failure-blocked claims (failed attempt, no current failure_analysis)
    # are NOT dispatchable — the failure_analysis_gate must be satisfied first.
    # Mirrors convergence_check.py so the two tools never contradict.
    failure_blocked_ids = set()
    if ws is not None:
        try:
            import failure_analysis_gate as fag
            failure_blocked_ids = {b["claim_id"] for b in fag.scan_workspace(Path(ws)) if b.get("state") == "BLOCKED"}
        except (ImportError, NameError):
            pass

    # v1.9.30: per-claim OUTCOME history from verification ledger (#122)
    outcome_scores = {}
    if ws is not None:
        try:
            sys.path.insert(0, str(Path(ws).parent / "scripts"))
            from outcome_capture import read_outcome_rows, aggregate_reward
            sys.path.pop(0)
            all_rows = read_outcome_rows(Path(ws))
            for r in all_rows:
                cid = r.get("claim_id", "")
                result = r.get("result", "").strip().upper()
                score = {"PASS": 1.0, "CONFIRMED": 1.0, "PARTIAL": 0.5, "UNVERIFIED": 0.5}.get(result, 0.0)
                outcome_scores.setdefault(cid, []).append(score)
        except Exception:
            pass

    rows = []
    for c in claims:
        cid = c.get('id')
        if not cid or not _is_open(c):
            continue
        if int(c.get('promotion_attempts', 0)) >= 3:
            continue
        if cid in failure_blocked_ids:
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal_ids for p in parents):
            continue
        if c.get('answers_question'):
            value = 1.0
        elif c.get('competitor_group'):
            value = 0.6
        else:
            value = 0.2
        if leverage_v2:
            leverage, direct_n, transit_n = _leverage_v2(cid, depends_on, by_id, open_set)
        else:
            leverage, direct_n, _ = _leverage_v1(cid, depends_on, by_id)
            transit_n = 0
        eta = int(c.get('evidence_tier_attempted', 0))
        cheapness = NEXT_TIER_CHEAP.get(eta, 0.1)
        next_tier = min(eta + 1, 3)
        novelty = 1.0 / (1 + int(c.get('promotion_attempts', 0)))
        claim_outcome = outcome_scores.get(cid, [])
        outcome_factor = sum(claim_outcome) / len(claim_outcome) if claim_outcome else 0.0
        w_outcome = weights.get('outcome', 0.0)
        score = (weights['value'] * value + weights['leverage'] * leverage +
                 weights['cheapness'] * cheapness + weights['novelty'] * novelty +
                 w_outcome * outcome_factor)
        rows.append({'id': cid, 'score': round(score, 3), 'value': value,
                     'leverage': round(leverage, 2), 'leverage_direct': direct_n,
                     'leverage_transitive': transit_n,
                     'cheapness': cheapness,
                     'novelty': round(novelty, 2), 'next_tier': next_tier,
                     'outcome': round(outcome_factor, 2),
                     'statement': c.get('statement', '') or ''})
    rows.sort(key=lambda r: r['score'], reverse=True)
    return rows


def gate_allows(reg, next_tier):
    if next_tier <= 1:
        return True
    threshold = next_tier - 1
    for c in (reg or {}).get('claims', []) or []:
        if c.get('status') in TERMINAL:
            continue
        if int(c.get('evidence_tier_attempted', 0)) < threshold:
            return False
    return True


def _weights(tspec):
    w = dict(DEFAULT_WEIGHTS)
    pw = (tspec or {}).get('priority_weights')
    if pw:
        w.update({k: float(v) for k, v in pw.items()})
    envw = os.environ.get('PRIORITY_WEIGHTS')
    if envw:
        try:
            parts = dict(zip(['value', 'leverage', 'cheapness', 'novelty'],
                             [float(x) for x in envw.split(',')]))
            w.update(parts)
        except Exception:
            pass
    return w


def main():
    args = [a for a in sys.argv[1:] if a not in ('--json', '--leverage-v1')]
    as_json = '--json' in sys.argv
    leverage_v2 = '--leverage-v1' not in sys.argv
    ws = _resolve_ws(args[0] if args else None)
    reg = _load(ws / 'claim-register.yaml')
    deps = _load(ws / 'claim_deps.yaml')
    tspec = _load(ws / 'task_spec.yaml')
    weights = _weights(tspec)
    rows = rank_claims(reg, deps, weights, leverage_v2=leverage_v2, ws=ws)
    total_open = sum(1 for c in (reg or {}).get('claims', []) or [] if _is_open(c))
    if as_json:
        out = {'workspace': str(ws), 'weights': weights, 'n_open': total_open,
               'n_dispatchable': len(rows), 'leverage_v2': leverage_v2,
               'dispatchable': rows}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    lev_label = 'v2 (sigmoid, transitive)' if leverage_v2 else 'v1 (direct cap)'
    print(f'kunglao-agent best-first dispatch queue  ({total_open} open, {len(rows)} dispatchable)  leverage={lev_label}')
    print(f'weights: value={weights["value"]} leverage={weights["leverage"]} '
          f'cheapness={weights["cheapness"]} novelty={weights["novelty"]}')
    if not rows:
        print('(no dispatchable claims - blocked by open deps, promotion cap>=3, or none open)')
        return 0
    hdr = f'{"rk":>3} {"claim":<7} {"score":>5} {"val":>4} {"lever":>5} {"direct":>6} {"transit":>7} {"cheap":>5} {"novel":>5} {"next":>4} {"gate":>5}  statement'
    print(hdr)
    print('-' * len(hdr))
    for i, r in enumerate(rows, 1):
        allowed = 'ok' if gate_allows(reg, r['next_tier']) else 'gate'
        d = r.get('leverage_direct', 0)
        t = r.get('leverage_transitive', 0)
        print(f'{i:>3} {r["id"]:<7} {r["score"]:>5} {r["value"]:>4} {r["leverage"]:>5} '
              f'{d:>6} {t:>7} {r["cheapness"]:>5} {r["novelty"]:>5} T{r["next_tier"]:<3} {allowed:>5}  {r["statement"][:60]}')
    print('\ndispatch top claim(s) within <=3 workers + tier gate; deviate only with a recorded reason.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
