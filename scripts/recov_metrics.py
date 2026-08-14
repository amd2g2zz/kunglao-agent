# -*- coding: utf-8 -*-
"""recov_metrics.py — symbol/type recovery quality metrics (issue #309).

Absorbed idea: Dryxio/auto-re-agent metrics.py:71-218, re-implemented for the
kunglao eval harness so eval can measure ANALYSIS QUALITY (name/type
recovery), not only oracle correctness.

Naming accuracy (per recovered function, greedy global assignment — a
recovered name or an expected function is never reused):
    exact    1.0  recovered == primary expected name
    same-set 0.9  recovered in the expected synonym group
    superset 0.8  recovered name is a superset of an expected name
                  (e.g. "decrypt_0x401000" vs "decrypt")
    recall   0.7  the function was recovered but the name has no affinity
    (cross-function candidates require affinity; same-function pairs without
     affinity fall to the recall tier)
    naming_score = sum(pair tiers) / len(expected)

Type accuracy (per function): 0.4 return exact + 0.3 param count exact
+ 0.3 param types exact-ratio (positions equal / total; 0 when counts differ).
"""
from __future__ import annotations

EXACT = 1.0
SAME_SET = 0.9
SUPERSET = 0.8
RECALL_TIER = 0.7

RETURN_W = 0.4
COUNT_W = 0.3
PARAMS_W = 0.3

NAMING_PASS_THRESHOLD = 0.75
TYPE_PASS_THRESHOLD = 0.75


def _pair_tier(recovered_name: str, expected_names: list[str]) -> float | None:
    """Affinity tier between one recovered name and one expected group;
    None means no affinity (no cross-function candidate)."""
    rec = str(recovered_name or "")
    names = [str(n) for n in (expected_names or [])]
    if not names:
        return None
    if rec == names[0]:
        return EXACT
    if rec in names[1:]:
        return SAME_SET
    if any(rec != n and n and n in rec for n in names):
        return SUPERSET
    return None


def naming_score(expected: dict, recovered: dict) -> dict:
    """Greedy no-reuse matching of recovered names to expected functions.

    expected:  {func: [primary_name, synonym, ...]}
    recovered: {func: name}
    """
    candidates: list[tuple[float, str, str]] = []
    for r_func, r_name in recovered.items():
        for e_func, e_names in expected.items():
            tier = _pair_tier(r_name, e_names)
            if tier is not None:
                candidates.append((tier, r_func, e_func))
            elif r_func == e_func:
                candidates.append((RECALL_TIER, r_func, e_func))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))  # deterministic tiebreak

    used_r: set[str] = set()
    used_e: set[str] = set()
    pairings: list[dict] = []
    total = 0.0
    for tier, r_func, e_func in candidates:
        if r_func in used_r or e_func in used_e:
            continue
        used_r.add(r_func)
        used_e.add(e_func)
        pairings.append({"recovered_func": r_func, "expected_func": e_func,
                         "tier": tier})
        total += tier

    n_exp = len(expected)
    n_rec = len(recovered)
    return {
        "score": round(total / n_exp, 4) if n_exp else 0.0,
        "matched": len(pairings),
        "expected": n_exp,
        "recovered": n_rec,
        "precision": round(len(pairings) / n_rec, 4) if n_rec else 0.0,
        "recall": round(len(pairings) / n_exp, 4) if n_exp else 0.0,
        "pairings": pairings,
    }


def naming_dimension(expected: dict, recovered: dict) -> dict:
    """Eval-harness dimension wrapper (pass/fail + score + detail)."""
    s = naming_score(expected, recovered)
    return {"pass": s["score"] >= NAMING_PASS_THRESHOLD,
            "score": s["score"],
            "matched": s["matched"], "expected": s["expected"],
            "detail": (f"naming_quality score={s['score']} matched={s['matched']}/"
                       f"{s['expected']} (exact {EXACT}/same-set {SAME_SET}/"
                       f"superset {SUPERSET}/recall {RECALL_TIER})")}


def _type_per_function(exp: dict, rec: dict) -> float:
    ret = 1.0 if (exp.get("return") or "") == (rec.get("return") or "") else 0.0
    ep = exp.get("params") or []
    rp = rec.get("params") or []
    cnt = 1.0 if len(ep) == len(rp) else 0.0
    if ep and rp:
        ratio = (sum(1 for a, b in zip(ep, rp) if (a or "") == (b or "")) / len(ep)
                 if cnt else 0.0)
    elif cnt:
        ratio = 1.0  # both empty: vacuously perfect param recovery
    else:
        ratio = 0.0
    return RETURN_W * ret + COUNT_W * cnt + PARAMS_W * ratio


def type_score(expected: dict, recovered: dict) -> dict:
    """0.4 return + 0.3 count + 0.3 params, averaged over expected functions."""
    per: dict[str, float] = {}
    for f, e in expected.items():
        rec = recovered.get(f)
        per[f] = _type_per_function(e, rec) if rec is not None else 0.0
    score = sum(per.values()) / len(expected) if expected else 0.0
    return {"score": round(score, 4), "per_function": per,
            "expected": len(expected), "matched": sum(1 for f in expected if f in recovered)}


def type_dimension(expected: dict, recovered: dict) -> dict:
    s = type_score(expected, recovered)
    return {"pass": s["score"] >= TYPE_PASS_THRESHOLD,
            "score": s["score"],
            "detail": (f"type_quality score={s['score']} "
                       f"({RETURN_W} return + {COUNT_W} count + {PARAMS_W} params)")}
