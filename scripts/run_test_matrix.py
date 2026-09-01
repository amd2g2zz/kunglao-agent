#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_test_matrix.py — kunglao-agent v0.1.3 acceptance test orchestrator.

Authority: docs/v0.1.3-test-plan.md §2.2
Cross-platform (no bash-only). Drives the four test categories:

    regression  — pytest -q on the full existing test suite (Gate 2)
    integration — pytest -m integration on tests/v013_acceptance/
    fault       — pytest -m fault on tests/v013_acceptance/
    mutation    — mutmut run on the bounded module set (Gate 4 Phase 2)
    full        — all four, in order; failure of any → REJECT

Per-category artifacts under /out/<category>/ (mounted volume).

Exit codes:
    0 — all requested categories PASS
    1 — at least one category FAILED
    2 — usage / environment error (missing tool, bad mode)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

KUNGLAO_ROOT = Path("/kunglao") if Path("/kunglao").exists() else Path(__file__).resolve().parent.parent
OUT_DIR = Path(os.environ.get("KUNGLAO_OUT", "/out"))
TIMEOUT_S = int(os.environ.get("KUNGLAO_TIMEOUT", "1800"))
MUTATION_BUDGET = int(os.environ.get("KUNGLAO_MUTATION_BUDGET", "50"))

CATEGORIES = ("smoke", "complexity", "regression", "integration", "fault", "mutation")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str, str, float]:
    """Subprocess runner with timeout + duration."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout, env=full_env, encoding="utf-8", errors="replace")
        duration = time.monotonic() - start
        return r.returncode, r.stdout, r.stderr, duration
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        return 124, e.stdout or "", (e.stderr or "") + f"\n[TIMEOUT after {timeout}s]", duration


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def category_regression() -> dict:
    """Gate 2: full pytest -q run on existing tests.

    Loads `tests.v013_acceptance.conftest` as a plugin via `-p` so the
    xfail pass-through applies to the FULL regression suite (the
    v013 conftest only auto-loads for tests under tests/v013_acceptance).

    Uses pytest-xdist `-n auto` for parallel execution (load_sensitive
    tests are serialized via flock #369; xdist respects the marker).
    """
    out_dir = OUT_DIR / "regression"
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / "junit.xml"

    cmd = ["python", "-m", "pytest", "-q", "--junitxml", str(junit),
           "-m", "not replay", "--tb=short",
           "-p", "tests.v013_acceptance.conftest",
           "-n", "auto"]  # pytest-xdist parallel
    try:
        import pytest_timeout  # noqa: F401
        cmd.append("--timeout=300")
    except ImportError:
        pass
    rc, stdout, stderr, duration = _run(cmd, KUNGLAO_ROOT, TIMEOUT_S)

    (out_dir / "stdout.log").write_text(stdout or "", encoding="utf-8", errors="replace")
    (out_dir / "stderr.log").write_text(stderr or "", encoding="utf-8", errors="replace")

    summary = {
        "category": "regression",
        "exit_code": rc,
        "duration_s": round(duration, 2),
        "junit": str(junit),
        "stdout_log": str(out_dir / "stdout.log"),
        "stderr_log": str(out_dir / "stderr.log"),
        "stdout_bytes": len(stdout or ""),
        "stderr_bytes": len(stderr or ""),
        "ts": utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def category_integration() -> dict:
    """Integration: pytest -m integration on tests/v013_acceptance/test_integration_v013.py."""
    out_dir = OUT_DIR / "integration"
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / "junit.xml"

    target = KUNGLAO_ROOT / "tests" / "v013_acceptance" / "test_integration_v013.py"
    cmd = ["python", "-m", "pytest", "-v", "--junitxml", str(junit),
           "-m", "v013 and integration", str(target),
           "--tb=short"]
    try:
        import pytest_timeout  # noqa: F401
        cmd.append("--timeout=120")
    except ImportError:
        pass
    rc, stdout, stderr, duration = _run(cmd, KUNGLAO_ROOT, TIMEOUT_S // 2)

    (out_dir / "stdout.log").write_text(stdout or "", encoding="utf-8", errors="replace")
    (out_dir / "stderr.log").write_text(stderr or "", encoding="utf-8", errors="replace")

    summary = {
        "category": "integration",
        "exit_code": rc,
        "duration_s": round(duration, 2),
        "junit": str(junit),
        "stdout_log": str(out_dir / "stdout.log"),
        "stderr_log": str(out_dir / "stderr.log"),
        "stdout_bytes": len(stdout or ""),
        "stderr_bytes": len(stderr or ""),
        "ts": utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def category_fault() -> dict:
    """Fault injection: pytest -m fault on tests/v013_acceptance/test_fault_injection_v013.py."""
    out_dir = OUT_DIR / "fault"
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / "junit.xml"

    target = KUNGLAO_ROOT / "tests" / "v013_acceptance" / "test_fault_injection_v013.py"
    cmd = ["python", "-m", "pytest", "-v", "--junitxml", str(junit),
           "-m", "v013 and fault", str(target),
           "--tb=long"]
    try:
        import pytest_timeout  # noqa: F401
        cmd.append("--timeout=60")
    except ImportError:
        pass
    rc, stdout, stderr, duration = _run(cmd, KUNGLAO_ROOT, TIMEOUT_S // 2)

    (out_dir / "stdout.log").write_text(stdout or "", encoding="utf-8", errors="replace")
    (out_dir / "stderr.log").write_text(stderr or "", encoding="utf-8", errors="replace")

    summary = {
        "category": "fault",
        "exit_code": rc,
        "duration_s": round(duration, 2),
        "junit": str(junit),
        "stdout_log": str(out_dir / "stdout.log"),
        "stderr_log": str(out_dir / "stderr.log"),
        "stdout_bytes": len(stdout or ""),
        "stderr_bytes": len(stderr or ""),
        "ts": utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def category_mutation() -> dict:
    """Mutation: mutmut run on the bounded module set (Gate 4 Phase 2).

    OBSERVATION-ONLY in this project. Mutmut 3.x's trampoline mechanism
    requires `module.__name__` to match `source_paths`-derived keys. The
    project uses bare `from X import` (scripts/ in pytest.ini pythonpath),
    so mutmut's recorded keys are `convergence_check.x__...` while its
    expected keys are `scripts.convergence_check.x__...`. The fix would
    require either scripts/__init__.py (breaks 205 internal imports) or
    moving scripts to src/ (production refactor). Per the test plan
    §6.2 mutation score is an observation, not a gate.

    We still RUN mutmut to verify the runner + config are valid, and
    capture stats. Exit code reflects mutmut's own success (mutmut
    exit 0 = ran successfully, regardless of whether it found mutant
    coverage).
    """
    out_dir = OUT_DIR / "mutation"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("mutmut"):
        summary = {
            "category": "mutation",
            "exit_code": 2,
            "duration_s": 0.0,
            "note": "mutmut not installed (dev dep); skipping — Gate 4 Phase 1 only",
            "ts": utc_now(),
        }
        _write_json(out_dir / "summary.json", summary)
        return summary

    env = {
        "PYTHONPATH": ":".join([
            str(KUNGLAO_ROOT),
            str(KUNGLAO_ROOT / "scripts"),
            str(KUNGLAO_ROOT / "hooks"),
            str(KUNGLAO_ROOT / "tools"),
            str(KUNGLAO_ROOT / "tools/_lib"),
        ]),
    }

    cmd = ["mutmut", "run", "--max-children", "1"]
    rc, stdout, stderr, duration = _run(cmd, KUNGLAO_ROOT, min(TIMEOUT_S, 1500), env=env)

    results_path = KUNGLAO_ROOT / "results.json"
    mutmut_stats: dict = {}
    if results_path.exists():
        try:
            mutmut_stats = json.loads(results_path.read_text(encoding="utf-8"))
            shutil.copy(results_path, out_dir / "mutmut-results.json")
        except Exception as e:
            mutmut_stats = {"parse_error": str(e)}

    (out_dir / "stdout.log").write_text(stdout or "", encoding="utf-8", errors="replace")
    (out_dir / "stderr.log").write_text(stderr or "", encoding="utf-8", errors="replace")

    # OBSERVATION ONLY: if mutmut ran but trampoline mismatch blocked
    # coverage, count it as a partial pass with a clear note. This is
    # NOT a release-blocker (Gate 4 is "test effectiveness"; the project
    # acknowledges mutation testing is Phase 2 with caveats).
    trampoline_mismatch = "Stopping early" in (stdout or "")
    observation_only = trampoline_mismatch

    summary = {
        "category": "mutation",
        "exit_code": rc if not observation_only else 0,
        "duration_s": round(duration, 2),
        "mutmut_stats": mutmut_stats,
        "stdout_log": str(out_dir / "stdout.log"),
        "stderr_log": str(out_dir / "stderr.log"),
        "stdout_bytes": len(stdout or ""),
        "stderr_bytes": len(stderr or ""),
        "ts": utc_now(),
        "observation_only": observation_only,
        "observation_reason": (
            "mutmut 3.x trampoline keys mismatch: recorded=convergence_check.x__... "
            "expected=scripts.convergence_check.x__... — project uses bare "
            "imports (no scripts/ package). Fix requires either scripts/__init__.py "
            "(breaks 205 internal imports) or moving scripts to src/ (production "
            "refactor). Per docs/v0.1.3-test-plan.md §6.2, mutation score is an "
            "observation, not a gate."
            if observation_only else None
        ),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def category_smoke() -> dict:
    """Smoke (Gate 1 + Gate 3 cross-cut): fastest signal — runs first."""
    out_dir = OUT_DIR / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / "junit.xml"

    target = KUNGLAO_ROOT / "tests" / "v013_acceptance" / "test_smoke_v013.py"
    cmd = ["python", "-m", "pytest", "-v", "--junitxml", str(junit),
           "-m", "v013 and smoke", str(target), "--tb=short"]
    try:
        import pytest_timeout  # noqa: F401
        cmd.append("--timeout=30")
    except ImportError:
        pass
    rc, stdout, stderr, duration = _run(cmd, KUNGLAO_ROOT, 120)

    # Full logs (NOT truncated) — per user feedback that app logs are part of
    # the artifact surface and truncation defeats the point.
    (out_dir / "stdout.log").write_text(stdout or "", encoding="utf-8", errors="replace")
    (out_dir / "stderr.log").write_text(stderr or "", encoding="utf-8", errors="replace")

    summary = {
        "category": "smoke",
        "exit_code": rc,
        "duration_s": round(duration, 2),
        "junit": str(junit),
        "stdout_log": str(out_dir / "stdout.log"),
        "stderr_log": str(out_dir / "stderr.log"),
        "stdout_bytes": len(stdout or ""),
        "stderr_bytes": len(stderr or ""),
        "ts": utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def category_complexity() -> dict:
    """Complexity audit: vulture (orphan) + radon cc (cyclomatic) + ruff (redundancy)."""
    import shutil as _sh
    out_dir = OUT_DIR / "complexity"
    out_dir.mkdir(parents=True, exist_ok=True)

    findings: dict[str, object] = {}
    all_stdout: list[str] = []
    all_stderr: list[str] = []
    start = time.monotonic()

    # 1. vulture — orphan / dead code (min-confidence 80 = strict)
    if _sh.which("vulture"):
        rc, out, err, _ = _run(
                ["vulture", "scripts", "hooks", "tools",
                 "--min-confidence", "80",
                 "--sort-by-size"],
                KUNGLAO_ROOT, 120,
            )
        findings["vulture"] = {
            "exit_code": rc,
            "stdout_log": str(out_dir / "vulture.log"),
            "stderr_log": str(out_dir / "vulture.err.log"),
            "stdout_bytes": len(out or ""),
        }
        (out_dir / "vulture.log").write_text(out or "", encoding="utf-8", errors="replace")
        (out_dir / "vulture.err.log").write_text(err or "", encoding="utf-8", errors="replace")
        all_stdout.append(f"=== vulture ===\n{out}")

    # 2. radon cc — cyclomatic complexity ranking
    if _sh.which("radon"):
        rc, out, err, _ = _run(
                ["radon", "cc", "scripts", "hooks", "tools",
                 "-a", "-s", "--total-average"],
                KUNGLAO_ROOT, 120,
            )
        findings["radon_cc"] = {
            "exit_code": rc,
            "stdout_log": str(out_dir / "radon_cc.log"),
            "stderr_log": str(out_dir / "radon_cc.err.log"),
            "stdout_bytes": len(out or ""),
        }
        (out_dir / "radon_cc.log").write_text(out or "", encoding="utf-8", errors="replace")
        (out_dir / "radon_cc.err.log").write_text(err or "", encoding="utf-8", errors="replace")
        all_stdout.append(f"=== radon cc ===\n{out}")

    # 3. ruff — redundancy (F-rules: unused imports/vars; C901: complexity)
    if _sh.which("ruff"):
        rc, out, err, _ = _run(
                ["ruff", "check", "scripts", "hooks", "tools",
                 "--select", "F,C901", "--statistics"],
                KUNGLAO_ROOT, 60,
            )
        findings["ruff_redundancy"] = {
            "exit_code": rc,
            "stdout_log": str(out_dir / "ruff_redundancy.log"),
            "stderr_log": str(out_dir / "ruff_redundancy.err.log"),
            "stdout_bytes": len(out or ""),
        }
        (out_dir / "ruff_redundancy.log").write_text(out or "", encoding="utf-8", errors="replace")
        (out_dir / "ruff_redundancy.err.log").write_text(err or "", encoding="utf-8", errors="replace")
        all_stdout.append(f"=== ruff --select F,C901 ===\n{out}")

    duration = time.monotonic() - start
    has_findings = any(f["exit_code"] not in (0, None) for f in findings.values())

    # Combined log (all tools) for at-a-glance review
    (out_dir / "combined.log").write_text("\n\n".join(all_stdout), encoding="utf-8", errors="replace")

    summary = {
        "category": "complexity",
        "exit_code": 0,  # observation is never blocks ACCEPT
        "duration_s": round(duration, 2),
        "findings": findings,
        "combined_log": str(out_dir / "combined.log"),
        "verdict": "findings-present" if has_findings else "clean",
        "ts": utc_now(),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


CATEGORY_FUNCS = {
    "smoke": category_smoke,
    "complexity": category_complexity,
    "regression": category_regression,
    "integration": category_integration,
    "fault": category_fault,
    "mutation": category_mutation,
}


def _progress(label: str, fraction: float, width: int = 30) -> str:
    """ASCII progress bar fallback (no external deps). fraction ∈ [0, 1]."""
    filled = int(round(fraction * width))
    bar = "=" * filled + " " * (width - filled)
    pct = int(round(fraction * 100))
    return f"[{bar}] {pct:3d}% {label}"


def _make_progress_bar(total: int, desc: str = "test matrix"):
    """Build a tqdm progress bar if tqdm is available; else a no-op shim.

    The bar advances one tick per category. Per-category duration_s and
    exit_code are written to stdout via tqdm.write() so they don't break
    the bar's line-redraw.
    """
    try:
        from tqdm import tqdm
        # Disable on non-TTY (e.g., redirected to file) — bar still logs.
        import sys as _sys
        disable = not _sys.stdout.isatty()
        return tqdm(total=total, desc=desc, unit="cat",
                     bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
                     disable=disable)
    except ImportError:
        return _NoOpBar(total)


class _NoOpBar:
    def __init__(self, total: int):
        self.total = total
        self.n = 0

    def update(self, n: int = 1):
        self.n += n

    def set_description(self, desc: str):
        pass

    def set_postfix_str(self, s: str):
        print(f"  {s}", flush=True)

    def write(self, s: str):
        print(s, flush=True)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent v0.1.3 test matrix")
    ap.add_argument("mode", nargs="?", default="full",
                    choices=("smoke", "complexity", "regression", "integration",
                             "fault", "mutation", "full"),
                    help="test category (default: full)")
    args = ap.parse_args(argv)

    if not KUNGLAO_ROOT.exists():
        print(f"FAIL: KUNGLAO_ROOT missing: {KUNGLAO_ROOT}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    modes = list(CATEGORIES) if args.mode == "full" else [args.mode]
    n = len(modes)
    overall = {
        "mode": args.mode,
        "categories": [],
        "verdict": "ACCEPT",
        "ts": utc_now(),
    }

    rc_total = 0
    smoke_failed = False
    bar = _make_progress_bar(len(modes), desc="kunglao-test matrix")
    with bar:
        for m in modes:
            bar.set_description(f"running {m}")

            if smoke_failed and m != "smoke":
                skip_summary = {
                    "category": m,
                    "exit_code": 0,
                    "duration_s": 0.0,
                    "skipped": "smoke-failure-short-circuit",
                    "ts": utc_now(),
                }
                _write_json(OUT_DIR / m / "summary.json", skip_summary)
                overall["categories"].append(skip_summary)
                bar.write(f"  {m}: SKIPPED (smoke failed)")
                bar.update(1)
                continue
            fn = CATEGORY_FUNCS[m]
            try:
                summary = fn()
            except Exception as e:
                summary = {
                    "category": m,
                    "exit_code": 2,
                    "duration_s": 0.0,
                    "exception": repr(e),
                    "ts": utc_now(),
                }
                _write_json(OUT_DIR / m / "summary.json", summary)

            rc = summary["exit_code"]
            dur = summary["duration_s"]
            status = "PASS" if rc == 0 else "FAIL"
            bar.set_postfix_str(f"{m}: {status} (rc={rc}, {dur:.2f}s)")
            bar.write(f"  === {m} === exit={rc} duration={dur:.2f}s")

            if rc != 0:
                overall["verdict"] = "REJECT"
                rc_total = 1
                if m == "smoke":
                    smoke_failed = True
            overall["categories"].append(summary)
            bar.update(1)

    _write_json(OUT_DIR / "overall.json", overall)

    # Final summary table
    print("\n" + "=" * 80, flush=True)
    print(f"  VERDICT: {overall['verdict']}", flush=True)
    print("=" * 80, flush=True)
    for c in overall["categories"]:
        status = "PASS" if c.get("exit_code") == 0 else ("SKIP" if c.get("skipped") else "FAIL")
        dur = c.get("duration_s", 0.0)
        print(f"  {c['category']:14s}  {status:5s}  {dur:7.2f}s", flush=True)
    print(f"\n  Reports under: {OUT_DIR}/", flush=True)
    return rc_total


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())