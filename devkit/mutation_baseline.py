#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutation_baseline.py — Gate 4's evidence recorder (issue #663).

Gate 4 (Test Effectiveness) used to pass on `import mutmut` alone — no
mutation run, no evidence (the vacuous-pass report on #663). This
recorder produces the artifact the gate now requires: it runs mutmut on
the BOUNDED scope declared in pyproject `[tool.mutmut]` and writes
`devkit/mutation-baseline.json` (schema `mutation-baseline/1`) from the
REAL run's per-file result sidecars — counts are parsed, never invented;
an unparseable/absent sidecar is an error, not a zero.

Data flow (mutmut 3.x):
  1. `python -m mutmut run` executes with the repo's [tool.mutmut]
     config (source_paths/also_copy/only_mutate/test selection);
  2. per mutated file, mutmut writes `mutants/<path>.py.meta` carrying
     `exit_code_by_key` (mutant key -> pytest exit code);
  3. this recorder maps exit codes through mutmut's own status table
     (1/3/-24 killed; 0 survived; 36 timeout; 34 skipped; 35 suspicious;
     5/33 no tests; None not checked) and aggregates.

Usage:
  uv run --project . python devkit/mutation_baseline.py --record
  uv run --project . python devkit/mutation_baseline.py --print

Exit codes: 0 ok; 1 error (no config / run failed / unparseable).

The artifact is COMMITTED: Gate 4 passes only while a fresh, valid
baseline exists (schema + totals + not-checked==0 + base_commit an
ancestor of HEAD + age <= MUTATION_BASELINE_MAX_AGE_DAYS + score >=
MUTATION_SCORE_FLOOR, all in devkit/quality_gates.py).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_REL = Path("devkit") / "mutation-baseline.json"
SCHEMA = "mutation-baseline/1"

#: mutmut's own status table (mirror of mutmut/__main__.py
#: status_by_exit_code; unknown codes read as suspicious, like mutmut).
_STATUS_BY_EXIT_CODE = {
    1: "killed", 3: "killed", -24: "killed",
    0: "survived",
    5: "no_tests", 33: "no_tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "type_check_error",
    2: "interrupted",
    None: "not_checked",
}
_STATUS_BUCKETS = ("killed", "survived", "timeout", "suspicious", "skipped",
                   "no_tests", "type_check_error", "interrupted",
                   "not_checked")


def _load_mutmut_config(root: Path) -> dict:
    data = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    cfg = data.get("tool", {}).get("mutmut")
    if not cfg:
        raise SystemExit("no [tool.mutmut] config in pyproject.toml — "
                         "Gate 4 has no declared scope to record")
    if not cfg.get("only_mutate"):
        raise SystemExit("[tool.mutmut] declares no only_mutate targets — "
                         "an unbounded mutation run is not sanctioned")
    return cfg


def _git_head(root: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _mutmut_version() -> str:
    import importlib.metadata as md
    try:
        return md.version("mutmut")
    except md.PackageNotFoundError:
        return "unknown"


def _parse_sidecar(meta_path: Path) -> dict:
    doc = json.loads(meta_path.read_text(encoding="utf-8"))
    codes = doc.get("exit_code_by_key")
    if not isinstance(codes, dict) or not codes:
        raise SystemExit(f"sidecar {meta_path} carries no exit_code_by_key "
                         "rows — refusing to fabricate a baseline")
    counts = dict.fromkeys(_STATUS_BUCKETS, 0)
    for value in codes.values():
        status = _STATUS_BY_EXIT_CODE.get(value, "suspicious")
        counts[status] += 1
    return counts


def record(root: Path = REPO_ROOT) -> dict:
    cfg = _load_mutmut_config(root)
    mutants_dir = root / "mutants"
    # a stale copy tree or cache would poison the parse — always fresh
    for stale in (mutants_dir, root / ".mutmut-cache"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    run = subprocess.run([sys.executable, "-m", "mutmut", "run"],
                         cwd=root)
    if run.returncode != 0:
        raise SystemExit(f"mutmut run failed (rc={run.returncode}) — "
                         "no baseline recorded")

    totals = dict.fromkeys(_STATUS_BUCKETS, 0)
    for target in cfg["only_mutate"]:
        meta = mutants_dir / (str(target) + ".meta")
        if not meta.is_file():
            raise SystemExit(f"result sidecar missing: {meta} — "
                             "mutmut did not complete; no baseline recorded")
        part = _parse_sidecar(meta)
        for key in totals:
            totals[key] += part[key]
    total = sum(totals.values())
    if total == 0:
        raise SystemExit("zero mutants parsed — refusing an empty baseline")

    artifact = {
        "schema": SCHEMA,
        "tool": "mutmut",
        "tool_version": _mutmut_version(),
        "recorded_at": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "base_commit": _git_head(root),
        "scope": {
            "source_paths": list(cfg.get("source_paths", [])),
            "only_mutate": list(cfg["only_mutate"]),
            "test_selection": list(
                cfg.get("pytest_add_cli_args_test_selection", [])),
        },
        "totals": {**totals, "total": total},
        "score": round(totals["killed"] / total, 4),
    }
    out = root / ARTIFACT_REL
    out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"mutation baseline recorded -> {out}")
    print(f"  scope: {artifact['scope']['only_mutate']} "
          f"(selection {artifact['scope']['test_selection']})")
    print(f"  killed {totals['killed']}/{total}  "
          f"survived {totals['survived']}  timeout {totals['timeout']}  "
          f"suspicious {totals['suspicious']}  score {artifact['score']}")
    return artifact


def show(root: Path = REPO_ROOT) -> int:
    out = root / ARTIFACT_REL
    if not out.is_file():
        print(f"no baseline artifact at {out}", file=sys.stderr)
        return 1
    print(out.read_text(encoding="utf-8"), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate 4 mutation-baseline recorder (#663)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", action="store_true",
                   help="run mutmut on the declared scope and write the artifact")
    g.add_argument("--print", dest="print_", action="store_true",
                   help="print the current artifact")
    args = ap.parse_args(argv)
    if args.print_:
        return show()
    record()
    return 0


if __name__ == "__main__":
    sys.exit(main())
