#!/usr/bin/env python3
"""tools/auxiliary/capture_golden.py — phase 0: golden master capture tool.

For every CLI case to be locked: run the command in a synthetic workspace → persist expected stdout (byte-exact).
Capture is freeze: this is the pre-refactor behavior baseline; no later phase may silently modify expected/
(legitimate behavior changes go through the change process in specs/README.md).

Usage:
  python tools/auxiliary/capture_golden.py            # capture all cases
  python tools/auxiliary/capture_golden.py --refresh  # re-capture (contract-change flow only)

Output: tests/fixtures/golden/{manifest.yaml, F-NN/{ws/, cmd.json, expected/stdout.txt}}
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

ROOT = Path(__file__).resolve().parents[2]  # repo root (tools/auxiliary/ → #340)
SCRIPTS = ROOT / "scripts"
GOLDEN = ROOT / "tests" / "fixtures" / "golden"


def make_ws(case_dir: Path, claims: list[dict], extra: dict | None = None) -> Path:
    """Build a synthetic workspace (isomorphic to tests/conftest.py::ws_factory)."""
    ws = case_dir / "ws"
    shutil.rmtree(ws, ignore_errors=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n" + "".join(
            f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
            f"  boundary_type: {c.get('boundary_type', 'positive_observation')}\n"
            f"  evidence_tier_attempted: {c.get('evidence_tier_attempted', 0)}\n"
            f"  promotion_attempts: {c.get('promotion_attempts', 0)}\n"
            f"  depends_on: {c.get('depends_on', '[]')}\n"
            for c in claims
        ), encoding="utf-8")
    for name, content in (extra or {}).items():
        p = ws / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ws


CASES: list[dict] = [
    # ---- F1-F18 regression matrix: core-loop 5 branches (convergence_check) ----
    dict(id="F-01", script="convergence_check.py", expected_exit=1,
         claims=[dict(id="C-1", status="OPEN")], args=["--json"],
         intent="F1 idle+free-slot -> DISPATCH"),
    dict(id="F-02", script="convergence_check.py", expected_exit=0,
         claims=[dict(id="C-1", status="PROVEN")], args=["--json"],
         intent="F2 converged no-open -> CONVERGED"),
    dict(id="F-03", script="convergence_check.py", expected_exit=3,
         claims=[dict(id="C-1", status="OPEN")], args=["--json"],
         extra={"runs/worker-status-w1.md": "## Status\nstatus: in-progress\n",
                "runs/worker-status-w2.md": "## Status\nstatus: in-progress\n",
                "runs/worker-status-w3.md": "## Status\nstatus: in-progress\n"},
         intent="F3 saturated 3 workers -> SATURATED"),
    dict(id="F-04", script="convergence_check.py", expected_exit=4,
         claims=[dict(id="C-1", status="OPEN", promotion_attempts=3)], args=["--json"],
         intent="F4 blocked attempts>=3 -> BLOCKED"),
    dict(id="F-05", script="convergence_check.py", expected_exit=2,
         claims=[dict(id="C-1", status="PROVEN")], args=["--json"],
         extra={"facts/_INDEX.md": "F001 | PARTIAL | C-1 | test\n"},
         intent="F5 partial fact -> DISPATCH_VERIFIER"),
    dict(id="F-06", script="convergence_check.py", expected_exit=1,
         claims=[dict(id="C-1", status="OPEN")], args=["--json"],
         extra={"runs/worker-status-w1.md": "## Status\nstatus: done\n"},
         intent="F6 zombie-done-worker frees slot -> DISPATCH"),
    # ---- loop health (convergence_health) ----
    dict(id="F-07", script="convergence_health.py", expected_exit=None,
         claims=[], args=["--json"],
         extra={".convergence_ledger.jsonl":
                "".join(json.dumps({"ts": f"2026-08-06T00:{5*i:02d}:00Z", "decision": "DISPATCH",
                                    "open_count": 5 - i, "open_ids": [], "partial_count": 0,
                                    "active_workers": 0, "blockers": [], "facts_total": 0}) + "\n"
                       for i in range(5))},
         intent="F7 health HEALTHY trending-down"),
    # ---- claim expiry / plan drift / stale blocker ----
    dict(id="F-08", script="claim_expiry.py", expected_exit=None,
         claims=[dict(id="C-old", status="OPEN"), dict(id="C-new", status="OPEN")],
         args=["--stale-hours", "24"],
         intent="F8 stale-claim expiry check"),
    dict(id="F-09", script="plan_drift_detector.py", expected_exit=None,
         claims=[dict(id="C-201", status="OPEN")],
         extra={"global_plan.txt": "plan with no C-201\n"},
         intent="F9 plan-drift ORPHAN_CLAIM"),
    dict(id="F-10", script="stale_blocker_prune.py", expected_exit=None,
         claims=[dict(id="C-1", status="PROVEN")],
         extra={"blockers/B1c-2026-08-01-w1.md": "blocker for C-1 (now PROVEN)\n"},
         intent="F10 stale-blocker-for-closed-claim"),
    # ---- progress reporting ----
    dict(id="F-11", script="progress_report.py", expected_exit=None,
         claims=[dict(id="C-1", status="OPEN"), dict(id="C-2", status="PROVEN")],
         intent="F11 progress report"),
    # ---- failure-analysis gate / self smoke test ----
    dict(id="F-12", script="failure_analysis_gate.py", expected_exit=None,
         claims=[dict(id="C-1", status="OPEN", promotion_attempts=1)],
         intent="F12 failure-analysis gate scan"),
    # ---- content hash / trace normalization ----
    dict(id="F-13", script="content_hash.py", expected_exit=0,
         claims=[],
         extra={"claim.txt": "Decode PE optional header magic bytes\n",
                "reproduce.txt": "python -c \"import struct; print(hex(struct.unpack('<H', open('a.bin','rb').read(2))[0]))\"\n",
                "expected.txt": "0x10b\n"},
         argv_override=["{script}", "{ws}/claim.txt", "{ws}/reproduce.txt", "{ws}/expected.txt"],
         intent="F13 content-hash idempotent"),
    dict(id="F-14", script="normalize_trace.py", expected_exit=0,
         claims=[], argv_override=["{script}", "{ws}/trace.json", "--tool", "qiling"],
         extra={"trace.json": json.dumps({"api_calls": [
             {"name": "WinHttpOpen", "args": ["0x7ff600001000", 4]},
             {"name": "WinHttpConnect", "args": ["0x7ff600002000", 8]},
         ]})},
         intent="F14 normalize dynamic trace"),
    # ---- intent reconciliation / _INDEX maintenance ----
    dict(id="F-15", script="reconcile_intents.py", expected_exit=0,
         claims=[dict(id="C-1", status="OPEN")],
         argv_override=["{script}", "{ws}/analysis_state.txt", "{ws}/facts"],
         extra={"analysis_state.txt": "in_flight: C-1\n",
                "facts/F-abc.md": "## claim\nidle\n"},
         intent="F15 intent reconciliation"),
    dict(id="F-16", script="update_index.py", expected_exit=0,
         claims=[dict(id="C-1", status="OPEN")],
         argv_override=["{script}", "upsert", "{ws}/facts/_INDEX.md", "F-abc", "OPEN", "C-1", "test"],
         extra={"facts/_INDEX.md": "# _INDEX\n"},
         intent="F16 atomic _INDEX upsert"),
]


def _argv(case: dict, ws: Path) -> list[str]:
    script = SCRIPTS / case["script"]
    if "argv_override" in case:
        argv = [str(x).format(script=str(script), ws=str(ws)) for x in case["argv_override"]]
        # Windows cannot exec .py directly: prepend the python interpreter
        if argv and argv[0].endswith(".py"):
            argv.insert(0, sys.executable)
        return argv
    args = case.get("args", [])
    return [sys.executable, str(script), str(ws), *args]


def main() -> int:
    ap = argparse.ArgumentParser(description="capture golden master baselines (phase 0)")
    ap.add_argument("--refresh", action="store_true", help="re-capture (for the spec change process)")
    ap.add_argument("--out", metavar="DIR", default=str(GOLDEN),
                    help="golden output dir (default: tests/fixtures/golden, #277)")
    args = ap.parse_args()

    golden = Path(args.out)
    golden.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    for case in CASES:
        cdir = golden / case["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        ws = make_ws(cdir, case["claims"], case.get("extra"))

        argv = _argv(case, ws)
        r = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        exp_dir = cdir / "expected"
        exp_dir.mkdir(exist_ok=True)
        (exp_dir / "stdout.txt").write_text(r.stdout, encoding="utf-8")
        (cdir / "cmd.json").write_text(json.dumps({"argv": argv, "cwd": str(ROOT)}, indent=2), encoding="utf-8")
        manifest_cases.append({
            "id": case["id"], "script": case["script"],
            "intent": case["intent"],
            "expected_exit": case.get("expected_exit"),
            "cmd": {"argv": argv, "cwd": str(ROOT)},
        })
        print(f"  [OK ] {case['id']} {case['script']} exit={r.returncode}")

    (golden / "manifest.yaml").write_text(
        yaml.safe_dump({"cases": manifest_cases}, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    print(f"manifest: {len(manifest_cases)} cases -> {golden / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
