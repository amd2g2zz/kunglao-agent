#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discovery_gate.py — #866 discovery-face CI gate (quality_gates Gate 9).

Root cause (issue #866): tool building and discovery-face registration are
two disconnected processes — 65% of tools/ CLIs had zero discovery faces
("built then sealed away"). Per the adjudicated three-layer split,
DECLARATION is the eligibility gate: not registered = not in the candidate
set (registration != mandatory use; selection stays worker-autonomous).

The gate machine-binds that declaration for every tools/ ``__main__`` CLI:
a NEW CLI must register BOTH faces in the same change that adds it —

  face A (registry)   a tools/_INDEX.yaml entry — the execution registry
                      hooks/worker_budget_gates._load_tool_index_keywords
                      consumes at dispatch time. (The ext index is
                      DESCRIBE-ONLY and excludes internal-registry names by
                      design, so the tools-native registry is the machine
                      face — recorded as Recon deviation 1, issue #866-a.)
  face B (teaching)   a SKILL teaching mention OR a references/ entry

Baseline ratchet (the scripts/retirement_gate.py pattern): existing
unregistered CLIs ride `devkit/.discovery-gate-baseline.txt` (one
repo-relative source key per line — known debt, dispositioned by PR
866-b: register four faces or retire). Findings - baseline = new
violations -> exit 1. The ratchet only shrinks.

Exit codes: 0 = pass; 1 = new violations (or baseline missing);
2 = usage. Fail-closed on unexpected exceptions via the quality_gates
runner wrapper (same as Gates 5-8).

Usage:
  uv run python devkit/discovery_gate.py                 # check (default root)
  uv run python devkit/discovery_gate.py --root <dir>
  uv run python devkit/discovery_gate.py --print-baseline  # emit keys for a fresh ledger
  uv run python devkit/discovery_gate.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_REL = "devkit/.discovery-gate-baseline.txt"
REGISTRY_REL = "tools/_INDEX.yaml"

RC_PASS = 0
RC_FAIL = 1
RC_USAGE = 2


def _out_encoding() -> str:
    return getattr(sys.stdout, "encoding", None) or "utf-8"


def _safe(text: str) -> str:
    """GBK-console safety (same lesson as devkit/doc_sync._safe)."""
    enc = _out_encoding()
    return text.encode(enc, "replace").decode(enc, "replace")


def enumerate_subjects(root: Path) -> list:
    """tools/ ``__main__`` CLI repo-relative paths (infra trio + _lib
    excluded — the generator/querier never enters its own registry)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import relib_audit  # engine reuse: same subject definition, one source
    return sorted(rel for rel in relib_audit.production_subjects(root)
                  if rel.startswith("tools/"))


def _load_baseline_keys(path: Path | None, root: Path) -> list:
    p = path if path is not None else root / BASELINE_REL
    if not p.is_file():
        raise FileNotFoundError(
            f"baseline ledger missing: {p} — create it from "
            f"--print-baseline output (existing debt only; never for a NEW CLI)")
    keys = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        key = ln.split("#", 1)[0].strip()  # allow inline `# reason` comments
        if key:
            keys.append(key)
    return keys


def subject_faces(root, rel: str) -> set:
    """Discovery faces found for one subject: subset of
    {'registry', 'teaching'} (empty set = fully undiscoverable)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import relib_audit
    faces = set()
    if relib_audit._hits(rel, relib_audit._face_corpus(
            root, (REGISTRY_REL,)), bare_stem=True):
        faces.add("registry")
    if relib_audit._hits(rel, relib_audit._face_corpus(
            root, ("skills/**", "references/**")), bare_stem=True):
        faces.add("teaching")
    return faces


def find_violations(root, baseline_keys=None, baseline_path=None) -> list:
    """Return human-readable violation strings (empty = gate green).

    baseline_keys (list) overrides loading from baseline_path / the
    default ledger file; pass [] for a no-debt ratchet."""
    root = Path(root)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import relib_audit

    subjects = enumerate_subjects(root)
    if not subjects:
        return []
    missing_baseline = baseline_keys is None
    if baseline_keys is None:
        baseline_keys = _load_baseline_keys(baseline_path, root)
    baseline = set(baseline_keys)

    violations: list = []
    for rel in subjects:
        faces = subject_faces(root, rel)
        if len(faces) == 2:
            continue
        if rel in baseline:
            continue
        missing = sorted({"registry", "teaching"} - faces)
        violations.append(
            f"{rel}: __main__ CLI missing discovery face(s): "
            f"{'+'.join(missing)} — "
            f"register in {REGISTRY_REL} AND teach in skills/ or references/ "
            "in the same change; existing debt only may ride "
            f"{BASELINE_REL}")

    if missing_baseline:
        stale = [k for k in baseline_keys
                 if k not in subjects and not (root / k).is_file()]
        for k in stale:
            print(_safe(f"  [note] baseline key no longer exists "
                        f"(prune it): {k}"), file=sys.stderr)
    return violations


def check(root: str | None = None) -> int:
    root_path = Path(root) if root else REPO_ROOT
    try:
        violations = find_violations(root_path)
    except FileNotFoundError as exc:
        print(_safe(f"FAIL Gate 9 (discovery face): {exc}"), file=sys.stderr)
        return RC_FAIL
    if violations:
        print(_safe(f"FAIL Gate 9 (discovery face): {len(violations)} "
                    f"tools/ CLI(s) not discoverable:"))
        for v in violations:
            print(_safe(f"  {v}"))
        return RC_FAIL
    print("[PASS] Gate 9 discovery face: every tools/ __main__ CLI is "
          "registry-registered and taught (or riding the #866-b baseline)")
    return RC_PASS


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="#866 discovery-face gate")
    ap.add_argument("--root", default=None,
                    help="repo root (default: this repo)")
    ap.add_argument("--baseline", default=None,
                    help="baseline ledger path override")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--print-baseline", action="store_true",
                    help="emit ledger keys for the current findings")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else REPO_ROOT
    try:
        if args.print_baseline:
            for rel in enumerate_subjects(root):
                if len(subject_faces(root, rel)) < 2:
                    print(f"{rel}\t# existing debt — disposition in #866-b")
            return RC_PASS
        violations = find_violations(
            root, baseline_path=Path(args.baseline) if args.baseline else None)
    except FileNotFoundError as exc:
        print(_safe(f"FAIL: {exc}"), file=sys.stderr)
        return RC_FAIL
    if args.json:
        print(json.dumps({"violations": violations,
                          "counts": {"new_violations": len(violations)}},
                         ensure_ascii=False, indent=1))
    else:
        for v in violations:
            print(_safe(v))
    return RC_PASS if not violations else RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
