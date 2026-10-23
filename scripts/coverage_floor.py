#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_floor.py — measured-set coverage floor (raise-only ratchet).

Amends the observation-only coverage policy: coverage over the MEASURED
SET (scripts/ + hooks/ production faces — the same --cov scope the
release-check integration leg already uses) is ENFORDED in CI at the
ratchet floor.

The floor lives in `coverage-floor.json` (committed, hygiene-baseline
precedent) and can only move UP:
  - `check`     — fail when measured percent < floor (CI gate step).
  - `monotone`  — fail when the PR floor < base-ref floor (CI PR step).
  - `validate`  — schema/range validation only.

Never a --cov-fail-under flag: pytest.ini / local pytest stay
observation-only (the policy guard test keeps banning that flag).
Gate 4 (mutation validity) REMAINS the primary effectiveness metric —
this is a scoped hygiene rail under it, not a replacement.

Exit codes: 0 pass / 2 violation / 3 usage-or-contract error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLOOR_FILE = ROOT / "coverage-floor.json"
SCHEMA = "coverage-floor/1"
REQUIRED_KEYS = ("schema", "floor", "min_floor", "measured_set",
                 "baseline_measured")
# The enforced climb TARGET (the floor the measured set must reach).
# Pinned independently in the floor guard test — two sources, one value.
# The RATCHET itself is seeded once at review (the hygiene-baseline
# precedent: seed at the recorded truth, with cross-platform tolerance)
# and is then RAISE-ONLY — the CI monotone step refuses any floor below
# the base branch's floor.
TARGET_FLOOR = 70.0

# Cross-platform measurement tolerance at SEED time: the ratchet may be
# seeded up to 5% below the recorded baseline (mac-local vs CI runners
# differ by a few points); afterwards the CI monotone step makes any
# lowering impossible. 0.95, not fitted — a documented policy constant.
SEED_TOLERANCE = 0.95


def load_floor(path: Path | str = DEFAULT_FLOOR_FILE) -> dict:
    """Parse + validate the ratchet file. ValueError on any violation."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}, got {data.get('schema')!r}")
    for key in REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"missing key: {key}")
    floor = float(data["floor"])
    min_floor = float(data["min_floor"])
    baseline = float(data["baseline_measured"])
    if floor <= 0 or baseline <= 0:
        raise ValueError("floor and baseline_measured must be positive")
    if floor < SEED_TOLERANCE * baseline:
        raise ValueError(
            f"floor {floor} is more than {int((1 - SEED_TOLERANCE) * 100)}% "
            f"below the recorded baseline {baseline} — a seed that far "
            f"below the truth is a silent bar-drop")
    if min_floor < floor:
        raise ValueError(
            f"declared target min_floor {min_floor} below the live floor "
            f"{floor} — the target never trails the ratchet")
    if list(data["measured_set"]) != ["scripts", "hooks"]:
        raise ValueError(
            f"measured_set must be ['scripts', 'hooks'], "
            f"got {data['measured_set']!r}")
    return data


def check_violation(measured: float, floor: float) -> str | None:
    """Violation message when measured < floor, else None."""
    if measured >= floor:
        return None
    return (f"measured-set coverage {measured:.2f}% < floor {floor:.2f}% "
            f"Raise coverage with REAL tests on scripts/ + hooks/ — "
            f"lowering the ratchet is forbidden.")


def monotone_violation(base_floor: float, candidate_floor: float) -> str | None:
    """Violation message when the candidate lowers the ratchet, else None."""
    if candidate_floor >= base_floor:
        return None
    return (f"ratchet regression: floor {candidate_floor} < base-ref floor "
            f"{base_floor} — coverage-floor.json may only move UP.")


def floor_from_git(repo: Path, ref: str,
                   rel: str = "coverage-floor.json") -> float:
    """Read the floor as committed on `ref` (works for base-ref comparisons)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{rel}"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise ValueError(f"no {rel} on ref {ref}: {out.stderr.strip()}")
    return float(json.loads(out.stdout)["floor"])


def _cmd_check(args: argparse.Namespace) -> int:
    cov = json.loads(Path(args.coverage_json).read_text(encoding="utf-8"))
    measured = float(cov["totals"]["percent_covered"])
    floor = float(load_floor(args.floor_file)["floor"])
    violation = check_violation(measured, floor)
    print(f"measured={measured:.2f}% floor={floor:.2f}% "
          f"(measured_set=scripts+hooks)")
    if violation:
        print(f"VIOLATION: {violation}", file=sys.stderr)
        return 2
    delta = measured - floor
    if delta > 0.5:
        print(f"ratchet opportunity: measured exceeds the floor by "
              f"{delta:.2f}pts — consider raising coverage-floor.json "
              f"(raise-only) in a follow-up PR.")
    target = min_floor_target(args.floor_file)
    if floor < target:
        print(f"climb pending: target={target:.2f}% "
              f"gap={target - measured:.2f}pts — raise only with REAL tests")
    return 0


def min_floor_target(floor_file: Path | str = DEFAULT_FLOOR_FILE) -> float:
    """The declared climb target (never a gate by itself)."""
    return float(load_floor(floor_file)["min_floor"])


def _cmd_monotone(args: argparse.Namespace) -> int:
    try:
        base = floor_from_git(Path(args.repo), args.base_ref)
    except ValueError:
        # First PR introducing the ratchet: the base ref carries no
        # coverage-floor.json, so there is nothing to regress from —
        # monotonicity is vacuously satisfied (raise-only from here on).
        base = None
    if base is None:
        print(f"base-ref ({args.base_ref}) has no coverage-floor.json — "
              f"first landing, monotonicity vacuous (raise-only from "
              f"here on)")
        return 0
    cand = float(load_floor(args.floor_file)["floor"])
    print(f"base-ref ({args.base_ref}) floor={base} candidate floor={cand}")
    violation = monotone_violation(base, cand)
    if violation:
        print(f"VIOLATION: {violation}", file=sys.stderr)
        return 2
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    data = load_floor(args.floor_file)
    print(f"OK: schema={data['schema']} floor={data['floor']} "
          f"min_floor={data['min_floor']} "
          f"measured_set={data['measured_set']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--floor-file", default=str(DEFAULT_FLOOR_FILE))

    p = sub.add_parser("check", help="fail when measured < floor")
    common(p)
    p.add_argument("--coverage-json", default="coverage.json")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("monotone", help="fail when floor < base-ref floor")
    common(p)
    p.add_argument("--base-ref", required=True)
    p.add_argument("--repo", default=str(ROOT))
    p.set_defaults(func=_cmd_monotone)

    p = sub.add_parser("validate", help="validate the ratchet file")
    common(p)
    p.set_defaults(func=_cmd_validate)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
