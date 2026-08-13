#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptance_check.py — 端到端验收 (issue #6, plan §2.3/§9).

静态验收: 验证重构核心机制就位 + 可运行 (动态真实样本 run 属生产 skill 职责, deferred)。
输出: runs/e2e-acceptance-<ts>.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

EIGHT_CLIS = ["kunglao.py", "kunglao-decide.py", "kunglao-verify.py", "kunglao-record.py",
              "kunglao-monitor.py", "kunglao-init.py", "kunglao-eval.py", "kunglao-digest.py"]


def _check_oracle() -> dict:
    try:
        import kunglao_eval as ke
        results = ke.oracle_selfcheck()
        passed = sum(r["passed"] for r in results)
        ok = passed == len(results) == 10
        return {"name": "oracle_10_10", "passed": ok, "detail": f"{passed}/{len(results)}"}
    except Exception as exc:
        return {"name": "oracle_10_10", "passed": False, "detail": f"error: {exc}"}


def _check_cli_surface() -> dict:
    failures = []
    for cli in EIGHT_CLIS:
        p = SCRIPTS / cli
        if not p.exists():
            failures.append(f"{cli} missing"); continue
        r = subprocess.run([sys.executable, str(p), "--help"], capture_output=True, timeout=30)
        if r.returncode != 0:
            failures.append(f"{cli} --help exit {r.returncode}")
    return {"name": "cli_surface_8", "passed": not failures, "detail": "; ".join(failures) or "8/8"}


def _check_priority_voi() -> dict:
    try:
        import priority_ratio as pr
        claims = [{"id": "C1", "status": "OPEN", "evidence_tier_attempted": 0,
                   "promotion_attempts": 0, "statement": "c2 config"}]
        out = pr.priority_ratio(claims, {}, pr.EvidenceView())
        a = out[0]
        numerator = 0.45 * a.leverage + 0.30 * a.discriminator + 0.25 * a.novelty
        voi = abs(a.score - round(numerator / a.cost, 3)) < 1e-6
        has_fields = hasattr(a, "leverage") and not hasattr(a, "delta_disc")
        return {"name": "priority_voi_formula", "passed": voi and has_fields,
                "detail": f"score={a.score} voi_ok={voi} fields_ok={has_fields}"}
    except Exception as exc:
        return {"name": "priority_voi_formula", "passed": False, "detail": f"error: {exc}"}


def _check_digest() -> dict:
    try:
        import digest_build as db
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            (ws / "task_spec.yaml").write_text("primary_questions:\n  - q1\n", encoding="utf-8")
            md = db.build_digest(ws)
            has_six = all(f"## sec_{c}" in md for c in "abcdef") and "## head" in md
            return {"name": "digest_builds", "passed": has_six, "detail": f"{len(md)}b six={has_six}"}
    except Exception as exc:
        return {"name": "digest_builds", "passed": False, "detail": f"error: {exc}"}


def _check_test_suite() -> dict:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider",
                            "--ignore=tests/test_acceptance.py"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        return {"name": "test_suite_green", "passed": r.returncode == 0, "detail": last[:120]}
    except Exception as exc:
        return {"name": "test_suite_green", "passed": False, "detail": f"error: {exc}"}


CHECKS = [_check_oracle, _check_cli_surface, _check_priority_voi, _check_digest, _check_test_suite]


def run_acceptance() -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    results = [fn() for fn in CHECKS]
    overall = all(r["passed"] for r in results)
    return {"ts": ts, "overall_passed": overall, "checks": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="acceptance_check.py", description="端到端静态验收")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    report = run_acceptance()
    if args.write:
        out = ROOT / "runs" / f"e2e-acceptance-{report['ts']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"acceptance report: {out}")
    print(f"overall: {'PASS' if report['overall_passed'] else 'FAIL'}")
    for c in report["checks"]:
        print(f"  [{'OK' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return 0 if report['overall_passed'] else 1


if __name__ == "__main__":
    sys.exit(main())
