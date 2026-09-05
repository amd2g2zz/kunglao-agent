#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/experiment_difficulty_15.py — #15 tier-separation experiment harness.

Plan mandate: the feature set MUST be validated for tier separation BEFORE the
implementation is locked. This harness runs scripts/difficulty_calibration.py's
pure core over the synthetic 9-profile corpus in
tests/fixtures/difficulty_15/ (hand labels = construction intent) and reports:

  profile | intended | achieved | score | dominant factor | families

PASS bar (issue #15 plan):
  * mandatory: easy and MAX endpoints separate cleanly (all easy -> easy,
    all max -> max). Failure here exits 1 — the feature set is rejected.
  * preferred: full 4-way separation (all profiles match intent).
  * accepted fallback: mid tiers (medium/hard) blur while endpoints hold —
    exits 0 and prints the 2-tier (easy/hard) fallback decision, which the
    plan pre-approves for data maturity (4 tiers can open later without a
    schema change: `tier` is the only enum surface).

Run: python tests/experiment_difficulty_15.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import difficulty_calibration as dc  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "difficulty_15"


def load_corpus() -> list[dict]:
    manifest = yaml.safe_load(
        (FIXTURES / "corpus.yaml").read_text(encoding="utf-8"))
    rows = []
    for row in manifest["profiles"]:
        evidence = {"die": None, "apkid": None}
        for name in ("die", "apkid"):
            p = FIXTURES / row["profile"] / "evidence" / f"{name}.json"
            if p.is_file():
                evidence[name] = json.loads(p.read_text(encoding="utf-8"))
        rows.append({"profile": row["profile"],
                     "intended": row["intended_tier"],
                     "evidence": evidence})
    return rows


def main() -> int:
    corpus = load_corpus()
    if len(corpus) < 8:
        print(f"FAIL: corpus must span >=8 profiles, found {len(corpus)}")
        return 1

    print(f"#15 difficulty calibration experiment — {len(corpus)} synthetic profiles")
    print(f"{'profile':<30} {'intended':<8} {'achieved':<8} "
          f"{'score':>7}  dominant factor / note")
    print("-" * 100)

    mismatches: list[tuple[str, str, str]] = []
    endpoint_fail = False
    for row in corpus:
        result = dc.calibrate(dc.features_from_evidence(row["evidence"]))
        achieved, score = result["tier"], result["score"]
        dominant = result["dominant_factor"]
        if result["factors"].get("evidence_gap"):
            dominant = f"evidence_gap ({'; '.join(result['notes'])[:60]}...)"
        fams = ",".join(f for f, v in result["families"].items() if v["active"])
        print(f"{row['profile']:<30} {row['intended']:<8} {achieved:<8} "
              f"{score:>7.4f}  {dominant} [{fams}]")
        if achieved != row["intended"]:
            mismatches.append((row["profile"], row["intended"], achieved))
            if row["intended"] in ("easy", "max"):
                endpoint_fail = True

    print("-" * 100)
    if endpoint_fail:
        print("FAIL: easy/MAX endpoints did not separate cleanly — "
              "feature set rejected, do NOT lock the implementation.")
        return 1

    if mismatches:
        print(f"4-way separation NOT met ({len(mismatches)} mid-tier mismatches: "
              f"{mismatches}). DECISION: ship the 2-tier easy/hard fallback per "
              "the plan — collapse medium->easy, hard->hard at consumption; "
              "endpoints are clean, so the schema stays stable.")
        return 0

    print("PASS: full 4-way separation (easy/medium/hard/max) over the corpus. "
          "Feature set + weights LOCKED (see the experiment table in "
          "scripts/difficulty_calibration.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
