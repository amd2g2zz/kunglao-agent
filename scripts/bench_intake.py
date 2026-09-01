#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_intake.py — kunglao-bench manifest gate (B1, #823 AB-VALUE).

FAIL-CLOSED by design: every violation makes the whole check fail. The
intake gate is the first line of experiment hygiene — a bad manifest
must never reach the runner.

Checks per sample entry {id, stratum, path, sha256, first_seen,
truth_tier, truth_sources, scoring_pqs, excluded_pqs}:
  - stratum is one of S1..S4
  - the sample file exists and its sha256 matches the manifest
  - first_seen >= MODEL_CUTOFF (recency filter, AB-DESIGN §5.1 —
    post-cutoff samples blunt training-corpus memory)
  - truth: >=2 independent sources, or a single source-level A+ tier
  - path is OUTSIDE the repo (sample bytes never enter git)
Layer counts are enforced only under --strict-counts (8-7-8-7), so a
manifest can be built up incrementally while the full-experiment gate
still exists.

Usage: bench_intake.py <manifest.yaml> [--strict-counts] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

SCHEMA = "kunglao-bench-manifest/1"
STRATA = ("S1", "S2", "S3", "S4")
TIERS = ("A+", "A", "B")
MODEL_CUTOFF = "2025-08"  # YYYY-MM; first_seen must be >= this
FULL_COUNTS = {"S1": 8, "S2": 7, "S3": 8, "S4": 7}
REPO_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(manifest_path: Path,
          expect_counts: dict[str, int] | None = None) -> dict:
    """Validate one manifest; returns {ok, violations, counts}. Never
    raises for content problems — problems ARE the report."""
    violations: list[str] = []
    counts: dict[str, int] = {s: 0 for s in STRATA}
    try:
        data = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {"ok": False, "counts": counts,
                "violations": [f"manifest unreadable: {exc}"]}
    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        return {"ok": False, "counts": counts,
                "violations": ["manifest: missing samples[] list"]}
    seen_ids: set[str] = set()
    for e in data["samples"]:
        if not isinstance(e, dict):
            violations.append("entry: non-mapping entry")
            continue
        sid = str(e.get("id") or "")
        if not sid:
            violations.append("entry: missing id")
            continue
        if sid in seen_ids:
            violations.append(f"{sid}: duplicate id")
        seen_ids.add(sid)
        stratum = str(e.get("stratum") or "")
        if stratum not in STRATA:
            violations.append(f"{sid}: bad stratum {stratum!r}")
        else:
            counts[stratum] += 1
        p = Path(str(e.get("path") or ""))
        if not p.is_file():
            violations.append(f"{sid}: sample file missing: {p}")
        else:
            try:
                actual = _sha256(p)
            except OSError as exc:
                violations.append(f"{sid}: unreadable sample: {exc}")
            else:
                if actual != str(e.get("sha256") or "").lower():
                    violations.append(f"{sid}: sha256 mismatch")
        try:
            repo_root = Path(REPO_ROOT).resolve()
            inside = p.resolve().is_relative_to(repo_root)
        except (OSError, ValueError):
            inside = False
        if inside:
            violations.append(f"{sid}: sample path inside repo (git hygiene)")
        first_seen = str(e.get("first_seen") or "")
        if first_seen < MODEL_CUTOFF:
            violations.append(
                f"{sid}: first_seen {first_seen} < cutoff {MODEL_CUTOFF}")
        tier = str(e.get("truth_tier") or "")
        if tier not in TIERS:
            violations.append(f"{sid}: bad truth_tier {tier!r}")
        sources = e.get("truth_sources") or []
        if not isinstance(sources, list) or len(sources) < 1:
            violations.append(f"{sid}: truth_sources empty")
        elif len(sources) < 2 and tier != "A+":
            violations.append(
                f"{sid}: truth_sources <2 without A+ tier (single-source "
                "corroboration rule, AB-DESIGN §5.2)")
    if expect_counts is not None:
        for s, want in expect_counts.items():
            if counts.get(s, 0) != want:
                violations.append(f"count[{s}]: {counts.get(s, 0)} != {want}")
    return {"ok": not violations, "violations": violations, "counts": counts}


def _git_porcelain(root: Path) -> tuple[int, str]:
    """(returncode, stdout) of `git status --porcelain kunglao-bench` —
    module-level so tests can inject."""
    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain",
             "kunglao-bench"],
            capture_output=True, text=True, check=False, encoding="utf-8", errors="replace")
        return status.returncode, status.stdout
    except OSError:
        return 1, ""


def check_safety(vault_root: Path, vm_snapshot: str | None = None) -> dict:
    """B9 pre-run mechanical gate — three checks, ANY red refuses the
    run (plan B9 §8). Never auto-repairs; a red check is a human action."""
    vault_root = Path(vault_root)
    checks = {
        # §1: the vault must carry the encryption marker written by the
        # vault setup procedure (7z-AES / age container)
        "vault_encrypted": (vault_root / ".encrypted").is_file(),
        # §3: a VM snapshot base must be named for the pre-run restore
        "vm_snapshot": bool(vm_snapshot),
    }
    rc, out = _git_porcelain(REPO_ROOT)
    gitignore = (REPO_ROOT / "kunglao-bench" / ".gitignore")
    ignores_samples = gitignore.is_file() and "samples/" in gitignore.read_text(
        encoding="utf-8", errors="replace")
    checks["git_clean"] = (rc == 0 and not out.strip() and ignores_samples)
    return {"ok": all(checks.values()), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_intake.py",
                                 description="kunglao-bench manifest gate")
    ap.add_argument("manifest", help="path to kunglao-bench/manifest.yaml")
    ap.add_argument("--strict-counts", action="store_true",
                    help=f"enforce full layer counts {FULL_COUNTS}")
    ap.add_argument("--check-safety", metavar="VAULT_ROOT", default=None,
                    help="B9 pre-run gate: vault encryption / git clean / "
                         "VM snapshot (name via KUNGLAO_BENCH_VM_SNAPSHOT)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.check_safety:
        import os
        report = check_safety(Path(args.check_safety),
                              vm_snapshot=os.environ.get(
                                  "KUNGLAO_BENCH_VM_SNAPSHOT"))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for name, ok in report["checks"].items():
                print(f"{name}: {'PASS' if ok else 'RED'}")
            print("SAFETY " + ("PASS" if report["ok"] else "REFUSE"))
        return 0 if report["ok"] else 1
    report = check(Path(args.manifest),
                   expect_counts=FULL_COUNTS if args.strict_counts else None)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"counts: {report['counts']}")
        for v in report["violations"]:
            print(f"VIOLATION: {v}")
        print("INTAKE " + ("PASS" if report["ok"] else "FAIL"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
