#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release_receipt.py — kunglao-agent release receipt generator (issue #80).

The OBSERVED half of the release contract (the DECLARED half is
release-manifest.yaml at the repo root). Produces a machine-readable JSON
receipt for the current tree:

    revision (git HEAD) / dependency lock digest / asset inventory (sha256) /
    CLI inventory (--help exit codes) / router subcommands / test result.

Usage:
    python scripts/release_receipt.py [--out release-receipt.json]
                                       [--revision <sha>]
                                       [--manifest release-manifest.yaml]
                                       [--pytest-junit <junit.xml>]
                                       [--no-tests]
                                       [--check]

Exit contract: 0 = receipt written (or --check passed); 1 = manifest/CLI
validation failed or the receipt could not be produced. Test failures are
DATA recorded in the receipt — the CI pytest step is the GATE.

Test result intake:
  --pytest-junit <file>   read counts from a junit XML (CI passes the pytest
                          step's own output — no double test run)
  (default)               run the standard test command (python -m pytest -q)
                          and parse the summary line, plus a --collect-only
                          probe for the collected count
  --no-tests              omit the test result (fast local manifest check)

The receipt contains inventory digests only — never file contents, env vars,
or secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_VERSION = "1.0"

# ---- reverse scan contract (issue #320) ----
# Every shipped file under these directories must be declared in the manifest
# (assets.<section>) — "adding a shipped asset without declaring it fails CI"
# is enforced both ways: declared→exists AND exists→declared.
SCAN_SECTIONS = ("agents", "hooks", "templates", "tools")
# Doc/index-class files are governed by their own contracts (e.g.
# tools/_INDEX.yaml + validate_index.py), not the release manifest.
SCAN_WHITELIST_BASENAMES = {"README.md", "_INDEX.md", "_INDEX.yaml"}
SCAN_WHITELIST_PREFIX = "_index-"
# Runtime-generated / VCS-adjacent artifacts are not shipped assets.
SCAN_SKIPPED_DIRS = {"__pycache__"}

SUMMARY_RE = re.compile(
    r"(?P<failed>\d+) failed, (?P<passed>\d+) passed"
    r"(?:, (?P<skipped>\d+) skipped)?(?:, (?P<errors>\d+) error[s]?)? in .*"
)
PASSED_RE = re.compile(r"(?P<passed>\d+) passed(?:, (?P<skipped>\d+) skipped)? in .*")
COLLECTED_RE = re.compile(r"(\d+) tests? collected")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_dir(path: Path) -> str:
    """Deterministic digest of a directory: sha256 over sorted (relpath, sha256) pairs."""
    h = hashlib.sha256()
    for rel in sorted(p.relative_to(path).as_posix()
                      for p in path.rglob("*") if p.is_file()):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(sha256(path / rel).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def asset(path: str) -> dict:
    return {"path": path, "sha256": sha256(Path(path))}


# ---------- manifest / pyproject ----------

def load_manifest(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def pyproject_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def reverse_scan(root: Path, manifest: dict) -> list[str]:
    """存在→declared reverse scan (issue #320): every shipped file under
    agents/ hooks/ templates/ tools/ must be declared in the manifest's
    assets.<section> — undeclared assets FAIL with fix guidance.

    Exempt (doc/index-class): README.md, _INDEX.md, _INDEX.yaml, _index-*.md.
    Skipped (runtime/generated): __pycache__ directories, dotfiles, *.pyc.
    """
    errors: list[str] = []
    assets = manifest.get("assets", {})
    for section in SCAN_SECTIONS:
        declared = {str(p).replace("\\", "/") for p in assets.get(section, [])}
        d = root / section
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix == ".pyc":
                continue
            if any(part in SCAN_SKIPPED_DIRS or part.startswith(".")
                   for part in p.relative_to(root).parts):
                continue
            if (p.name in SCAN_WHITELIST_BASENAMES
                    or p.name.startswith(SCAN_WHITELIST_PREFIX)):
                continue
            rel = p.relative_to(root).as_posix()
            if rel not in declared:
                errors.append(f"undeclared asset: {rel} -- add it to "
                              f"release-manifest.yaml assets.{section}")
    return errors


def validate_manifest(manifest: dict, manifest_path: Path, errors: list[str]) -> None:
    """Declared contract vs tree: version agreement + every declared asset exists."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        errors.append("pyproject.toml missing")
    else:
        want = pyproject_version(pyproject)
        got = manifest.get("version", "")
        if want and got and want != got:
            errors.append(f"version mismatch: manifest={got} pyproject={want}")

    for section in ("agents", "hooks", "templates"):
        for rel in manifest.get("assets", {}).get(section, []):
            p = Path(rel)
            if not p.exists():
                errors.append(f"declared asset missing: {rel}")

    # #320: reverse scan — every shipped asset exists in the manifest.
    errors.extend(reverse_scan(Path("."), manifest))

    if not manifest.get("test_command"):
        errors.append("manifest test_command is empty")


# ---------- CLI inventory ----------

def probe_help(cmd: list[str], timeout: int = 60) -> int:
    try:
        # UTF-8 convention (#317/#320): child output is UTF-8 — locale
        # decoding (GBK) crashes reader threads; decode as UTF-8.
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode
    except (subprocess.TimeoutExpired, OSError) as exc:
        return -1


def cli_inventory(clis: list[str], errors: list[str]) -> list[dict]:
    out = []
    for cli in clis:
        rc = probe_help([sys.executable, str(cli), "--help"])
        out.append({"name": cli, "help_exit": rc})
        if rc != 0:
            errors.append(f"CLI --help failed ({rc}): {cli}")
    return out


def router_inventory(subcommands: list[str], errors: list[str]) -> dict:
    entry = {"command": "scripts/kunglao.py", "subcommands": list(subcommands), "help_exit": 0}
    for sub in subcommands:
        rc = probe_help([sys.executable, "scripts/kunglao.py", sub, "--help"])
        if rc != 0:
            entry["help_exit"] = rc
            errors.append(f"router subcommand --help failed ({rc}): kunglao.py {sub}")
    return entry


# ---------- test result ----------

def parse_junit(path: Path) -> dict:
    root = ET.parse(str(path)).getroot()
    suites = [root] if root.tag == "testsuite" else [c for c in root if c.tag == "testsuite"]
    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failed = sum(int(s.attrib.get("failures", 0)) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
    return {"collected": tests, "passed": tests - failed - skipped - errors,
            "failed": failed, "skipped": skipped}


def run_tests(command: str) -> dict:
    argv = command.split()
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable  # PATH may lack a bare `python` (e.g. ubuntu runners)
    r = subprocess.run(argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1500)
    tail = (r.stdout + r.stderr)[-4000:]
    m = SUMMARY_RE.search(tail) or PASSED_RE.search(tail)
    if not m:
        raise RuntimeError(f"could not parse pytest summary from:\n{tail[-500:]}")
    failed = int(m.groupdict().get("failed") or 0)
    passed = int(m.groupdict()["passed"])
    skipped = int(m.groupdict().get("skipped") or 0)
    collected = None
    coll = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    cm = COLLECTED_RE.search((coll.stdout + coll.stderr)[-2000:])
    if cm:
        collected = int(cm.group(1))
    return {"collected": collected, "passed": passed, "failed": failed, "skipped": skipped}


# ---------- assembly ----------

def build_receipt(manifest: dict, manifest_path: Path, revision: str,
                  test_result: dict | None) -> tuple[dict, list[str]]:
    errors: list[str] = []
    validate_manifest(manifest, manifest_path, errors)

    openspec = sorted(p.name for p in (Path("openspec") / "changes").iterdir()
                      if (Path("openspec") / "changes" / p.name).is_dir())

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dependencies": {
            "pyproject": asset("pyproject.toml"),
            "lockfile": asset("uv.lock"),
        },
        "assets": {
            "agents": [asset(a) for a in manifest.get("assets", {}).get("agents", [])],
            "hooks": [asset(h) for h in manifest.get("assets", {}).get("hooks", [])],
            "templates": [asset(t) for t in manifest.get("assets", {}).get("templates", [])],
            "tools": [asset(t) for t in manifest.get("assets", {}).get("tools", [])],
            "knowledge": [asset(k) for k in manifest.get("assets", {}).get("knowledge", [])],
            "references": [
                {"path": r, "sha256": sha256_dir(Path(r)) if Path(r).is_dir() else sha256(Path(r))}
                for r in manifest.get("assets", {}).get("references", [])
            ],
            "openspec_changes": [
                {"path": f"openspec/changes/{n}", "sha256": sha256_dir(Path("openspec") / "changes" / n)}
                for n in openspec
            ],
        },
        "clis": cli_inventory(manifest.get("clis", []), errors),
        "router": router_inventory(manifest.get("router_subcommands", []), errors),
        "tests": {"command": manifest.get("test_command", ""), **test_result} if test_result
                 else {"command": manifest.get("test_command", "")},
        "valid": not errors,
    }
    return receipt, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="kunglao-agent release receipt (issue #80) — manifest/CLI validation + machine-readable receipt")
    ap.add_argument("--out", default="release-receipt.json",
                    help="receipt output path ('-' = stdout; default release-receipt.json)")
    ap.add_argument("--revision", default=None,
                    help="revision override (default: git rev-parse HEAD)")
    ap.add_argument("--manifest", default="release-manifest.yaml",
                    help="release manifest path (override for tests)")
    ap.add_argument("--pytest-junit", default=None,
                    help="read test counts from a junit XML instead of running pytest")
    ap.add_argument("--no-tests", action="store_true",
                    help="omit the test result (fast local manifest check)")
    ap.add_argument("--check", action="store_true",
                    help="validate manifest + CLI surface only; write no receipt")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    manifest = load_manifest(manifest_path)

    if args.revision:
        revision = args.revision
    else:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        revision = r.stdout.strip() if r.returncode == 0 else "unknown"

    test_result = None
    if args.check:
        args.no_tests = True  # --check is a fast manifest/CLI gate — never runs the suite
    if not args.no_tests:
        if args.pytest_junit:
            jp = Path(args.pytest_junit)
            if not jp.exists():
                print(f"ERROR: junit file not found: {jp}", file=sys.stderr)
                return 1
            test_result = parse_junit(jp)
        else:
            test_result = run_tests(manifest.get("test_command", "python -m pytest -q"))

    receipt, errors = build_receipt(manifest, manifest_path, revision, test_result)

    if errors:
        print("RELEASE CONTRACT VIOLATIONS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)

    if args.check:
        return 0 if not errors else 1

    if receipt["valid"]:
        print(f"release receipt valid: revision={revision} "
              f"assets={sum(len(v) for v in receipt['assets'].values())} "
              f"clis={len(receipt['clis'])}", file=sys.stderr)
    if args.out == "-":
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    return 0 if receipt["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
