#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""devkit/production_replay_gate.py — production-shape replay gate
(Standard 12, #807; root cause RC6 of the 2026-10-23 six-panel log review:
"RC6 verification ground misaligned").

CI validated consistency (types, mocks, unit) while PRODUCTION failed on
shapes no unit ever exercised: 392 identical unbounded warns, 25/40 orphan
settlements, arm-NULL posterior broadcast passing a family liveness
sentinel, verify-rejects followed by settlement-grade rows. This gate
closes that layer: GOLDEN SHAPE fixtures distilled from real production
runs (devkit/production_shapes/) are replayed through REGISTERED
assertions, so every escaped failure class becomes a reproducible face.

Faces:

  load_fixture(path)          validate + load one production-shape/1 file.
  materialize(ws, fixture)    write the fixture's artifact files into a
                              scratch workspace (runs/... layout).
  register_assertion(name, fn, applies)   THE cross-card registration
                              surface: fn(ws, fixture) -> (ok, detail).
                              #801 (392-warn circuit breaker), #800
                              (orphan settlement / missing_rollout) and
                              #809 (9/9 false-reject) register their own
                              assertions against the anchored fixture ids
                              in their own cards; this module never
              reimplements them (#807 boundary).
  run([dir], [--only])        replay every registered assertion over every
                              fixture it applies to; exit 0 pass / 1 any
                              assertion FAIL / 2 contract error.

The fixtures are SYNTHETIC by contract (fixture["synthetic"] is True and
pinned by test): the reference logs carry user content and never enter
the repo — only counts, field names, ordering faces and template tokens.

Standard 11 compliance: this module adds NO warn() telemetry points; the
runner reports structurally (per-check rows on stdout, non-zero exit).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

DEVKIT_ROOT = Path(__file__).resolve().parent
DEFAULT_SHAPES = DEVKIT_ROOT / "production_shapes"
SCHEMA = "production-shape/1"
REQUIRED_KEYS = ("id", "synthetic", "source", "shape", "events",
                 "expectations")

# name -> {"fn": callable(ws, fixture) -> (ok, detail), "applies": set|None}
# applies=None means every fixture; a set of fixture ids restricts scope.
ASSERTIONS: dict[str, dict] = {}


def load_fixture(path: Path | str) -> dict:
    """Parse + validate one production-shape fixture. ValueError on any
    contract violation (fail-fast: a shape file that cannot be trusted
    must never silently degrade into a vacuous pass)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(
            f"{Path(path).name}: schema must be {SCHEMA}, "
            f"got {data.get('schema')!r}")
    for key in REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"{Path(path).name}: missing key: {key}")
    if data["synthetic"] is not True:
        raise ValueError(
            f"{Path(path).name}: fixtures are SYNTHETIC by contract "
            "(raw production logs carry user content and never enter "
            "the repo)")
    if not isinstance(data["events"], list) or not data["events"]:
        raise ValueError(f"{Path(path).name}: events must be a non-empty list")
    if not isinstance(data["expectations"], dict):
        raise ValueError(f"{Path(path).name}: expectations must be an object")
    for art in (data.get("artifacts") or {}):
        if not str(art).startswith("runs/"):
            raise ValueError(
                f"{Path(path).name}: artifact paths must stay under runs/")
    return data


def fixtures(directory: Path | str = DEFAULT_SHAPES) -> list[dict]:
    """Load every fixture in a shapes dir, sorted by id (stable order)."""
    out = [load_fixture(p) for p in sorted(Path(directory).glob("*.json"))]
    if not out:
        raise ValueError(f"no fixtures under {directory}")
    return out


def materialize(ws: Path, fixture: dict) -> Path:
    """Write the fixture's artifacts into a scratch workspace layout."""
    ws = Path(ws)
    for rel, rows in (fixture.get("artifacts") or {}).items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
    return ws


def register_assertion(name: str, fn: Callable,
                       applies: set[str] | None = None) -> None:
    """Register an assertion for the replay battery (cross-card surface).

    fn(ws, fixture) -> (ok: bool, detail: str); ws is a materialized
    scratch workspace for ONE fixture. Duplicate names raise: an
    assertion silently replacing another is exactly the silent-drift
    class this gate exists to prevent."""
    if name in ASSERTIONS:
        raise ValueError(f"assertion already registered: {name}")
    ASSERTIONS[name] = {"fn": fn, "applies": applies}


def applies_to(entry: dict, fixture: dict) -> bool:
    return entry["applies"] is None or fixture["id"] in entry["applies"]


# ---- built-in assertion: INV-003 family-level (this card's own face) ------

def _inv003_posterior_family_key(ws: Path, fixture: dict) -> tuple[bool, str]:
    """The rl-posterior-moved fingerprint must REJECT the production
    arm-NULL broadcast shape and ACCEPT the arm-keyed control — the
    INV-003 family-level upgrade (#807), asserted both ways."""
    import liveness_gate as lg  # devkit sibling, lazy import

    spec = next(f for f in lg.load_fingerprints()["fingerprints"]
                if f["id"] == "rl-posterior-moved")
    ok, detail = lg.evaluate_fingerprint(ws, spec)
    expected = fixture.get("expectations", {}).get("rl-posterior-moved",
                                                   "PASS")
    want = expected == "PASS"
    good = ok == want
    verdict = "PASS" if ok else "FAIL"
    return good, (f"rl-posterior-moved read {verdict}, expected "
                  f"{expected}: {detail}")


register_assertion("inv003-posterior-family-key",
                   _inv003_posterior_family_key, applies=None)


def run(directory: Path | str = DEFAULT_SHAPES,
        only: set[str] | None = None) -> int:
    """Replay every registered assertion over every applying fixture.

    Each (fixture, assertion) pair gets a FRESH materialized scratch
    workspace — an assertion can never inherit another's pollution."""
    if not ASSERTIONS:
        print("replay gate: no assertions registered — nothing to run",
              file=sys.stderr)
        return 2
    import tempfile

    failed = 0
    ran = 0
    for fixture in fixtures(directory):
        for name, entry in sorted(ASSERTIONS.items()):
            if only and name not in only:
                continue
            if not applies_to(entry, fixture):
                continue
            ran += 1
            with tempfile.TemporaryDirectory(
                    prefix="replay-") as td:
                ws = materialize(Path(td), fixture)
                try:
                    ok, detail = entry["fn"](ws, fixture)
                except Exception as exc:  # noqa: BLE001 — a broken
                    # assertion is a RED result, never a crash of the gate
                    ok, detail = False, (
                        f"assertion raised: {type(exc).__name__}: {exc}")
            mark = "PASS" if ok else "FAIL"
            if not ok:
                failed += 1
            print(f"  [{mark}] {fixture['id']} :: {name}: {detail}")
    if ran == 0:
        print("replay gate: no assertion applied to any fixture",
              file=sys.stderr)
        return 2
    verdict = ("PRODUCTION-SHAPES LIVE" if failed == 0 else
               f"REPLAY GAPS ({failed} failing)")
    print(f"production-replay gate: {verdict}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shapes", default=str(DEFAULT_SHAPES))
    ap.add_argument("--only", nargs="*", help="assertion names to run")
    args = ap.parse_args(argv)
    try:
        return run(Path(args.shapes),
                   only=set(args.only) if args.only else None)
    except ValueError as exc:
        print(f"replay gate contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
