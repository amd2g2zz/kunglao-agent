#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checker.py — tf-chain3-js-v1 TF answer checker (#356).

Standalone (stdlib only): grades the session's answer.txt byte-exact
against the unit's constructed ground truth. Emits the runner-style
stream (METRIC / FAILURE / EVIDENCE / VERDICT); exit 0 PASS / 1 FAIL /
2 REFUSED (no gradeable answer file)."""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEX16 = re.compile(r'^[0-9a-f]{16}$')

def _failures(expected, got_lines):
    failures = []
    for i, want in enumerate(expected):
        if i >= len(got_lines):
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} missing"})
            continue
        got = got_lines[i].strip()
        if not HEX16.match(got):
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} malformed (want 16-hex)"})
        elif got != want:
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} mismatched"})
    extra = len(got_lines) - len(expected)
    if extra > 0:
        failures.append({"code": "PAIR_MISMATCH",
                         "detail": f"{extra} extra line(s)"})
    return failures

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    gt = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))
    expected = [p["out"] for p in gt["published_pairs"]]
    answer = Path(args.answer)
    out = Path(args.out) if args.out else HERE.parent / "runs" / "tf-check" \
        / gt["task_id"]
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    answer_ref = str(answer)
    if not answer.is_file():
        failures = [{"code": "BAD_CANDIDATE",
                     "detail": f"answer file missing: {answer}"}]
        verdict, rc = "REFUSED", 2
        matched = 0
    else:
        got_lines = answer.read_text(encoding="utf-8",
                                     errors="replace").splitlines()
        failures = _failures(expected, got_lines)
        line_failures = [f for f in failures
                         if f["detail"].startswith("line ")]
        matched = len(expected) - len(line_failures)
        verdict, rc = ("PASS", 0) if not failures else ("FAIL", 1)
    metrics = {"ttc_seconds": round(time.time() - started, 3),
               "dispatch_count": 1,
               "pass_at_k_contribution": 1 if verdict == "PASS" else 0,
               "converged": 1 if verdict == "PASS" and not failures else 0}
    evidence = {
        "schema": "kunglao-eval-evidence/1",
        "task_id": gt["task_id"], "eval_version": gt.get("eval_version"),
        "family": gt["family"], "tier": "toolflex",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate": answer_ref,
        "faces": {"tf-answer": {"matched": matched,
                                "count": len(expected)}},
        "metrics": metrics, "verdict": verdict, "failures": failures,
    }
    ev = out / (f"evidence-{gt['task_id']}-"
                f"{time.strftime('%Y%m%dT%H%M%SZ')}-"
                f"{os.getpid() % 100000}.json")
    ev.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    for name, value in metrics.items():
        print(f"METRIC {name}={value:g}"
              if isinstance(value, float) else f"METRIC {name}={value}")
    for f in failures:
        print(f"FAILURE code={f['code']} detail={f['detail']}")
    print(f"EVIDENCE {ev}")
    print(f"VERDICT {verdict}")
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
