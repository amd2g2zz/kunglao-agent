#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_analyze.py — statistics pipeline (B7, #823 AB-VALUE).

Paired two-arm analysis over the runs table. stdlib-only: exact McNemar
(two-sided binomial on discordant pairs), Wilcoxon signed-rank via the
tie-corrected normal approximation (valid at the experiment's n=30),
least-squares slopes for the tuition curve. scipy/duckdb deliberately
NOT added — numerics are equivalent at this n and the plugin stays
dependency-lean (plan deviation, recorded).

Dual-lens rule (plan B4/B7): every success rate is reported BOTH over
all runs and over done-only runs; timeouts keep their tokens/wall rows
(a cap-time run is still a cost datum). Timeout is an independent
column — the timeout RATE per arm is itself a capability signal.

H1-H4 verdicts use the pre-registered thresholds (AB-DESIGN §2); a
negative result is reported, never buried (§10).

Usage: bench_analyze.py <runs.jsonl> --out-dir <dir>
       bench_analyze.py --demo [--seed 7]   (60 synthetic runs)
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

ARMS = ("O", "N")
H4_MARGIN = 0.05        # non-inferiority margin on PQ coverage
H1_RATIO = 0.5          # N zero-output share must halve O's


# ---------- statistics primitives (stdlib) ----------

def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar via the binomial: 2·Σ_{i≤k} C(n,i)/2ⁿ."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1))
    return min(1.0, 2.0 * tail / 2 ** n)


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def wilcoxon_signed_rank(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Returns (p_two_sided, W_plus). Zero diffs dropped; average ranks
    for ties; tie-corrected normal approximation with continuity fix."""
    diffs = [x - y for x, y in zip(xs, ys) if x != y]
    n = len(diffs)
    if n == 0:
        return 1.0, 0.0
    order = sorted(range(n), key=lambda i: abs(diffs[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(diffs[order[j + 1]]) == abs(diffs[order[i]]):
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    mu = n * (n + 1) / 4
    sorted_abs = sorted(abs(d) for d in diffs)
    tie_terms = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_abs[j + 1] == sorted_abs[i]:
            j += 1
        t = j - i + 1
        tie_terms += t ** 3 - t
        i = j + 1
    sigma2 = n * (n + 1) * (2 * n + 1) / 24 - tie_terms / 48
    if sigma2 <= 0:
        return 1.0, w_plus
    z = (w_plus - mu - 0.5 * (1 if w_plus > mu else -1)) / math.sqrt(sigma2)
    return min(1.0, 2.0 * _norm_sf(abs(z))), w_plus


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope; 0.0 when degenerate."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def _median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


# ---------- aggregation ----------

def summarize(rows: list[dict]) -> dict:
    """Per-arm stats + paired counts. Contaminated rows stay in the
    counts but are flagged (analysis re-runs without them are cheap)."""
    out: dict = {"pairs": 0, "arms": {a: {} for a in ARMS}}
    by_sample: dict[str, set] = {}
    for r in rows:
        by_sample.setdefault(r["sample"], set()).add(r["arm"])
    out["pairs"] = sum(1 for v in by_sample.values() if v == set(ARMS))
    for a in ARMS:
        rs = [r for r in rows if r.get("arm") == a]
        n = len(rs)
        done = [r for r in rs if not r.get("timeout")]
        out["arms"][a] = {
            "n": n,
            "success_rate": (sum(1 for r in rs if r.get("success")) / n)
            if n else 0.0,
            "success_rate_done_only": (sum(1 for r in done if r.get("success"))
                                       / len(done)) if done else 0.0,
            "timeout_rate": (sum(1 for r in rs if r.get("timeout")) / n)
            if n else 0.0,
            "token_median": _median([r.get("tokens", 0) for r in rs]),
            "token_mean": (sum(r.get("tokens", 0) for r in rs) / n) if n else 0.0,
            "wall_median": _median([r.get("wall_s", 0) for r in rs]),
            "z_self_rate": (sum(1 for r in rs if r.get("z_self")) / n) if n else 0.0,
            "pq_mean": (sum(r.get("pq_score", 0.0) for r in rs) / n) if n else 0.0,
            "zero_output_mean": (sum(r.get("zero_output_share") or 0.0
                                     for r in rs) / n) if n else 0.0,
            "contaminated": sum(1 for r in rs if r.get("contaminated")),
        }
    return out


def _paired(rows: list[dict], field: str) -> tuple[list[float], list[float]]:
    """(O values, N values) over complete pairs, sample order stable."""
    by_sample: dict[str, dict[str, float]] = {}
    for r in rows:
        by_sample.setdefault(r["sample"], {})[r["arm"]] = r.get(field) or 0
    pairs = [(v["O"], v["N"]) for v in by_sample.values()
             if set(v) == set(ARMS)]
    return ([o for o, _ in pairs], [n for _, n in pairs])


def hypotheses(rows: list[dict]) -> dict:
    """H1-H4 with pre-registered thresholds. Negative results report as
    FAIL, missing data as UNDECIDABLE — never silent."""
    out: dict[str, dict] = {}
    zo_o, zo_n = _paired(rows, "zero_output_share")
    if zo_o:
        p, _ = wilcoxon_signed_rank(zo_o, zo_n)
        mean_o = sum(zo_o) / len(zo_o)
        mean_n = sum(zo_n) / len(zo_n)
        out["H1"] = {"verdict": "PASS" if mean_n < mean_o * H1_RATIO else "FAIL",
                     "p": round(p, 4), "test": "wilcoxon",
                     "mean_O": round(mean_o, 4),
                     "mean_N": round(mean_n, 4),
                     "threshold": f"mean_N < mean_O × {H1_RATIO}"}
    else:
        out["H1"] = {"verdict": "UNDECIDABLE", "p": None}

    by_stratum: dict[str, list[dict]] = {}
    for r in rows:
        by_stratum.setdefault(r["stratum"], []).append(r)
    slopes = {}
    for st, rs in by_stratum.items():
        for a in ARMS:
            arm_rows = sorted([r for r in rs if r["arm"] == a],
                              key=lambda r: r.get("seq_in_stratum", 0))
            slopes[f"{st}/{a}"] = round(_slope(
                [float(r.get("seq_in_stratum", 0)) for r in arm_rows],
                [float(r.get("tokens", 0)) for r in arm_rows]), 3)
    n_slopes = [v for k, v in slopes.items() if k.endswith("/N")]
    out["H2"] = {"verdict": "PASS" if n_slopes and all(
        s < 0 for s in n_slopes) else "FAIL",
        "slopes": slopes}

    z_o, z_n = _paired(rows, "z_self")
    if z_o:
        b = sum(1 for o, nn in zip(z_o, z_n) if not o and nn)
        c = sum(1 for o, nn in zip(z_o, z_n) if o and not nn)
        p = mcnemar_exact(b, c)
        rate_o = sum(z_o) / len(z_o)
        rate_n = sum(z_n) / len(z_n)
        out["H3"] = {"verdict": "PASS" if rate_n >= rate_o else "FAIL",
                     "p": round(p, 4), "test": "McNemar",
                     "rate_O": round(rate_o, 4), "rate_N": round(rate_n, 4),
                     "discordant": {"O_pass_N_fail": c, "O_fail_N_pass": b}}
    else:
        out["H3"] = {"verdict": "UNDECIDABLE", "p": None}

    pq_o, pq_n = _paired(rows, "pq_score")
    if pq_o:
        mean_o = sum(pq_o) / len(pq_o)
        mean_n = sum(pq_n) / len(pq_n)
        out["H4"] = {"verdict": "PASS" if mean_n >= mean_o - H4_MARGIN
                     else "FAIL",
                     "mean_O": round(mean_o, 4), "mean_N": round(mean_n, 4),
                     "margin": H4_MARGIN}
    else:
        out["H4"] = {"verdict": "UNDECIDABLE", "p": None}
    return out


# ---------- report ----------

def format_report(stats: dict, verdicts: dict) -> str:
    lines = ["# AB-VALUE run analysis", ""]
    lines.append(f"pairs: {stats['pairs']}")
    for a in ARMS:
        s = stats["arms"].get(a, {})
        lines.append(
            f"- {a}: n={s.get('n', 0)} success={s.get('success_rate', 0):.3f} "
            f"(done-only {s.get('success_rate_done_only', 0):.3f}) "
            f"timeout={s.get('timeout_rate', 0):.3f} "
            f"tokens(med)={s.get('token_median', 0):.0f} "
            f"z_self={s.get('z_self_rate', 0):.3f} "
            f"pq={s.get('pq_mean', 0):.3f}")
    lines.append("")
    lines.append("Hypotheses (pre-registered thresholds):")
    for h in ("H1", "H2", "H3", "H4"):
        v = verdicts.get(h, {"verdict": "UNDECIDABLE", "p": None})
        p = f" p={v['p']}" if v.get("p") is not None else ""
        detail = json.dumps({k: val for k, val in v.items()
                             if k not in ("verdict", "p")},
                            ensure_ascii=False)
        lines.append(f"- {h}: {v['verdict']}{p} {detail}")
    lines.append("")
    lines.append("Negative results are reported, never buried (AB-DESIGN §10).")
    return "\n".join(lines) + "\n"


def run_demo(seed: int = 7) -> dict:
    """60 deterministic synthetic runs (30 pairs, 4 strata) with a built-in
    N-arm effect — the self-check for the whole pipeline."""
    rng = random.Random(seed)
    rows: list[dict] = []
    strata = [("S1", 8), ("S2", 7), ("S3", 8), ("S4", 7)]
    for st, count in strata:
        for i in range(count):
            base = rng.randrange(80_000, 160_000)
            o_tokens = base + rng.randrange(-5_000, 5_000)
            n_tokens = int(base * (0.72 - 0.02 * i)) + rng.randrange(-4_000, 4_000)
            rows.append({
                "sample": f"{st}-s{i}", "stratum": st, "seq_in_stratum": i,
                "arm": "O", "success": rng.random() < 0.5,
                "partial_score": round(rng.random() * 0.4 + 0.3, 3),
                "z_self": int(rng.random() < 0.45), "tokens": o_tokens,
                "wall_s": rng.randrange(14_000, 22_000), "timeout": False,
                "zero_output_share": round(0.35 + rng.random() * 0.15, 3),
                "stall_s": rng.randrange(0, 900),
                "pq_score": round(0.6 + rng.random() * 0.25, 3),
                "contaminated": False})
            rows.append({
                "sample": f"{st}-s{i}", "stratum": st, "seq_in_stratum": i,
                "arm": "N", "success": rng.random() < 0.7,
                "partial_score": round(rng.random() * 0.3 + 0.5, 3),
                "z_self": int(rng.random() < 0.65), "tokens": n_tokens,
                "wall_s": rng.randrange(11_000, 18_000), "timeout": False,
                "zero_output_share": round(0.10 + rng.random() * 0.08, 3),
                "stall_s": rng.randrange(0, 400),
                "pq_score": round(0.62 + rng.random() * 0.25, 3),
                "contaminated": False})
    stats = summarize(rows)
    verdicts = hypotheses(rows)
    return {"stats": stats, "verdicts": verdicts,
            "report": format_report(stats, verdicts)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_analyze.py",
                                 description="AB-VALUE statistics pipeline")
    ap.add_argument("runs", nargs="?", default=None,
                    help="runs.jsonl (one row per run)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out-dir", default=None,
                    help="write report.md + runs-summary.json here")
    args = ap.parse_args(argv)
    if args.demo:
        result = run_demo(seed=args.seed)
    else:
        if not args.runs:
            ap.error("either runs.jsonl or --demo is required")
        rows = [json.loads(line) for line in
                Path(args.runs).read_text(encoding="utf-8").splitlines()
                if line.strip()]
        stats = summarize(rows)
        verdicts = hypotheses(rows)
        result = {"stats": stats, "verdicts": verdicts,
                  "report": format_report(stats, verdicts)}
    if args.out_dir:
        d = Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.md").write_text(result["report"], encoding="utf-8")
        (d / "runs-summary.json").write_text(json.dumps(
            {"stats": result["stats"], "verdicts": result["verdicts"]},
            ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(result["report"], end="")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
