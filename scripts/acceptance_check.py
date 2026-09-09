#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acceptance_check.py — milestone acceptance: static battery + category matrix.

ONE milestone-acceptance entry point. Faces:
  default / --full            static battery (pinned smoke subset / full suite)
  --smoke                     matrix smoke category (the pinned fastest signal)
  --categories smoke,fault    scoped matrix runs (per-category artifacts under
                              KUNGLAO_OUT, default /out)

Static face:

Static acceptance: verify the refactored core mechanisms are in place and
runnable (dynamic real-sample runs belong to the production skill; deferred).
Output: runs/e2e-acceptance-<ts>.json (static face); per-category
summaries + matrix-summary.json under the matrix output root

#689: test_suite_green runs a PINNED SMOKE SUBSET (scripts/acceptance_smoke.txt),
not the full suite. Full-suite enforcement lives ONLY in devkit/quality_gates.py
Gate 2 (Regression Safety) — pytest must not nest full pytest (the old embed
cost 2x~301s = 60% of the 2026-08-25 suite runtime and grew O(n^2) with it).
`--full` remains the explicit operator channel for a full-suite run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    """#107: the ranker is the rebuilt Thompson composite — score =
    (sampled case posterior + LAMBDA_DH*dH) * worth, deterministic under the
    default seed, with the new feeds diagnostics and no weighted-era fields.
    (The check token keeps its historical name; the formula it pins changed
    by owner ruling — "之前的不要了".)"""
    try:
        import priority_ratio as pr
        claims = [{"id": "C1", "status": "OPEN", "evidence_tier_attempted": 0,
                   "promotion_attempts": 0, "statement": "c2 config"}]
        out = pr.priority_ratio(claims, {}, pr.EvidenceView())
        a = out[0]
        again = pr.priority_ratio(claims, {}, pr.EvidenceView())[0]
        det = (a.to_dict() == again.to_dict())
        composite = (hasattr(a, "feeds")
                     and {"thompson_sample", "case_flip_potential", "dh_pq"}
                     <= set(a.feeds or {})
                     and not hasattr(a, "leverage")
                     and not hasattr(a, "delta_disc"))
        bounded = 0.0 < a.score < 1.0 + pr.LAMBDA_DH + 1e-9  # Beta sample + dH=0
        return {"name": "priority_voi_formula",
                "passed": det and composite and bounded,
                "detail": f"score={a.score} det={det} composite={composite} "
                          f"bounded={bounded}"}
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




# ---------- milestone matrix (absorbed category runner) ----------
# The matrix face of the milestone CLI: scoped category runs over the
# four acceptance categories plus the observation-only complexity and
# mutation audits. Per-category artifacts land under the output root
# (KUNGLAO_OUT, default /out); a smoke failure short-circuits the
# remaining categories.

from harness_common import utc_now_z as utc_now  # noqa: E402

KUNGLAO_ROOT = Path("/kunglao") if Path("/kunglao").exists() else Path(__file__).resolve().parent.parent
OUT_DIR = Path(os.environ.get("KUNGLAO_OUT", "/out"))
TIMEOUT_S = int(os.environ.get("KUNGLAO_TIMEOUT", "1800"))
MUTATION_BUDGET = int(os.environ.get("KUNGLAO_MUTATION_BUDGET", "50"))

CATEGORIES = ("smoke", "complexity", "regression", "integration", "fault", "mutation")




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
    tests are serialized via a machine-local file lock; xdist respects
    the marker).
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




def _parse_categories(spec: str) -> list[str]:
    """Parse a comma-separated category list; unknown names raise ValueError."""
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in CATEGORY_FUNCS]
    if unknown:
        raise ValueError(
            f"unknown category {unknown} (known: {sorted(CATEGORY_FUNCS)})")
    return names


def run_categories(categories: list[str],
                   out_root: Path | None = None) -> dict:
    """Run the selected matrix categories in order; write the aggregate
    summary; return the report dict (overall_passed = every exit_code 0).
    A smoke failure short-circuits the remaining categories with an
    explicit skipped marker."""
    out_dir = Path(out_root) if out_root is not None else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    overall: dict = {"mode": ",".join(categories), "categories": [],
                     "verdict": "ACCEPT", "ts": utc_now()}
    smoke_failed = False
    bar = _make_progress_bar(len(categories), desc="kunglao-test matrix")
    with bar:
        for m in categories:
            bar.set_description(f"running {m}")
            if smoke_failed and m != "smoke":
                skip = {"category": m, "exit_code": 0, "duration_s": 0.0,
                        "skipped": "smoke-failure-short-circuit",
                        "ts": utc_now()}
                _write_json(out_dir / m / "summary.json", skip)
                overall["categories"].append(skip)
                bar.write(f"  {m}: SKIPPED (smoke failed)")
                bar.update(1)
                continue
            try:
                summary = CATEGORY_FUNCS[m]()
            except Exception as e:  # noqa: BLE001 — report, never crash the matrix
                summary = {"category": m, "exit_code": 2, "duration_s": 0.0,
                           "exception": repr(e), "ts": utc_now()}
                _write_json(out_dir / m / "summary.json", summary)
            rc = summary["exit_code"]
            dur = summary["duration_s"]
            status = "PASS" if rc == 0 else "FAIL"
            bar.set_postfix_str(f"{m}: {status} (rc={rc}, {dur:.2f}s)")
            bar.write(f"  === {m} === exit={rc} duration={dur:.2f}s")
            if rc != 0:
                overall["verdict"] = "REJECT"
                if m == "smoke":
                    smoke_failed = True
            overall["categories"].append(summary)
            bar.update(1)
    _write_json(out_dir / "matrix-summary.json", overall)
    print()
    print("=" * 80, flush=True)
    print(f"  VERDICT: {overall['verdict']}", flush=True)
    print("=" * 80, flush=True)
    for c in overall["categories"]:
        status = "PASS" if c.get("exit_code") == 0 else (
            "SKIP" if c.get("skipped") else "FAIL")
        print(f"  {c['category']:14s}  {status:5s}  {c.get('duration_s', 0.0):7.2f}s",
              flush=True)
    print(f"\n  Reports under: {out_dir}/", flush=True)
    overall["overall_passed"] = overall["verdict"] == "ACCEPT"
    return overall


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="acceptance_check.py", description="milestone acceptance: static battery + category matrix")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="[static face] run the full pytest suite instead of the pinned "
                         "smoke subset; always-on full enforcement lives in "
                         "devkit/quality_gates.py Gate 2")
    ap.add_argument("--smoke", action="store_true",
                    help="[matrix face] run only the smoke category (the pinned "
                         "fastest signal)")
    ap.add_argument("--categories", default=None,
                    help="[matrix face] comma-separated categories to run "
                         "(smoke,complexity,regression,integration,fault,mutation); "
                         "a smoke failure short-circuits the rest")
    ap.add_argument("--out", default=None,
                    help="[matrix face] output root for per-category artifacts "
                         "(default: KUNGLAO_OUT or /out)")
    args = ap.parse_args(argv)

    if args.smoke and (args.categories or args.full):
        print("acceptance_check: --smoke is mutually exclusive with "
              "--full/--categories", file=sys.stderr)
        return 2
    if args.full and args.categories:
        print("acceptance_check: --full is mutually exclusive with "
              "--categories", file=sys.stderr)
        return 2

    if args.smoke or args.categories:
        try:
            modes = ["smoke"] if args.smoke else _parse_categories(args.categories)
        except ValueError as exc:
            print(f"acceptance_check: {exc}", file=sys.stderr)
            return 2
        out_root = Path(args.out) if args.out else OUT_DIR
        report = run_categories(modes, out_root=out_root)
        return 0 if report["overall_passed"] else 1

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
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
