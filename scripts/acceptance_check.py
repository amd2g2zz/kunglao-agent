#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptance_check.py — end-to-end acceptance (issue #6, plan §2.3/§9; #689).

Static acceptance: verify the refactored core mechanisms are in place and
runnable (dynamic real-sample runs belong to the production skill; deferred).
Output: runs/e2e-acceptance-<ts>.json

#689: test_suite_green runs a PINNED SMOKE SUBSET (scripts/acceptance_smoke.txt),
not the full suite. Full-suite enforcement lives ONLY in devkit/quality_gates.py
Gate 2 (Regression Safety) — pytest must not nest full pytest (the old embed
cost 2x~301s = 60% of the 2026-08-25 suite runtime and grew O(n^2) with it).
`--full` remains the explicit operator channel for a full-suite run.
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


SMOKE_MANIFEST = SCRIPTS / "acceptance_smoke.txt"  # #689: pinned nodeids, module-adjacent
SMOKE_SUITE_TIMEOUT = 120  # #689: pinned subset ≈ 2.5s idle; flat budget, deliberately NOT load-scaled
FULL_SUITE_TIMEOUT = 1800  # #689: --full path only (Gate 2 owns always-on full enforcement)


def _load_smoke_nodeids() -> list[str]:
    """#689: pinned smoke manifest — one nodeid per line; '#' comments and
    blank lines ignored. Empty/missing manifest fails loud (never silently
    green)."""
    if not SMOKE_MANIFEST.exists():
        raise FileNotFoundError(f"smoke manifest missing: {SMOKE_MANIFEST}")
    nodeids = [ln.strip() for ln in SMOKE_MANIFEST.read_text(encoding="utf-8").splitlines()]
    nodeids = [n for n in nodeids if n and not n.startswith("#")]
    if not nodeids:
        raise ValueError(f"smoke manifest carries no nodeids: {SMOKE_MANIFEST}")
    return nodeids


def _check_test_suite(full: bool = False) -> dict:
    """#689: default = pinned smoke subset (seconds); --full = explicit operator
    channel. The full suite is Gate 2's job (devkit/quality_gates.py), so the
    default path never nests full pytest inside pytest again. `--ignore` of
    tests/test_acceptance.py is kept on BOTH paths: a pinned acceptance nodeid
    (or the full path) would otherwise recurse into run_acceptance itself."""
    try:
        cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider",
               "--ignore=tests/test_acceptance.py"]
        if full:
            mode, timeout = "full", FULL_SUITE_TIMEOUT
        else:
            nodeids = _load_smoke_nodeids()
            cmd.extend(nodeids)
            mode, timeout = f"smoke:{len(nodeids)}", SMOKE_SUITE_TIMEOUT
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        return {"name": "test_suite_green", "passed": r.returncode == 0,
                "detail": f"[{mode}] {last[:120]}"}
    except Exception as exc:
        return {"name": "test_suite_green", "passed": False, "detail": f"error: {exc}"}


CHECKS = [_check_oracle, _check_cli_surface, _check_priority_voi, _check_digest, _check_test_suite]


def run_acceptance(full_suite: bool = False) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    results = [fn(full=full_suite) if fn is _check_test_suite else fn() for fn in CHECKS]
    overall = all(r["passed"] for r in results)
    return {"ts": ts, "overall_passed": overall, "checks": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="acceptance_check.py", description="end-to-end static acceptance")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="run the full pytest suite instead of the pinned smoke subset; "
                         "always-on full enforcement lives in devkit/quality_gates.py Gate 2")
    args = ap.parse_args(argv)
    report = run_acceptance(full_suite=args.full)
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
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
