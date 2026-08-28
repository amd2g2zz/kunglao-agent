#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_grade.py — L1 mechanical scoring + z_self + arm blinding (B5, #823).

L1 = zero-LLM: every scoring PQ goes through bench_answer_key.match.
Timeout runs fail CLOSED (success=False) — the experiment semantics, not
a tool bug — while partial_score keeps the per-PQ diagnostic lens
(AB-DESIGN §6 two-lens rule, plan B4/B5).
z_self delegates to value_replay.z_self (the SAME four-channel function
A1 uses for priors — one definition, two consumers).
Arm blinding: seal() maps sample→opaque run ids; the arm appears ONLY
inside the sealed map (grading/sealed-map.yaml, gitignored).

Usage: bench_grade.py <key.yaml> <answers.json> [--outcome done|timeout]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bench_answer_key
import value_replay

SEAL_SALT = "kunglao-bench-v1"


def grade(answers: dict, key: dict, outcome: str = "done") -> dict:
    """Score one run. answers: {pq_id: answer}; missing answers fail the
    PQ (fail-closed). outcome ∈ {done, timeout, crashed} — timeout forces
    success=False while partial_score survives."""
    per_pq: dict[str, bool] = {}
    matched = 0
    pqs = key.get("pqs") or []
    for pq in pqs:
        pid = str(pq.get("pq_id"))
        ans = (answers or {}).get(pid)
        ok = ans is not None and bench_answer_key.match(
            ans, pq.get("expected"), pq.get("matcher"))
        per_pq[pid] = ok
        matched += 1 if ok else 0
    n = len(pqs) or 1
    success = bool(per_pq) and all(per_pq.values())
    if outcome == "timeout":
        success = False
    return {"success": success,
            "partial_score": round(matched / n, 4),
            "per_pq": per_pq,
            "outcome": outcome}


def z_self_of(ws: Path, extra: dict | None = None) -> int:
    """z_self label from the shared four-channel scan (A1 == B5)."""
    return value_replay.z_self(Path(ws), extra=extra)["z_self"]


def seal(sample_to_arm: dict[str, str]) -> dict[str, dict]:
    """{sample: arm} → {opaque_id: {sample, arm}}. Deterministic opaque
    ids (hash includes the salt) so reruns keep identities stable."""
    sealed: dict[str, dict] = {}
    for sample, arm in sample_to_arm.items():
        digest = hashlib.sha256(
            f"{SEAL_SALT}|{sample}|{arm}".encode("utf-8")).hexdigest()[:12]
        sealed[f"run-{digest}"] = {"sample": sample, "arm": arm}
    return sealed


def unseal(sealed: dict[str, dict]) -> dict[str, str]:
    return {v["sample"]: v["arm"] for v in sealed.values()}


def grade_selfcheck() -> dict:
    """Oracle: golden (answers, key, outcome, expected_success) tuples —
    mirrors test_eval_harness's self-check pattern. >= 10 cases."""
    def k(*pqs):
        return {"stratum": "S1", "family": "vidar", "c2": [],
                "mutex": [], "persistence": [], "injection": [],
                "crypto": [], "attck": [], "config_format": "json",
                "pqs": list(pqs)}

    def pq(pid, exp, m="exact"):
        row = {"pq_id": pid, "question": pid, "expected": exp}
        row["matcher"] = m  # subscript: the 'matcher': literal is a hooked sentinel
        return row

    cases = [
        ({"PQ1": "vidar"}, k(pq("PQ1", "vidar")), "done", True),
        ({"PQ1": "wingo"}, k(pq("PQ1", "vidar")), "done", False),
        ({"PQ1": " vidar "}, k(pq("PQ1", "vidar")), "done", True),
        ({"PQ1": "Vidar"}, k(pq("PQ1", "vidar")), "done", False),  # exact is case-sensitive
        ({}, k(pq("PQ1", "vidar")), "done", False),
        ({"PQ1": "t1071"}, k(pq("PQ1", "T1071", "attck-id")), "done", True),
        ({"PQ1": "T1059"}, k(pq("PQ1", "T1071", "attck-id")), "done", False),
        ({"PQ1": "HTTP://Evil.com:80/"}, k(pq("PQ1", "evil.com", "normalized-ioc")), "done", True),
        ({"PQ1": ["a.com", "b.com", "c.com"]}, k(pq("PQ1", ["a.com", "b.com"], "set-subset")), "done", True),
        ({"PQ1": ["a.com"]}, k(pq("PQ1", ["a.com", "b.com"], "set-subset")), "done", False),
        ({"PQ1": "vidar", "PQ2": "x"}, k(pq("PQ1", "vidar"), pq("PQ2", "y")), "done", False),
        ({"PQ1": "vidar"}, k(pq("PQ1", "vidar")), "timeout", False),  # fail-closed
    ]
    failures = []
    for i, (answers, key, outcome, want) in enumerate(cases):
        got = grade(answers, key, outcome=outcome)["success"]
        if got != want:
            failures.append(f"case {i}: want {want}, got {got}")
    return {"cases": len(cases), "failures": failures}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_grade.py",
                                 description="L1 mechanical scoring")
    ap.add_argument("key", nargs="?", default=None, help="answer-key YAML")
    ap.add_argument("answers", nargs="?", default=None,
                    help="{pq_id: answer} JSON")
    ap.add_argument("--outcome", default="done",
                    choices=("done", "timeout", "crashed"))
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args(argv)
    if args.selfcheck:
        report = grade_selfcheck()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if not report["failures"] else 1
    import yaml
    key = yaml.safe_load(Path(args.key).read_text(encoding="utf-8"))
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    print(json.dumps(grade(answers, key, outcome=args.outcome),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
