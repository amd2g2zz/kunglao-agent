# -*- coding: utf-8 -*-
"""cost_estimate.py — pre-dispatch cost estimator (issue #309).

Absorbed idea: Dryxio/auto-re-agent cmd_estimate.py:34-47 (tokens ~=
decompiled chars / 4 + fixed overhead; calls = functions x (rounds +
investigations)), re-implemented for kunglao claim-driven dispatch.

Estimate shape for a claim at evidence tier `eta` (0..2):
    tokens_per_tier = decompiled_chars / CHARS_PER_TOKEN + BASE_OVERHEAD_TOKENS
    est_tokens      = tokens_per_tier * tiers_left          (tiers_left = 3 - eta, min 1)
    est_calls       = n_functions * (tiers_left + INVESTIGATION_CALLS)
    cheapness_est   = clamp(REF_COST_TOKENS / est_tokens, 0, 1)

The estimator feeds priority.py's cheapness term. Conservative blending
keeps the tier heuristic as the CAP: blended = min(tier_cheapness,
cheapness_est) — an estimate can only make a claim look MORE expensive,
never cheaper than the tier says (issue: "保守: 保留 tier 作下限").

Sample features come from <workspace>/sample_features.yaml:
    n_functions: 142
    decompiled_chars: 48000
(produced by decompile/recon tools; absent file -> estimator disabled,
priority.py falls back to the pure tier heuristic.)

Usage:
  python scripts/cost_estimate.py <workspace> --json       # machine-readable
  python scripts/cost_estimate.py <workspace> --claim C-2  # specific claim
  python scripts/cost_estimate.py <workspace> --reproduce  # bare python command
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

CHARS_PER_TOKEN = 4.0
BASE_OVERHEAD_TOKENS = 3000.0
INVESTIGATION_CALLS = 2
REF_COST_TOKENS = 4000.0
MAX_TIERS = 3
FEATURES_FILE = "sample_features.yaml"
NEXT_TIER_CHEAP = {0: 1.0, 1: 0.5, 2: 0.2}

SCRIPT_PATH = Path(__file__).resolve()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def estimate_claim(claim: dict, features: dict) -> dict:
    """Pure deterministic estimate for one claim against sample features.

    Returns a dict with est_tokens, est_calls, tokens_per_tier, tiers_left,
    cheapness_est and the inputs (for --reproduce auditability).
    """
    eta = max(0, min(MAX_TIERS - 1, int(claim.get("evidence_tier_attempted", 0) or 0)))
    tiers_left = max(1, MAX_TIERS - eta)
    n_functions = max(0, int(features.get("n_functions", 0) or 0))
    decompiled_chars = max(0, int(features.get("decompiled_chars", 0) or 0))
    tokens_per_tier = decompiled_chars / CHARS_PER_TOKEN + BASE_OVERHEAD_TOKENS
    est_tokens = tokens_per_tier * tiers_left
    est_calls = n_functions * (tiers_left + INVESTIGATION_CALLS)
    cheapness_est = _clamp(REF_COST_TOKENS / est_tokens, 0.0, 1.0)
    return {
        "est_tokens": est_tokens,
        "est_calls": est_calls,
        "tokens_per_tier": tokens_per_tier,
        "tiers_left": tiers_left,
        "cheapness_est": cheapness_est,
        "inputs": {"n_functions": n_functions, "decompiled_chars": decompiled_chars,
                   "evidence_tier_attempted": eta,
                   "chars_per_token": CHARS_PER_TOKEN,
                   "base_overhead_tokens": BASE_OVERHEAD_TOKENS,
                   "investigation_calls": INVESTIGATION_CALLS,
                   "ref_cost_tokens": REF_COST_TOKENS},
    }


def blended_cheapness(tier_cheapness: float, est: dict) -> float:
    """Conservative blend: tier heuristic is the CAP on cheapness."""
    return min(float(tier_cheapness), float(est.get("cheapness_est", 1.0)))


def load_features(ws: Path) -> dict | None:
    """Read <ws>/sample_features.yaml; None when absent or malformed."""
    p = Path(ws) / FEATURES_FILE
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _tier_cheapness(claim: dict) -> float:
    return NEXT_TIER_CHEAP.get(int(claim.get("evidence_tier_attempted", 0) or 0), 0.1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="cost_estimate.py",
        description="pre-dispatch cost estimator (#309): claim + sample features -> "
                    "estimated tokens/calls/cost")
    ap.add_argument("workspace", help="workspace root (claim-register.yaml + sample_features.yaml)")
    ap.add_argument("--claim", default=None, help="claim id (default: first OPEN claim)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--reproduce", action="store_true",
                    help="print a bare python reproduction command")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    reproduce = (f'"{sys.executable}" "{SCRIPT_PATH}" "{ws}" --json')
    if args.reproduce:
        # field=value input record (kunglao_verify reproduce-output parseable);
        # the executable command form stays available in the --json payload
        fpath = ws / FEATURES_FILE
        print(f"workspace={ws}")
        print(f"claim={args.claim or 'first-open'}")
        print(f"features_file={fpath if fpath.exists() else '-'}")
        return 0

    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        print(f"error: no claim-register.yaml in {ws}", file=sys.stderr)
        return 1
    reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    claims = reg.get("claims") or []
    claim = None
    if args.claim:
        for c in claims:
            if c.get("id") == args.claim:
                claim = c
                break
        if claim is None:
            print(f"error: claim {args.claim} not found", file=sys.stderr)
            return 1
    else:
        for c in claims:
            if c.get("status") not in ("PROVEN", "VERIFIED", "NEGATIVE", "REFUTED",
                                       "DEFERRED", "STALE", "SUPERSEDED", "DEAD",
                                       "IN_PROGRESS"):
                claim = c
                break
    if claim is None:
        print("error: no OPEN claim found", file=sys.stderr)
        return 1

    features = load_features(ws)
    if features is None:
        if args.json:
            print(json.dumps({"workspace": str(ws), "claim_id": claim.get("id"),
                              "error": f"no {FEATURES_FILE} in workspace",
                              "estimate": None}, ensure_ascii=False, indent=2))
        else:
            print(f"no {FEATURES_FILE} in {ws} — estimator disabled (tier heuristic only)")
        return 0

    est = estimate_claim(claim, features)
    tier_c = _tier_cheapness(claim)
    payload = {
        "workspace": str(ws),
        "claim_id": claim.get("id"),
        "claim_statement": claim.get("statement", ""),
        "features": {k: est["inputs"][k] for k in ("n_functions", "decompiled_chars")},
        "tier_cheapness": tier_c,
        "estimate": est,
        "blended_cheapness": blended_cheapness(tier_c, est),
        "reproduce": reproduce,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"claim {payload['claim_id']}: est_tokens={est['est_tokens']:.0f} "
              f"est_calls={est['est_calls']} "
              f"cheapness_est={est['cheapness_est']:.2f} "
              f"tier={tier_c} blended={payload['blended_cheapness']:.2f}")
        print(f"reproduce: {reproduce}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
